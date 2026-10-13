# 创建桌面快捷方式：目标 pythonw main.py，工作目录为项目根。
# 项目根由脚本自身位置推导（tools/ 的上级），无参数依赖；重复运行覆盖旧快捷方式。
$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$pythonw = Join-Path $Root '.venv\Scripts\pythonw.exe'
if (-not (Test-Path $pythonw)) {
    Write-Host "[SpriteLens] venv 不存在，请先创建: python -m venv .venv" -ForegroundColor Red
    exit 1
}

$desktop = [Environment]::GetFolderPath('Desktop')
$lnkPath = Join-Path $desktop '小洛探探.lnk'
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($lnkPath)
$shortcut.TargetPath = $pythonw
$shortcut.Arguments = 'main.py'
$shortcut.WorkingDirectory = $Root
$shortcut.Description = '小洛探探 SpriteLens - 洛克王国数据观测'
$shortcut.IconLocation = Join-Path $Root 'resources\app.ico'  # 应用图标而非 pythonw 默认图标
$shortcut.Save()
Write-Host "已创建桌面快捷方式: $lnkPath" -ForegroundColor Green
