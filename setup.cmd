@echo off
REM One-command setup (Windows). A batch file is immune to the PowerShell
REM execution-policy GPO axis and is not itself an .exe, so it runs where a
REM PowerShell-based entry would be blocked. Runs from cmd.exe or a PS prompt.
REM Delegates to install.py under a base python.
setlocal
cd /d "%~dp0"
if defined PYTHON (set "PY=%PYTHON%") else (set "PY=py -3")
where py >nul 2>nul
if errorlevel 1 (
    echo ERROR: 'py' launcher not found. Install Python 3.10+ from https://python.org
    echo        ^(or set PYTHON=C:\path\to\python.exe and re-run^).
    exit /b 1
)
%PY% install.py %*
exit /b %ERRORLEVEL%
