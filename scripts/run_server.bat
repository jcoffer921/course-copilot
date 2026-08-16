@echo off
setlocal

rem Restarts the course-copilot ASGI server: kills any previous instance of
rem THIS project's uvicorn process first, so re-running this script doesn't
rem fail with "address already in use" or leave orphaned processes behind.

cd /d "%~dp0.."

if not exist "venv\" (
    echo Error: venv\ not found.
    echo Run this first:
    echo   python -m venv venv
    echo   venv\Scripts\pip install -r requirements.txt
    exit /b 1
)

if not exist "venv\Scripts\uvicorn.exe" (
    echo Error: venv\ exists but uvicorn isn't installed in it.
    echo Run: venv\Scripts\pip install -r requirements.txt
    exit /b 1
)

rem Kill any previous instance of THIS project's server. Matched as two
rem required substrings ("uvicorn" and "config.asgi:application"), not one
rem contiguous string like `pkill -f "uvicorn config.asgi:application"` would
rem use on Linux/macOS -- Windows invokes the real binary as "uvicorn.exe",
rem so that exact contiguous substring never appears in the real command
rem line. Both substrings are still required, so this stays scoped to this
rem project's server (nothing else on a dev box has "config.asgi:application"
rem in its command line).
rem
rem Killed via `taskkill /F /T`, not Stop-Process: uvicorn's --reload on
rem Windows spawns its actual worker through Python's multiprocessing module
rem (Windows has no fork()), so the worker's own command line is
rem `python.exe -c "from multiprocessing.spawn import spawn_main; ..."
rem --multiprocessing-fork` -- it contains neither "uvicorn" nor
rem "config.asgi:application" and this match can never see it directly.
rem Stop-Process only kills the matched PID itself, orphaning that worker;
rem it keeps holding the port and keeps serving whatever code was loaded
rem when it started, silently, for as long as it survives. taskkill's /T
rem kills the whole OS-level process tree under each matched PID
rem (parent-child, not command-line matching), which reaches the worker
rem regardless of how its command line looks. Confirmed via a live repro:
rem after several restarts, curl against the "running" server returned
rem template content from hours earlier -- Stop-Process had been orphaning
rem a fresh worker every time, and whichever old one still held the port
rem kept answering.
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*uvicorn*' -and $_.CommandLine -like '*config.asgi:application*' } | ForEach-Object { taskkill /F /T /PID $_.ProcessId 2>$null }"

rem Give the port a moment to free up (avoids "timeout" here since it can
rem error out under redirected/non-interactive stdin; ping is a portable sleep).
ping -n 3 127.0.0.1 >nul

venv\Scripts\uvicorn.exe config.asgi:application --reload
