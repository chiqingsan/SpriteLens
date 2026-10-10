@echo off
rem Create a desktop shortcut for SpriteLens (idempotent, overwrites old .lnk).
chcp 65001 >nul
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0create_shortcut.ps1"
pause
endlocal
