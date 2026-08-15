@echo off
rem Thin wrapper so `.\run_server.bat` works from the project root. The real
rem logic lives in scripts\run_server.bat — kept in one place to avoid drift.
call "%~dp0scripts\run_server.bat" %*
