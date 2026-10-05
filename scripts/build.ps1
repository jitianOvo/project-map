$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$pythonExe = (Get-Command python -CommandType Application | Select-Object -First 1).Source
$pythonDirectory = Split-Path -Parent $pythonExe
$previousPath = $env:PATH
Push-Location -LiteralPath $projectRoot
try {
    # 避免其他工具在 PATH 中携带的旧版 CRT / Qt DLL 混入单文件包。
    $env:PATH = @($pythonDirectory, (Join-Path $pythonDirectory 'Scripts'), (Join-Path $env:SystemRoot 'System32'), $env:SystemRoot) -join ';'
    & $pythonExe -m PyInstaller --noconfirm --clean 项目航图.spec
    if ($LASTEXITCODE -ne 0) { throw "打包失败，退出码 $LASTEXITCODE" }
}
finally {
    $env:PATH = $previousPath
    Pop-Location
}
