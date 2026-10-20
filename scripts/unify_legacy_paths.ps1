param([string]$ProjectRoot = (Join-Path $PSScriptRoot '..'))

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path -LiteralPath $ProjectRoot).Path
$distRoot = [IO.Path]::GetFullPath((Join-Path $root 'dist'))
$archiveRoot = [IO.Path]::GetFullPath((Join-Path $root 'Backups\整合迁移-20261006\内层归档'))
if (-not $archiveRoot.StartsWith($root + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) { throw '归档路径越界' }
if (-not (Test-Path -LiteralPath (Join-Path $root 'Backups\整合迁移-20261006\migration.json'))) { throw '请先完成数据合并和备份' }
New-Item -ItemType Directory -Path $archiveRoot -Force | Out-Null
foreach ($name in @('Markdown', 'Media', 'Data', 'Backups')) {
    $inner = [IO.Path]::GetFullPath((Join-Path $distRoot $name))
    $outer = [IO.Path]::GetFullPath((Join-Path $root $name))
    $archive = [IO.Path]::GetFullPath((Join-Path $archiveRoot $name))
    if (-not $inner.StartsWith($distRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) { throw '内层目录越界' }
    if (-not $archive.StartsWith($archiveRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) { throw '归档目标越界' }
    New-Item -ItemType Directory -Path $outer -Force | Out-Null
    if (Test-Path -LiteralPath $inner) {
        $item = Get-Item -LiteralPath $inner -Force
        if ($item.LinkType) {
            if ([IO.Path]::GetFullPath($item.Target) -ne $outer) { throw "已有链接指向其他位置：$inner" }
            continue
        }
        if (Test-Path -LiteralPath $archive) { throw "归档已存在，不覆盖：$archive" }
        Move-Item -LiteralPath $inner -Destination $archive
    }
    New-Item -ItemType Junction -Path $inner -Target $outer | Select-Object FullName, Target
}
