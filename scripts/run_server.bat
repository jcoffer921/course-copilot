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
rem in its command line) and it catches the whole --reload supervisor tree
rem (launcher + worker), not just one piece that would otherwise respawn.
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*uvicorn*' -and $_.CommandLine -like '*config.asgi:application*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"

rem Give the port a moment to free up (avoids "timeout" here since it can
rem error out under redirected/non-interactive stdin; ping is a portable sleep).
ping -n 3 127.0.0.1 >nul

venv\Scripts\uvicorn.exe config.asgi:application --reload
