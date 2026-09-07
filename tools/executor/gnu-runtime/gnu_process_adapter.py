"""Opt-in GNU process composition preserving the existing complete policy owner.

The first admission requires logical read access everywhere (no DENY entries).
Its actual Landlock grants remain much narrower. Namespace mutation and writes
are still per-operation decisions from the original complete managed policy.
"""
import asyncio
import json
import os
from pathlib import Path
from types import SimpleNamespace

from tools.executor.exec_server import BackendCall, RpcError, encode_message
from tools.executor.native_processes import NativeProcessesBackend, _receive_supervisor, _receive, _packet, _wait_owned, _finish
from tools.policy.managed_policy import parse_context
from tools.executor.native_files import NativeFilesBackend
from tools.executor.native_process_policy import NativeProcessPolicy
from gnu_runtime_capacity import runtime_fd_admission


class GnuProcessesBackend(NativeProcessesBackend):
    def __init__(self, runner, workspace, *, proot, rootfs, loader, loader32, scratch, guest_tmp,
                 guest_workspace='/workspace', files_backend, limits=None, parent_environment=None):
        super().__init__(runner, workspace, executables={'__foldgpt_gnu_v1':proot},
            guest_workspace=guest_workspace, files_backend=files_backend, limits=limits,
            parent_environment=parent_environment)
        roots=[Path(p).resolve(strict=True) for p in (workspace,scratch,guest_tmp)]
        if any(a==b or a in b.parents or b in a.parents for i,a in enumerate(roots) for b in roots[i+1:]):
            raise ValueError('GNU workspace, runtime scratch and guest temporary roots must be disjoint')
        self.gnu_fd_admission=runtime_fd_admission(proot)
        self.gnu_inputs=tuple(str(Path(p).resolve(strict=True)) for p in (rootfs,loader,loader32,scratch,guest_tmp))+(str(self.gnu_fd_admission['capacity']),)
        self.gnu_tmp=NativeFilesBackend(files_backend.helper,guest_tmp,guest_workspace='/tmp')
        self.gnu_session=None
        self.gnu_close_failed=False

    async def close(self, session_id):
        if self.gnu_close_failed or self.quarantined:
            raise RpcError(-32603,'GNU roots retain their leases after unknown descendant cleanup')
        if self.gnu_session is not None and session_id!=self.gnu_session:
            raise RpcError(-32600,'GNU adapter belongs to another session')
        try:await super().close(session_id)
        except BaseException:
            self.gnu_close_failed=True
            raise
        # A failed cleanup raises above; retain the temporary-root lease then.
        if not self.gnu_tmp.closed:
            self.gnu_tmp.closed=True
            os.close(self.gnu_tmp.root)

    def _root_policy(self, record, temporary):
        if not temporary:return record.policy
        # Preserve the exact parsed policy and intent; only pathname projection
        # changes to the other pinned root. cwd is never rewritten to grant /tmp.
        return SimpleNamespace(policy=record.policy.policy,intent=record.policy.intent,
            backend=self.gnu_tmp,decisions=record.policy.decisions)

    async def _start(self, call, notify):
        if self.gnu_tmp.closed or self.gnu_close_failed:
            raise RpcError(-32600,'GNU adapter is closed or quarantined')
        if self.gnu_session is not None and call.session_id!=self.gnu_session:
            raise RpcError(-32600,'GNU adapter belongs to another session')
        params=call.params
        try:policy=parse_context(params.get('sandbox'))
        except ValueError as error:raise RpcError(-32602,str(error)) from error
        if not policy.decide('/').can_read or any(entry.access.value=='deny' for entry in policy.resolved_entries):
            raise RpcError(-32602,'GNU metadata admission requires root read with no DENY entries; complete policies are never approximated')
        if params.get('arg0') is not None:
            raise RpcError(-32602,'GNU custom argv0 is not yet admitted')
        argv=params['argv']
        if not argv or not argv[0].startswith('/'):
            raise RpcError(-32602,'GNU command must have an absolute guest executable path')
        if params['cwd']!=self.files_backend.mount.uri:
            raise RpcError(-32602,'GNU cwd must match this pinned workspace')
        self.gnu_tmp._inspect(policy)
        self.gnu_session=call.session_id
        # Keep the original policy and environment bytes unchanged. Only argv is
        # translated to the immutable runtime's private constructor convention.
        params['argv']=['__foldgpt_gnu_v1',*self.gnu_inputs,self.guest_workspace,'--',*argv]
        result=await super()._start(BackendCall(call.session_id,call.request_id,call.method,encode_message(params),call.trace_json),notify)
        self.processes[(call.session_id,params['processId'])].gnu_original_request=call.params_json
        return result

    @staticmethod
    def _mutation(policy_owner,message):
        if set(message)!={'type','id','operation','pathHex','destinationHex'} or type(message['id']) is not int:
            raise RpcError(-32603,'Invalid GNU mutation message')
        operation=message['operation']
        if operation not in {'mkdir','unlink','rmdir','rename'}:
            raise RpcError(-32603,'Unsupported GNU namespace mutation')
        backend=policy_owner.backend;policy=policy_owner.policy
        def parts(value):
            raw=bytes.fromhex(value);text=raw.decode('utf-8')
            if raw.hex()!=value or not text or any(p in ('','.','..') for p in text.split('/')):
                raise ValueError('Invalid copied native mutation path')
            return tuple(text.split('/'))
        path=parts(message['pathHex']);destination=parts(message['destinationHex']) if message['destinationHex'] else None
        metadata,_,_,nodes=backend._inspect(policy)
        try:
            backend._require_write(policy,backend.mount.append(path),metadata)
            if path[-1]=='.git': raise PermissionError('gitdir mutations are unsupported')
            if operation=='rename':
                if destination is None: raise ValueError('Missing rename destination')
                backend._require_write(policy,backend.mount.append(destination),metadata)
                if destination[-1]=='.git': raise PermissionError('gitdir mutations are unsupported')
                for entry in nodes:
                    if entry[:len(path)]==path:
                        backend._require_write(policy,backend.mount.append(entry),metadata)
                        backend._require_write(policy,backend.mount.append(destination+entry[len(path):]),metadata)
                    if entry[:len(destination)]==destination:
                        backend._require_write(policy,backend.mount.append(entry),metadata)
            elif destination is not None: raise ValueError('Unexpected mutation destination')
        except PermissionError:
            allowed=0
        else: allowed=1
        return {'id':message['id'],'allow':allowed}

    async def _control(self, record, endpoint):
        record.supervisor_fd,record.supervisor_identity=await _receive_supervisor(endpoint,record.process.pid)
        await _packet(endpoint,b'P')
        record.supervisor_identity['acknowledgedBeforeWorker']=True
        while True:
            message=await _receive(endpoint)
            if message is None:
                if record.native_result is None: raise RpcError(-32603,'Native lifecycle socket closed without completion')
                return
            if type(message) is not dict: raise RpcError(-32603,'Invalid GNU lifecycle message')
            kind=message.get('type')
            if kind in {'open','openTmp','mutation','mutationTmp'}:
                temporary=kind.endswith('Tmp')
                owner=self._root_policy(record,temporary)
                if temporary:message={**message,'type':kind[:-3]}
                decision=(lambda m:NativeProcessPolicy.decide(owner,m)) if message['type']=='open' else lambda m:self._mutation(owner,m)
                task=asyncio.create_task(asyncio.to_thread(decision,message))
                try: reply=await _wait_owned(task)
                except asyncio.CancelledError:
                    await _finish(task);raise
                try: await _packet(endpoint,json.dumps(reply,separators=(',',':')).encode())
                except BrokenPipeError:
                    if not record.termination_requested: raise
            elif kind=='started':
                required={'type','pid','profile','uidTasksObserved','uidTaskBudget','uidNprocLimit','inheritedNprocSoft','inheritedNprocHard'}
                if record.native_started is not None or record.native_result is not None or set(message)!=required or message['profile']!='managed-process-v2' or any(type(message[k]) is not int or message[k]<0 for k in required-{'type','profile'}):
                    raise RpcError(-32603,'GNU startup contract differs')
                record.native_started=message
                if record.termination_requested:self._terminate(record);continue
                record.state='running';record.started.set_result(None)
            elif kind=='exited':
                if record.native_started is None or record.exit_code is not None or set(message)!={'type','exitCode','signal'}:
                    raise RpcError(-32603,'Invalid native leader exit observation')
                code,signum=message['exitCode'],message['signal']
                if type(code) is not int or type(signum) is not int or not -1<=code<=255 or not 0<=signum<=64 or (signum and code!=-1) or (not signum and code<0):
                    raise RpcError(-32603,'Invalid native exit status')
                record.exit_code=128+signum if signum else code
                if record.started.done() and record.started.exception() is None:
                    self._event(record,'process/exited',{'exitCode':record.exit_code,'sandboxDenied':False})
                record.write_changed.set()
            elif kind=='result':
                required={'type','outcome','exitCode','signal','cleanupComplete','started','grants','denials','stdoutBytes','stderrBytes','stage','errno'}
                if record.native_result is not None or set(message)!=required or message['outcome'] not in {'exited','cancelled','timeout','output_limit','setup_error','broker_error','cleanup_error'} or any(type(message[k]) is not bool for k in ('cleanupComplete','started')) or any(type(message[k]) is not int or message[k]<0 for k in ('signal','grants','denials','stdoutBytes','stderrBytes','stage','errno')) or type(message['exitCode']) is not int or not -1<=message['exitCode']<=255:
                    raise RpcError(-32603,'Invalid GNU completion')
                record.native_result=message
                if not record.started.done():record.started.set_exception(RpcError(-32603,'GNU process failed before verified exec'))
            else: raise RpcError(-32603,'Unknown GNU lifecycle event')
