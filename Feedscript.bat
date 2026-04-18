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

where python >nul 2>nul
if errorlevel 1 (
    echo Python 3 is not installed or not on PATH.
    echo Install it from https://www.python.org/downloads/windows/ then re-run this file.
    pause
    exit /b 1
)

if not exist "venv\Scripts\python.exe" (
    echo Preparing Python environment...
    python -m venv venv || (
        echo Could not create the virtual environment.
        pause
        exit /b 1
    )
)

set "VENV_PY=%cd%\venv\Scripts\python.exe"

"%VENV_PY%" -m pip install --upgrade pip >nul 2>&1

"%VENV_PY%" -c "import webview" >nul 2>&1
if errorlevel 1 (
    echo Installing app window library...
    "%VENV_PY%" -m pip install pywebview || (
        echo Could not install pywebview.
        pause
        exit /b 1
    )
)

"%VENV_PY%" launcher.py
endlocal
