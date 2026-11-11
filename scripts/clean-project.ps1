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

# Reproducible build output and candidate working copies. Local evidence that is
# SHA-256 pinned by tracked docs/*.json, the installed environments, downloaded
# datasets/reference sources and deliverables/ are intentionally preserved.
$CleanupPatterns = @(
    'output/design/build_*',
    'output/baseline-v1',
    'undergrad_ffn1/tmp',
    'undergrad_ffn1/candidates/*/study',
    'undergrad_ffn1/candidates/*/tmp'
)
foreach ($CleanupPattern in $CleanupPatterns) {
    $CleanupTargets += @(Get-ChildItem -Path (Join-Path $CleanupRoot $CleanupPattern) -Force -ErrorAction SilentlyContinue)
}

# Python bytecode caches outside installed environments.
$CleanupCodeRoots = @('scripts', 'tests', 'model', 'docs', 'environment', 'integration', 'rtl', 'firmware', 'constraints', 'undergrad_ffn1')
foreach ($CleanupCodeRoot in $CleanupCodeRoots) {
    $CleanupCodePath = Join-Path $CleanupRoot $CleanupCodeRoot
    if (Test-Path -LiteralPath $CleanupCodePath) {
        $CleanupTargets += @(Get-ChildItem -Path $CleanupCodePath -Directory -Recurse -Force -Filter '__pycache__' -ErrorAction SilentlyContinue)
    }
}

$CleanupTargets = @($CleanupTargets | Sort-Object -Property FullName -Unique)
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
Write-Output ("Removed {0:N0} bytes ({1:N2} GB). Installed environments, datasets, reference sources, pinned evidence and deliverables retained." -f $CleanupBytes, ($CleanupBytes / 1e9))
