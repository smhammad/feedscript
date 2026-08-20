@echo off
REM Feedscript Windows launcher (dev mode — equivalent of start.command on Mac).
REM Double-click to run. First launch creates a venv and installs everything.

setlocal enableextensions
cd /d "%~dp0"

echo.
echo   +---------------------------------------+
echo   ^|           Feedscript - Launch         ^|
echo   +---------------------------------------+
echo.

set "VENV_PY=%cd%\venv\Scripts\python.exe"

REM Python 3.10+ is required: yt-dlp dropped 3.9, and on an older Python pip
REM silently resolves it to a release Instagram has since broken.
REM
REM A venv that already runs a new enough Python is self-sufficient, so check
REM it before looking for (or demanding) a system Python. Unlike launcher.py,
REM this script does not run from inside the venv, so a venv whose interpreter
REM will not answer is safe to rebuild here.
if not exist "%VENV_PY%" goto :find_python
call :pyver "%VENV_PY%"
if not defined PYVER goto :find_python
if %PYVER% GEQ 310 goto :venv_ready

:find_python
set "PYTHON="
REM Windows ships no python3.12 executable — the py launcher is the supported
REM way to ask for a specific version, so it is tried first.
call :try py -3.14
call :try py -3.13
call :try py -3.12
call :try py -3.11
call :try py -3.10
call :try py -3
call :try python
call :try python3
if defined PYTHON goto :have_python

echo Feedscript needs Python 3.10 or newer.
echo Install it from https://www.python.org/downloads/windows/
echo ^(tick "Add python.exe to PATH" during setup^), then re-run this file.
pause
exit /b 1

:have_python
echo Using %PYTHON%
%PYTHON% --version

if not exist venv goto :make_venv
echo Rebuilding Python environment ^(the existing one is not usable^)...
rmdir /s /q venv
if exist venv (
    echo Could not remove the old venv. Close any running Feedscript window and try again.
    pause
    exit /b 1
)

:make_venv
echo Preparing Python environment...
%PYTHON% -m venv venv
if not exist "%VENV_PY%" (
    echo Could not create the virtual environment.
    pause
    exit /b 1
)

:venv_ready
"%VENV_PY%" -m pip install --upgrade pip >nul 2>&1

"%VENV_PY%" -c "import webview" >nul 2>&1
if errorlevel 1 (
    echo Installing app window library...
    "%VENV_PY%" -m pip install pywebview
)

"%VENV_PY%" launcher.py
endlocal
exit /b 0

REM ---------------------------------------------------------------- helpers
REM Sets PYVER to MAJOR*100+MINOR for the interpreter given as arguments, or
REM leaves it undefined if that interpreter does not run. A marker file is used
REM rather than `for /f` so quoted paths and redirection need no escaping, and
REM rather than errorlevel because a crashing interpreter can exit with a
REM negative code, which `if errorlevel 1` reads as success.
:pyver
set "PYVER="
del "%TEMP%\fs_pyver.txt" >nul 2>&1
%* -c "import sys;f=open(r'%TEMP%\fs_pyver.txt','w');f.write(str(sys.version_info[0]*100+sys.version_info[1]));f.close()" >nul 2>&1
if exist "%TEMP%\fs_pyver.txt" set /p PYVER=<"%TEMP%\fs_pyver.txt"
del "%TEMP%\fs_pyver.txt" >nul 2>&1
exit /b 0

:try
if defined PYTHON exit /b 0
call :pyver %*
if not defined PYVER exit /b 0
if %PYVER% GEQ 310 set "PYTHON=%*"
exit /b 0
