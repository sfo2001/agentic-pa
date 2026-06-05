@echo off
REM Start the assistant (Windows, canonical). Batch entry — immune to the
REM PowerShell execution-policy GPO axis. Delegates to launch.py under a base python.
setlocal
cd /d "%~dp0"
if defined PYTHON (set "PY=%PYTHON%") else (set "PY=py -3")
where py >nul 2>nul
if errorlevel 1 (
    echo ERROR: 'py' launcher not found. Install Python 3.10+ from https://python.org
    echo        ^(or set PYTHON=C:\path\to\python.exe and re-run^).
    exit /b 1
)
%PY% launch.py %*
exit /b %ERRORLEVEL%
