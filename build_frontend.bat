@echo off
rem Build and publish the Vue frontend into spritelens/web/static/vue.
setlocal
chcp 65001 >nul
cd /d "%~dp0"

set "PYTHON_BIN="
if exist "%~dp0.venv\Scripts\python.exe" set "PYTHON_BIN=%~dp0.venv\Scripts\python.exe"
if not defined PYTHON_BIN if exist "%~dp0venv\Scripts\python.exe" set "PYTHON_BIN=%~dp0venv\Scripts\python.exe"

if not defined PYTHON_BIN (
    echo [frontend] 未找到 Python 虚拟环境，请先创建 .venv 并安装项目依赖。
    pause
    exit /b 1
)

if exist "%~dp0spritelens\web\static\vue-pending" (
    echo [frontend] 正在清理上次发布留下的 vue-pending 临时产物...
    rmdir /s /q "%~dp0spritelens\web\static\vue-pending"
    if exist "%~dp0spritelens\web\static\vue-pending" (
        echo [frontend] 清理 vue-pending 失败，已停止构建。
        pause
        exit /b 1
    )
)
if exist "%~dp0spritelens\web\static\vue-previous" (
    echo [frontend] 检测到 vue-previous 发布残留，请先检查上次发布失败的产物。
    pause
    exit /b 1
)

set "PYTHONIOENCODING=utf-8"
"%PYTHON_BIN%" -B "%~dp0tools\frontend.py" build
set "EXITCODE=%ERRORLEVEL%"
if "%EXITCODE%"=="0" (
    echo [frontend] 构建并发布完成。
) else (
    echo.
    echo [frontend] 构建或发布失败，退出码 %EXITCODE%
)
pause
endlocal
exit /b %EXITCODE%
