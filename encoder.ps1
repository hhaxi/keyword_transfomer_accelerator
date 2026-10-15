param(
    [ValidateSet('export','calibrate','math','component','fourstate','faults','lint','compat','soc','profile','synth','netlist','compat-netlist','collect','package','all')]
    [string]$Task='all'
)
$ErrorActionPreference='Stop'
Set-Location $PSScriptRoot
. (Join-Path $PSScriptRoot 'env.ps1')
$EncoderPython=Join-Path $PSScriptRoot '.venv-model/Scripts/python.exe'
function Checked([string]$Program,[string[]]$Arguments) {
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Encoder command failed: $Program $Arguments" }
}
if ($Task -eq 'all') {
    foreach ($Step in @('calibrate','export','math','component','fourstate','faults','lint','compat','soc','profile','synth','netlist','compat-netlist','collect','package')) {
        & $PSCommandPath -Task $Step
    }
} elseif ($Task -eq 'export' -or $Task -eq 'calibrate') {
    $Split=if ($Task -eq 'calibrate') {'training'} else {'validation'}
    Checked $EncoderPython @('scripts/export_encoder.py','--split',$Split)
} elseif ($Task -eq 'collect' -or $Task -eq 'package') {
    Checked $EncoderPython @("scripts/${Task}_encoder.py")
} else {
    $RunArgs=@('scripts/run_encoder.py',$Task)
    if ($Task -eq 'netlist') {$RunArgs+=@('--tasks','1')}
    Checked $EncoderPython $RunArgs
}
