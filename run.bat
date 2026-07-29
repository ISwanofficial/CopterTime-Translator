@echo off
chcp 65001 >nul
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Создание виртуального окружения...
    py -m venv .venv
)

call ".venv\Scripts\activate.bat"

python -c "import docx, deep_translator" 2>nul
if errorlevel 1 (
    echo Установка зависимостей...
    python -m pip install --upgrade pip
    pip install -r requirements.txt
)

python app.py
if errorlevel 1 pause
