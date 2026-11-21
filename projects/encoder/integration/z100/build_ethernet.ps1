param(
    [Parameter(Mandatory)][string] $VendorExample,
    [Parameter(Mandatory)][string] $ArmRuntime,
    [Parameter(Mandatory)][string] $Output,
    [ValidateRange(20000000,100000000)][int] $Frequency = 40000000,
    [ValidateRange(3,254)][int] $IpLast = 11,
    [string] $VitisRoot = 'D:\AMDDesignTools\2026.1\Vitis',
    [string] $LwipTcpSource,
    [switch] $DirectModel,
    [switch] $StreamHandoff,
    [switch] $Profile,
    [switch] $Contest
)
$ErrorActionPreference = 'Stop'
$example = (Resolve-Path -LiteralPath $VendorExample).Path
$runtime = (Resolve-Path -LiteralPath $ArmRuntime).Path
$outputFile = [IO.Path]::GetFullPath($Output)
$outputDir = Split-Path $outputFile -Parent
New-Item -ItemType Directory -Force -Path $outputDir | Out-Null
$bsp = Join-Path $example 'vitis/system_wrapper/export/system_wrapper/sw/system_wrapper/standalone_ps7_cortexa9_0'
$vendorSource = Join-Path $example 'vitis/lwip_echo_server/src'
$llvm = Join-Path $VitisRoot 'tps/llvm/7.0/win64/bin'
$defines = @('-DZ100_ARM_CACHE=1', "-DZ100_FCLK_HZ=$Frequency", "-DZ100_IP_LAST=$IpLast")
if ($DirectModel) { $defines += '-DZ100_DIRECT_MODEL=1' }
if ($StreamHandoff) {
    if (!$DirectModel) { throw 'StreamHandoff requires DirectModel' }
    $defines += '-DZ100_STREAM_HANDOFF=1'
}
if ($Profile) { $defines += '-DZ100_PROFILE=1' }
if ($Contest) {
    if ($DirectModel -or $StreamHandoff -or $Profile) {
        throw 'Contest uses the E203 shared SRAM loader and its mailbox statistics'
    }
    $defines += '-DZ100_CONTEST=1'
}
$sources = @((Join-Path $PSScriptRoot 'ethernet.c'), (Join-Path $PSScriptRoot 'kwt_infer.c'),
             (Join-Path $vendorSource 'platform_zynq.c'))
$compile = @('--target=arm-none-eabi', '-mcpu=cortex-a9', '-marm', '-mfpu=vfpv3', '-mfloat-abi=hard',
             '-ffreestanding', '-fno-unwind-tables', '-fshort-enums', '-O2', '-I', (Join-Path $bsp 'bspinclude/include'),
             '-I', $vendorSource, '-isystem', (Join-Path $runtime 'include/newlib'))
if ($LwipTcpSource) {
    $tcp = (Resolve-Path -LiteralPath $LwipTcpSource).Path
    $opts = Get-Content -LiteralPath (Join-Path $bsp 'bspinclude/include/lwipopts.h') -Raw
    $window = '(?m)^#define TCP_WND\s+\d+'
    if ([regex]::Matches($opts, $window).Count -ne 1) {
        throw 'Expected one TCP_WND in the vendor BSP'
    }
    $config = Join-Path $outputDir 'lwip-tcp-window'
    New-Item -ItemType Directory -Force $config | Out-Null
    [IO.File]::WriteAllText((Join-Path $config 'lwipopts.h'), ($opts -replace $window, '#define TCP_WND 32768'))
    # Strong TCP globals keep the linker from also extracting the BSP's TCP objects.
    $compile = @('-fno-common', '-I', $config) + $compile
    $sources += @('tcp.c', 'tcp_in.c', 'tcp_out.c') | ForEach-Object { Join-Path $tcp $_ }
}
$objects = foreach ($source in $sources) {
    $object = Join-Path $outputDir (([IO.Path]::GetFileNameWithoutExtension($outputFile)) + '-' +
        [IO.Path]::GetFileNameWithoutExtension($source) + '.o')
    & "$llvm/clang.exe" @compile @defines -c $source -o $object
    if ($LASTEXITCODE) { throw "Compilation failed: $source" }
    $object
}
$vendorLib = Join-Path $bsp 'bsplib/lib'
$newlib = Join-Path $runtime 'lib/arm-none-eabi/newlib/thumb/v7-a+fp/hard'
$gcc = Get-ChildItem -Path (Join-Path $runtime 'lib/gcc/arm-none-eabi') -Directory | Sort-Object Name | Select-Object -Last 1
$libs = @((Join-Path $vendorLib 'liblwip4.a'), (Join-Path $vendorLib 'libxil.a'),
          (Join-Path $newlib 'libm.a'), (Join-Path $newlib 'libc.a'), (Join-Path $newlib 'libnosys.a'),
          (Join-Path $gcc.FullName 'thumb/v7-a+fp/hard/libgcc.a'))
function Convert-ToWsl([string] $Path) {
    $converted = & wsl.exe -d Ubuntu -- wslpath -a ($Path.Replace('\','/'))
    if ($LASTEXITCODE -or !$converted) { throw "Cannot resolve $Path in Ubuntu WSL" }
    return $converted.Trim()
}
$linker = Convert-ToWsl (Join-Path $runtime 'bin/arm-none-eabi-ld')
$ldScript = Convert-ToWsl (Join-Path $vendorSource 'lscript.ld')
$wslObjects = @($objects | ForEach-Object { Convert-ToWsl $_ })
$wslLibs = @($libs | ForEach-Object { Convert-ToWsl $_ })
$wslOutput = Convert-ToWsl $outputFile
& wsl.exe -d Ubuntu -- $linker -T $ldScript -u _vector_table -u _sbrk -u _write @wslObjects --start-group @wslLibs --end-group -o $wslOutput
if ($LASTEXITCODE) { throw 'Ethernet firmware linking failed' }
Write-Output $outputFile
