# Deletes only reproducible local caches/output. Keeps evidence, data, sources and installed tools.
[CmdletBinding(SupportsShouldProcess)]
param()
$ErrorActionPreference = 'Stop'
$CleanupRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$CleanupPrefix = $CleanupRoot.TrimEnd('\', '/') + [System.IO.Path]::DirectorySeparatorChar
$CleanupTargets = @()

# Caches and manifests that are always regenerable.
$CleanupRelativePaths = @(
    'assets/downloads', '.tools/downloads', '.tools/wheels', 'tmp',
    'assets/metadata',
    'environment/installed-model-packages.txt',
    'environment/native-tools-manifest.json', 'environment/model-wheel-manifest.json'
)
foreach ($CleanupRelative in $CleanupRelativePaths) {
    $CleanupCandidate = Join-Path $CleanupRoot $CleanupRelative
    if (Test-Path -LiteralPath $CleanupCandidate) {
        $CleanupTargets += Get-Item -LiteralPath $CleanupCandidate -Force
    }
}

# Only rebuildable simulator work directories. Preserve output evidence, inputs,
# the installed environments and local deliverables.
$CleanupPatterns = @(
    'output/design/build_*'
)
foreach ($CleanupPattern in $CleanupPatterns) {
    $CleanupTargets += @(Get-ChildItem -Path (Join-Path $CleanupRoot $CleanupPattern) -Force -ErrorAction SilentlyContinue)
}

# Python bytecode caches outside installed environments.
$CleanupCodeRoots = @('scripts', 'tests', 'model', 'environment', 'integration', 'rtl', 'firmware', 'constraints')
foreach ($CleanupCodeRoot in $CleanupCodeRoots) {
    $CleanupCodePath = Join-Path $CleanupRoot $CleanupCodeRoot
    if (Test-Path -LiteralPath $CleanupCodePath) {
        $CleanupTargets += @(Get-ChildItem -Path $CleanupCodePath -Directory -Recurse -Force -Filter '__pycache__' -ErrorAction SilentlyContinue)
    }
}

$CleanupTargets = @($CleanupTargets | Sort-Object -Property FullName -Unique)
# Keep only top-most targets so deleting a parent never leaves nested targets to process.
$CleanupTopTargets = @()
foreach ($CleanupCandidate in @($CleanupTargets | Sort-Object -Property { $_.FullName.Length })) {
    $CleanupCandidatePath = [System.IO.Path]::GetFullPath($CleanupCandidate.FullName)
    $CleanupIsNested = $false
    foreach ($CleanupKept in $CleanupTopTargets) {
        if ($CleanupCandidatePath.StartsWith($CleanupKept + [System.IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
            $CleanupIsNested = $true
            break
        }
    }
    if (-not $CleanupIsNested) { $CleanupTopTargets += $CleanupCandidatePath }
}
$CleanupBytes = 0L
foreach ($CleanupItem in $CleanupTopTargets) {
    if (-not (Test-Path -LiteralPath $CleanupItem)) { continue }
    $CleanupResolved = (Resolve-Path -LiteralPath $CleanupItem).ProviderPath
    if (-not $CleanupResolved.StartsWith($CleanupPrefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to delete outside project: $CleanupResolved"
    }
    $CleanupItemInfo = Get-Item -LiteralPath $CleanupResolved -Force
    if ($CleanupItemInfo.Attributes -band [System.IO.FileAttributes]::ReparsePoint) {
        throw "Refusing to recursively delete a reparse point: $CleanupResolved"
    }
    if ($CleanupItemInfo.PSIsContainer) {
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
Write-Output ("Removed {0:N0} bytes ({1:N2} GB). Installed environments, datasets, reference sources, pinned evidence and deliverables retained." -f $CleanupBytes, ($CleanupBytes / 1e9))
