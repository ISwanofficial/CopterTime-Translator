@echo off
setlocal
title CopterTime Translator v0.2
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    call install_and_run.bat
    exit /b
)

call ".venv\Scripts\activate.bat"
python app.py

if errorlevel 1 (
    echo.
    echo Application stopped with an error.
    pause
)
