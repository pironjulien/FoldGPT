import asyncio,base64,importlib,json,os,sys,tempfile
from pathlib import Path
repo=Path('/mnt/c/Dev/ChatgptFold');sys.path.insert(0,str(repo))
factory=importlib.import_module('tools.executor.bionic-supervisor.factory').factory
kernel=importlib.import_module('tools.executor.bionic-supervisor.test_kernel')
from tools.executor.exec_server import BackendCall,encode_message
async def run():
 work=Path('/var/tmp/foldgpt-runpath-review-0w3u5wxr')
 base=Path(tempfile.mkdtemp(prefix='foldgpt-runpath-mediated-',dir='/var/tmp'))
 workspace=base/'workspace';workspace.mkdir(mode=0o700);(workspace/'private').mkdir(mode=0o700);(workspace/'.git').mkdir(mode=0o700)
 build=repo/'downloads/bionic-supervisor/foldgpt-bionic-supervisor-qKM94iHA'
 backend=factory({'helper':str(build/'native-files'),'handleHelper':str(build/'native-file-handle'),'processRunner':str(build/'runner'),'workspace':str(workspace),'executables':{'runpath':str(work/'launch/explicit-direct-all'),'admission':str(work/'launch/admission')},'runtime':[{'path':path,'execute':execute} for path,execute in [('/usr',True),('/lib',True),('/lib64',True),('/etc/ld.so.cache',False),(str(work),True)]],'parentEnvironment':{},'limits':{'wall_ms':5000}})
 output=[]
 async def notify(method,params):pass
 try:
  for index,(name,args) in enumerate([('runpath',[]),('admission',[str(work/'runtime/lib')])],1):
   policy=kernel.context(workspace)
   params={'processId':name,'argv':[name,*args],'cwd':policy['cwd'],'env':{},'tty':False,'sandbox':policy}
   await backend.handle(BackendCall('runpath',index,'process/start',encode_message(params)),notify)
   record=backend.processes.processes[('runpath',name)]
   await asyncio.wait_for(asyncio.shield(record.finished),8)
   streams={stream:b''.join(base64.b64decode(c['chunk']) for c,_ in record.output if c['stream']==stream).decode() for stream in ('stdout','stderr')}
   actual={'name':name,'result':record.native_result,'closed':record.closed,'quarantined':backend.processes.quarantined,'supervisorReturncode':record.process.returncode,**streams}
   output.append(actual)
   assert record.native_result['exitCode']==0 and record.native_result['cleanupComplete'] and record.closed and not backend.processes.quarantined,actual
 finally:await backend.close('runpath')
 report={'schema':'foldgpt.runpath-mediated-host-review.v1','success':True,'androidExecution':False,'uid':os.getuid(),'loader':'glibc; real production supervisor mediation; not Samsung Bionic execution','observations':output}
 (base/'report.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps({'path':str(base/'report.json'),'report':report}))
asyncio.run(run())
