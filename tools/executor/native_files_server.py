"""Explicit native filesystem endpoint for the audited exec-server transport.

The supervisor supplies an exclusively owned workspace and trusted native
helper. This endpoint admits only NativeFilesBackend's supported file methods;
it is not a managed command executor or a default Desktop environment.
"""
import argparse
import asyncio
from pathlib import Path
import sys

# Direct script invocation also works with Python -I -S, including the trusted
# interpreter launched outside PRoot by the Android diagnostic service.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.executor.exec_server import ExecServer, local_environment_info, serve_stdio
from tools.executor.native_files import NativeFilesBackend


async def run(helper, workspace, guest_workspace):
    backend = NativeFilesBackend(helper, workspace, guest_workspace=guest_workspace)
    server = None
    try:
        info = local_environment_info()
        info["cwd"] = backend.mount.uri
        server = ExecServer(backend, environment_info=info)
        await serve_stdio(server)
    finally:
        # Construction errors must release the same native workspace lease too.
        if server is None:
            await backend.close(None)
        else:
            await server.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--helper", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--guest-workspace", required=True)
    args = parser.parse_args()
    asyncio.run(run(args.helper, args.workspace, args.guest_workspace))


if __name__ == "__main__":
    main()
