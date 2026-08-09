#!/usr/bin/env bash
# Restarts the course-copilot ASGI server: kills any previous instance of
# THIS project's uvicorn process first, so re-running this script doesn't
# fail with "address already in use" or leave orphaned processes behind.
set -euo pipefail

cd "$(dirname "$0")/.."

UVICORN_TARGET="uvicorn config.asgi:application"

if [ ! -d "venv" ]; then
    echo "Error: venv/ not found." >&2
    echo "Run this first: python -m venv venv, then activate it and run:" >&2
    echo "  pip install -r requirements.txt" >&2
    exit 1
fi

if [ -f "venv/bin/uvicorn" ]; then
    UVICORN="venv/bin/uvicorn"
elif [ -f "venv/Scripts/uvicorn.exe" ] || [ -f "venv/Scripts/uvicorn" ]; then
    UVICORN="venv/Scripts/uvicorn"
else
    echo "Error: venv/ exists but uvicorn isn't installed in it." >&2
    echo "Run 'pip install -r requirements.txt' with the venv activated first." >&2
    exit 1
fi

# Kill any previous instance of THIS project's server — scoped to the exact
# command string so it never touches unrelated python/uvicorn processes
# (other projects, Jupyter, etc).
if command -v pkill >/dev/null 2>&1; then
    pkill -f "$UVICORN_TARGET" 2>/dev/null || true
elif command -v pwsh.exe >/dev/null 2>&1 || command -v powershell.exe >/dev/null 2>&1; then
    # Git Bash on Windows has no pkill. PowerShell's Win32_Process.CommandLine
    # gives the same "match on full command string" scope as `pkill -f` — but
    # matched as two required substrings, not one contiguous string: Windows
    # invokes the real binary as "uvicorn.exe", so the literal string "uvicorn
    # config.asgi:application" (space right after "uvicorn") never actually
    # appears there. Both substrings are still required, so this stays just
    # as scoped to this project's server (nothing else on a dev box has
    # "config.asgi:application" in its command line) while also catching the
    # uvicorn --reload supervisor's full process tree (launcher + worker) —
    # killing only the worker leaves the supervisor to silently respawn it.
    PS_BIN="$(command -v pwsh.exe || command -v powershell.exe)"
    "$PS_BIN" -NoProfile -Command \
        "Get-CimInstance Win32_Process | Where-Object { \$_.CommandLine -like '*uvicorn*' -and \$_.CommandLine -like '*config.asgi:application*' } | ForEach-Object { Stop-Process -Id \$_.ProcessId -Force -ErrorAction SilentlyContinue }" \
        || true
else
    echo "Warning: no pkill or PowerShell found — skipping stale-instance check." >&2
fi

sleep 1.5

exec "$UVICORN" config.asgi:application --reload
