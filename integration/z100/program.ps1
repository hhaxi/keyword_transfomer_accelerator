param(
    [ValidatePattern('^(smoke|kwt-([2-9][0-9]|100))$')] [string] $Image = 'smoke',
    [string] $Firmware,
    [ValidateSet('jtag','sd')] [string] $ModelSource = 'jtag',
    [string] $VivadoRoot = 'D:\AMDDesignTools\2026.1\Vivado',
    [string] $SevenZip = 'D:\Program Files\7-Zip\7z.exe',
    [string] $BuildDir = (Join-Path $PSScriptRoot '../../output/z100'),
    [string] $Xsdb
)

$ErrorActionPreference = 'Stop'
$BuildDir = [IO.Path]::GetFullPath($BuildDir)
$xsa = Join-Path $BuildDir "z100-$Image.xsa"
if (!$Firmware) { $Firmware = "z100-$Image" }
if (!$Xsdb) { $Xsdb = Join-Path $VivadoRoot 'bin/xsdb.bat' }
& $SevenZip e -y "-o$BuildDir\z100-$Image" $xsa ps7_init.tcl
if ($LASTEXITCODE) { throw "PS initialization extraction failed ($LASTEXITCODE)" }
if (!(Get-NetTCPConnection -LocalPort 3121 -State Listen -ErrorAction SilentlyContinue)) {
    Start-Process -FilePath (Join-Path $VivadoRoot 'bin/hw_server.bat') -ArgumentList '-s tcp::3121' -WorkingDirectory $BuildDir -WindowStyle Hidden
    Start-Sleep -Seconds 2
}
$oldBuild = $env:Z100_BUILD
try {
    $env:Z100_BUILD = $BuildDir
    $messages = & $Xsdb (Join-Path $PSScriptRoot 'boot_smoke.tcl') "z100-$Image" $Firmware $ModelSource 2>&1
    $messages | Write-Output
    if ($LASTEXITCODE -or $messages -notcontains 'Cortex-A9 started') { throw 'XSDB did not start the firmware' }
}
finally {
    $env:Z100_BUILD = $oldBuild
}
