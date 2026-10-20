param([switch]$DebugConsole)
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$env:PYTHONUTF8 = '1'
$env:PYINSTALLER_CONFIG_DIR = Join-Path $projectRoot '.cache/pyinstaller-config'
$buildPython = Join-Path $projectRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $buildPython)) { $buildPython = 'python' }
Push-Location -LiteralPath $projectRoot
try {
    $launcherOutput = Join-Path $projectRoot 'dist/windows/项目航图-云端'
    $releaseOutput = Join-Path $projectRoot '.cache/unified-launcher-release'
    $iconPath = Join-Path $projectRoot 'windows/assets/app_icon.ico'
    New-Item -ItemType Directory -Path $launcherOutput -Force | Out-Null
    $windowMode = if ($DebugConsole) { '--console' } else { '--windowed' }
    & $buildPython -m PyInstaller --noconfirm --clean $windowMode --onefile --name '项目航图-云端' --distpath $releaseOutput --workpath '.cache/unified-launcher' --specpath '.cache' --icon $iconPath 'windows/unified_launcher.py'
    if ($LASTEXITCODE -ne 0) { throw '统一入口构建失败' }
    Copy-Item -LiteralPath (Join-Path $releaseOutput '项目航图-云端.exe') -Destination (Join-Path $launcherOutput '项目航图-云端.exe') -Force
} finally { Pop-Location }
