#!/bin/sh
# Official Desktop executable override, separate from every official file.
# The process and file policy remains the selected environment's responsibility.
exec /usr/bin/python3 -B /usr/local/lib/foldgpt/executor/tools/executor/app_server_adapter.py \
    --official /usr/lib/chatgpt/resources/codex \
    --environment foldgpt-native --cwd /workspace -- "$@"
