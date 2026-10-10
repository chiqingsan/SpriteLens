@echo off
rem SpriteLens debug launcher: run in foreground console to see errors/logs.
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo [SpriteLens] venv not found. Run first:
    echo     python -m venv .venv
    echo     .venv\Scripts\pip install -r requirements.txt
    pause
    exit /b 1
)
".venv\Scripts\python.exe" main.py
pause
endlocal
