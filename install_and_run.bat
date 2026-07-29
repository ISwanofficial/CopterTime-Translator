@echo off
setlocal
title CopterTime Translator v0.2 Setup
cd /d "%~dp0"

echo ============================================
echo CopterTime Translator v0.2
echo ============================================
echo.

where py >nul 2>nul
if errorlevel 1 (
    echo Python Launcher was not found.
    echo Install Python 3.11 64-bit.
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo Creating virtual environment...
    py -3.11 -m venv .venv
    if errorlevel 1 goto error
)

call ".venv\Scripts\activate.bat"

echo Updating pip...
python -m pip install --upgrade pip
if errorlevel 1 goto error

echo Installing lightweight dependencies...
python -m pip install -r requirements.txt
if errorlevel 1 goto error

echo.
echo Starting CopterTime Translator...
python app.py
if errorlevel 1 goto error
exit /b 0

:error
echo.
echo Setup or launch failed.
echo Take a screenshot of the last lines and send it to ChatGPT.
pause
exit /b 1
