param(
    [ValidateSet('export','calibrate','math','component','transfer','fourstate','faults','lint','compat','soc','transfer-profile','input-single','input-protocol','input-full','fifo-baseline','fifo-profile','profile','synth','netlist','compat-netlist','collect','package','all')]
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
    foreach ($Step in @('calibrate','export','math','component','transfer','fourstate','faults','lint','compat','soc','transfer-profile','input-single','input-protocol','input-full','fifo-baseline','fifo-profile','profile','synth','netlist','compat-netlist','collect','package')) {
        & $PSCommandPath -Task $Step
    }
} elseif ($Task -eq 'export' -or $Task -eq 'calibrate') {
    $Split=if ($Task -eq 'calibrate') {'training'} else {'validation'}
    Checked $EncoderPython @('scripts/export_encoder.py','--split',$Split)
} elseif ($Task -eq 'collect') {
    Checked $EncoderPython @('scripts/collect_input_study.py')
} elseif ($Task.StartsWith('input-')) {
    Checked $EncoderPython @('scripts/run_input_study.py',$Task.Substring(6))
} elseif ($Task -eq 'fifo-baseline') {
    Checked $EncoderPython @('scripts/run_fifo_study.py','baseline')
} elseif ($Task -eq 'fifo-profile') {
    Checked $EncoderPython @('scripts/run_fifo_study.py','candidate','--tasks','12','--jobs','4')
} elseif ($Task -eq 'package') {
    Checked $EncoderPython @("scripts/${Task}_encoder.py")
} else {
    $RunArgs=@('scripts/run_encoder.py',$Task)
    if ($Task -eq 'netlist') {$RunArgs+=@('--tasks','1')}
    Checked $EncoderPython $RunArgs
}
