@echo off
REM Start the assistant (Windows, canonical). Batch entry — immune to the
REM PowerShell execution-policy GPO axis. Delegates to launch.py under a base python.
setlocal
cd /d "%~dp0"
if defined PYTHON (set "PY=%PYTHON%") else (set "PY=py -3")
%PY% launch.py %*
exit /b %ERRORLEVEL%
