@echo off
rem 小洛探探 SpriteLens launcher (double-click). No console window stays open.
rem 启动界面：pywebview 窗口 + 本地服务（原生 PyQt 界面已退役）。
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
    echo [SpriteLens] venv not found. Run first:
    echo     python -m venv .venv
    echo     .venv\Scripts\pip install -r requirements.txt
    pause
    exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" "main.py"
endlocal
