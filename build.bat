@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

set "PYTHON_BIN="
set "DRY_RUN="
set "BUILD_ARGS=%*"
set "BUILD_CANCELLED="
set "VERSION_COMMAND="

if defined SPRITELENS_PYTHON if exist "%SPRITELENS_PYTHON%" set "PYTHON_BIN=%SPRITELENS_PYTHON%"
if not defined PYTHON_BIN if exist "%~dp0venv\Scripts\python.exe" set "PYTHON_BIN=%~dp0venv\Scripts\python.exe"
if not defined PYTHON_BIN if exist "%~dp0.venv\Scripts\python.exe" set "PYTHON_BIN=%~dp0.venv\Scripts\python.exe"

if not defined PYTHON_BIN (
    echo Missing Python runtime for packaging.
    echo Searched:
    echo   1. SPRITELENS_PYTHON
    echo   2. %~dp0venv\Scripts\python.exe
    echo   3. %~dp0.venv\Scripts\python.exe
    echo.
    echo Example:
    echo   set SPRITELENS_PYTHON=D:\Python\python.exe
    call :maybe_pause
    exit /b 1
)

echo Using Python:
echo   %PYTHON_BIN%
echo.

if "%~1"=="" call :choose_build_target
if defined BUILD_CANCELLED (
    echo Packaging cancelled.
    call :maybe_pause
    exit /b 0
)

for %%A in (%BUILD_ARGS%) do (
    if /I "%%~A"=="--dry-run" set "DRY_RUN=1"
    if /I "%%~A"=="--get-version" set "VERSION_COMMAND=1"
    if /I "%%~A"=="--set-version" set "VERSION_COMMAND=1"
)

if defined VERSION_COMMAND goto version_command

echo [1/3] Checking build configuration...
if defined DRY_RUN (
    echo Dry-run mode: skipping Nuitka import check.
) else (
    "%PYTHON_BIN%" -B -c "import nuitka" >nul 2>nul
    if errorlevel 1 (
        echo Nuitka is missing. Installing requirements-build.txt...
        "%PYTHON_BIN%" -B -m pip install -r requirements-build.txt
        if errorlevel 1 goto failed
    )
)

echo.
echo [2/3] Building SpriteLens...
"%PYTHON_BIN%" -B build.py %BUILD_ARGS%
if errorlevel 1 goto failed

echo.
if defined DRY_RUN (
    echo Dry-run finished. No executable was created.
    goto done
)

echo Packaging finished.
for /f "delims=" %%F in ('dir /b /a-d /o-d "%~dp0build\SpriteLens_*.exe" 2^>nul') do (
    echo Latest executable:
    echo   %~dp0build\%%F
    goto done
)

:done
call :maybe_pause
exit /b 0

:failed
set "EXIT_CODE=%ERRORLEVEL%"
echo.
echo Packaging failed. Exit code: %EXIT_CODE%
call :maybe_pause
exit /b %EXIT_CODE%

:maybe_pause
if not defined SPRITELENS_NO_PAUSE pause
exit /b 0

:version_command
"%PYTHON_BIN%" -B build.py %BUILD_ARGS%
set "EXIT_CODE=%ERRORLEVEL%"
call :maybe_pause
exit /b %EXIT_CODE%

:choose_build_target
rem Keep this batch file ASCII-only; build.py renders the bilingual menu.
rem Only the final stdout line is captured as BUILD_ARGS.
set "BUILD_ARGS="
for /f "delims=" %%A in ('"%PYTHON_BIN%" -B build.py --menu') do set "BUILD_ARGS=%%A"
if not defined BUILD_ARGS set "BUILD_CANCELLED=1"
exit /b 0
