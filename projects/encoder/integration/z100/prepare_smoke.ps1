param(
    [string] $BoardArchive = 'E:\Z100 ZYNQ开发板资料盘（A盘）\4_Source_Code\2_Embedded_Vitis\XC7Z035.rar',
    [string] $VitisRoot = 'D:\AMDDesignTools\2026.1\Vitis',
    [string] $SevenZip = 'D:\Program Files\7-Zip\7z.exe',
    [string] $BuildDir = (Join-Path $PSScriptRoot '../../output/z100'),
    [switch] $Ethernet
)

$ErrorActionPreference = 'Stop'
$BuildDir = [IO.Path]::GetFullPath($BuildDir)
$vendor = Join-Path $BuildDir 'vendor'
New-Item -ItemType Directory -Path $vendor -Force | Out-Null
$sample = 'XC7Z035\1_hello_world\hello_world.srcs\sources_1\bd\system\system.bd'
& $SevenZip e -y "-o$vendor" $BoardArchive $sample
if ($LASTEXITCODE) { throw "7-Zip returned $LASTEXITCODE" }
& python (Join-Path $PSScriptRoot 'board_profile.py') (Join-Path $vendor 'system.bd') (Join-Path $vendor 'ps_profile.tcl')
if ($LASTEXITCODE) { throw "Board configuration extraction returned $LASTEXITCODE" }
$sdExample = 'XC7Z035\14_micro_sd_rw\micro_sd_rw.srcs\sources_1\bd\system\system.bd'
$sdFolder = Join-Path $vendor 'sd'
& $SevenZip e -y "-o$sdFolder" $BoardArchive $sdExample
if ($LASTEXITCODE) { throw "7-Zip returned $LASTEXITCODE" }
& python (Join-Path $PSScriptRoot 'board_profile.py') (Join-Path $sdFolder 'system.bd') (Join-Path $vendor 'ps_profile_sd.tcl')
if ($LASTEXITCODE) { throw "SD board configuration extraction returned $LASTEXITCODE" }

if ($Ethernet) {
    $example = 'XC7Z035\36_lwip_echo_server'
    $ethernetFolder = Join-Path $vendor 'ethernet'
    $ethernetSources = @("$example\lwip_echo_server.srcs\sources_1\bd\system\system.bd",
                         "$example\vitis\lwip_echo_server\src\*",
                         "$example\vitis\system_wrapper\export\system_wrapper\sw\system_wrapper\standalone_ps7_cortexa9_0\bspinclude\include\*",
                         "$example\vitis\system_wrapper\export\system_wrapper\sw\system_wrapper\standalone_ps7_cortexa9_0\bsplib\lib\*.a")
    & $SevenZip x -y "-o$ethernetFolder" $BoardArchive @ethernetSources
    if ($LASTEXITCODE) { throw "Ethernet example extraction returned $LASTEXITCODE" }
    $bd = Join-Path $ethernetFolder "$example\lwip_echo_server.srcs\sources_1\bd\system\system.bd"
    & python (Join-Path $PSScriptRoot 'board_profile.py') $bd (Join-Path $vendor 'ps_profile_ethernet.tcl')
    if ($LASTEXITCODE) { throw "Ethernet board configuration extraction returned $LASTEXITCODE" }
}

& (Join-Path $PSScriptRoot 'build_firmware.ps1') -VitisRoot $VitisRoot -BuildDir $BuildDir
