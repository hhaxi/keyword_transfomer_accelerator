# Deletes only reproducible local caches/output. Keeps data, sources and installed tools.
[CmdletBinding(SupportsShouldProcess)]
param()
$ErrorActionPreference = 'Stop'
$CleanupRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$CleanupPrefix = $CleanupRoot.TrimEnd('\', '/') + [System.IO.Path]::DirectorySeparatorChar
$CleanupRelativePaths = @(
    'assets/downloads', '.tools/downloads', '.tools/wheels', 'output', 'tmp',
    'scripts/__pycache__', 'assets/metadata',
    'environment/installed-model-packages.txt',
    'environment/native-tools-manifest.json', 'environment/model-wheel-manifest.json'
)
$CleanupTargets = @()
foreach ($CleanupRelative in $CleanupRelativePaths) {
    $CleanupCandidate = Join-Path $CleanupRoot $CleanupRelative
    if (Test-Path -LiteralPath $CleanupCandidate) {
        $CleanupTargets += Get-Item -LiteralPath $CleanupCandidate -Force
    }
}
$CleanupSourceRoot = Join-Path $CleanupRoot 'assets/sources'
if (Test-Path -LiteralPath $CleanupSourceRoot) {
    $CleanupTargets += Get-ChildItem -LiteralPath $CleanupSourceRoot -Directory -Filter '__pycache__' -Recurse -Force
}
$CleanupFinderFile = Join-Path $CleanupRoot 'assets/datasets/speech_commands_v0.02/.DS_Store'
if (Test-Path -LiteralPath $CleanupFinderFile) {
    $CleanupTargets += Get-Item -LiteralPath $CleanupFinderFile -Force
}
$CleanupBytes = 0L
foreach ($CleanupItem in $CleanupTargets) {
    $CleanupResolved = (Resolve-Path -LiteralPath $CleanupItem.FullName).ProviderPath
    if (-not $CleanupResolved.StartsWith($CleanupPrefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to delete outside project: $CleanupResolved"
    }
    if ($CleanupItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint) {
        throw "Refusing to recursively delete a reparse point: $CleanupResolved"
    }
    if ($CleanupItem.PSIsContainer) {
        $CleanupLinks = @(Get-ChildItem -LiteralPath $CleanupResolved -Recurse -Force | Where-Object { $_.Attributes -band [System.IO.FileAttributes]::ReparsePoint })
        if ($CleanupLinks.Count) { throw "Refusing directory containing reparse points: $CleanupResolved" }
        $CleanupSize = (Get-ChildItem -LiteralPath $CleanupResolved -File -Recurse -Force | Measure-Object Length -Sum).Sum
    } else {
        $CleanupSize = $CleanupItem.Length
    }
    if ($PSCmdlet.ShouldProcess($CleanupResolved, 'Remove reproducible cache/output')) {
        Remove-Item -LiteralPath $CleanupResolved -Recurse -Force
        $CleanupBytes += [long]$CleanupSize
    }
}
Write-Output ("Removed {0:N0} bytes ({1:N2} GB). Installed environments, datasets and reference sources retained." -f $CleanupBytes, ($CleanupBytes / 1e9))
