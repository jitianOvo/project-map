param([string]$Executable = (Join-Path $PSScriptRoot '..\dist\项目航图.exe'))

$ErrorActionPreference = 'Stop'
$exePath = (Resolve-Path -LiteralPath $Executable).Path
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$buildRoot = [IO.Path]::GetFullPath((Join-Path $projectRoot 'build'))
$testRoot = Join-Path $buildRoot ('frozen-smoke-' + [Guid]::NewGuid().ToString('N'))
$testExe = Join-Path $testRoot '项目航图.exe'
$previousPlatform = $env:QT_QPA_PLATFORM
$launched = $false

try {
    New-Item -ItemType Directory -Path (Join-Path $testRoot 'Markdown') | Out-Null
    Copy-Item -LiteralPath $exePath -Destination $testExe
    $env:QT_QPA_PLATFORM = 'offscreen'
    $primary = Start-Process -FilePath $testExe -WorkingDirectory $testRoot -WindowStyle Hidden -PassThru -RedirectStandardError (Join-Path $testRoot 'stderr.log')
    $launched = $true
    $startup = [Diagnostics.Stopwatch]::StartNew()
    while ($startup.Elapsed.TotalSeconds -lt 45) {
        $primary.Refresh()
        if ($primary.HasExited -or (Test-Path -LiteralPath (Join-Path $testRoot 'Data/settings.ini'))) { break }
        Start-Sleep -Milliseconds 300
    }
    $primary.Refresh()
    if ($primary.HasExited) {
        throw "单文件版提前退出：$($primary.ExitCode)"
    }
    foreach ($folder in @('Data', 'Media', 'Backups')) {
        if (-not (Test-Path -LiteralPath (Join-Path $testRoot $folder) -PathType Container)) {
            $details = Get-Content -Raw -LiteralPath (Join-Path $testRoot 'stderr.log')
            throw "单文件版未完成初始化：$folder $details"
        }
    }
    $secondary = Start-Process -FilePath $testExe -WorkingDirectory $testRoot -WindowStyle Hidden -PassThru
    if (-not $secondary.WaitForExit(10000) -or $secondary.ExitCode -ne 0) {
        throw '重复启动未正常退出'
    }
    $primary.Refresh()
    if ($primary.HasExited) {
        throw '重复启动后原进程意外退出'
    }
    Write-Output '单文件版初始化及单实例检查通过。'
    (Get-Item -LiteralPath $testExe).VersionInfo | Select-Object ProductName, FileVersion, ProductVersion
}
finally {
    $env:QT_QPA_PLATFORM = $previousPlatform
    if ($launched) {
        Get-CimInstance Win32_Process -Filter "Name='项目航图.exe'" |
            Where-Object { $_.ExecutablePath -eq $testExe } |
            ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
        Start-Sleep -Milliseconds 700
    }
    $resolvedTestRoot = [IO.Path]::GetFullPath($testRoot)
    if ($resolvedTestRoot.StartsWith($buildRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
        Remove-Item -LiteralPath $resolvedTestRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}
