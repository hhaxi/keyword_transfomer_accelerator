param(
    [ValidateSet('smoke', 'kwt-25', 'kwt-20')] [string] $Image = 'smoke',
    [ValidateSet(115200, 921600)] [int] $Baud = 115200,
    [string] $VitisRoot = 'D:\AMDDesignTools\2026.1\Vitis',
    [string] $BuildDir = (Join-Path $PSScriptRoot '../../output/z100'),
    [string] $FatFsInclude,
    [string[]] $BspLibraries,
    [switch] $JtagVerify
)

$ErrorActionPreference = 'Stop'
$BuildDir = [IO.Path]::GetFullPath($BuildDir)
New-Item -ItemType Directory -Path $BuildDir -Force | Out-Null
$llvm = Join-Path $VitisRoot 'tps/llvm/7.0/win64/bin'
$clang = Join-Path $llvm 'clang.exe'
$linker = Join-Path $llvm 'ld.lld.exe'
$sources = @('start.S', 'smoke.c')
$defines = @("-DZ100_BAUD=$Baud")
$suffix = $Image
if ($Image -ne 'smoke') {
    $sources += 'kwt_infer.c'
    $frequency = [int]($Image.Substring(4)) * 1000000
    $defines += '-DZ100_KWT=1', "-DZ100_FCLK_HZ=$frequency"
}
if ($JtagVerify) {
    if ($Image -eq 'smoke') { throw 'JTAG inference needs a KWT image' }
    $sources = @('start.S', 'jtag_verify.c', 'kwt_infer.c')
    $suffix += '-jtag'
}
if ($FatFsInclude) {
    if ($Image -eq 'smoke' -or !$BspLibraries) { throw 'FatFs needs a KWT image and BSP libraries' }
    $defines += '-DZ100_USE_FATFS=1', "-I$FatFsInclude"
    $suffix += '-sd'
}
if ($Baud -ne 115200) { $suffix += "-$Baud" }
$objects = foreach ($source in $sources) {
    $object = Join-Path $BuildDir ("$suffix-" + [IO.Path]::GetFileNameWithoutExtension($source) + '.o')
    & $clang --target=arm-none-eabi -mcpu=cortex-a9 -marm -mfpu=vfpv3 -mfloat-abi=softfp -ffreestanding -fno-unwind-tables -Os -Wall -Wextra -Werror @defines -c (Join-Path $PSScriptRoot $source) -o $object
    if ($LASTEXITCODE) { throw "Cortex-A9 compilation failed for $source" }
    $object
}
$elf = Join-Path $BuildDir "z100-$suffix.elf"
& $linker -T (Join-Path $PSScriptRoot 'arm.ld') @objects --start-group @BspLibraries --end-group -o $elf
if ($LASTEXITCODE) { throw 'Cortex-A9 linking failed' }
Write-Output $elf
