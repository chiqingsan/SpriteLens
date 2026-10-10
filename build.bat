@echo off
rem SpriteLens 打包入口（双击或命令行均可）。自动查找 venv 的 Python。
setlocal
chcp 65001 >nul
cd /d "%~dp0"

set "PYTHON_BIN="
if exist "%~dp0.venv\Scripts\python.exe" set "PYTHON_BIN=%~dp0.venv\Scripts\python.exe"
if not defined PYTHON_BIN if exist "%~dp0venv\Scripts\python.exe" set "PYTHON_BIN=%~dp0venv\Scripts\python.exe"

if not defined PYTHON_BIN (
    echo [build] 未找到 Python 运行时，请先创建虚拟环境：
    echo     python -m venv .venv
    echo     .venv\Scripts\pip install -r requirements.txt
    echo     .venv\Scripts\pip install -r requirements-build.txt
    pause
    exit /b 1
)

"%PYTHON_BIN%" "%~dp0build.py" %*
set "EXITCODE=%ERRORLEVEL%"
if not "%EXITCODE%"=="0" (
    echo.
    echo [build] 打包失败，退出码 %EXITCODE%
)
pause
endlocal
exit /b %EXITCODE%
