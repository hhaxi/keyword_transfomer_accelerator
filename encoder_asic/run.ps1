param([ValidateSet('check','simulate','synth')][string]$Task='check',[string]$DcShell='dc_shell',[string]$ModelSimBin='')
$ErrorActionPreference='Stop'
if ($Task -eq 'synth') {
 & $DcShell -f (Join-Path $PSScriptRoot 'dc/run.tcl')
 if($LASTEXITCODE -ne 0){throw 'DC failed'}
} else {
 $taskPython=if($env:CODEX_PRIMARY_RUNTIME_PYTHON){$env:CODEX_PRIMARY_RUNTIME_PYTHON}else{'python'}
 $taskArgs=@((Join-Path $PSScriptRoot 'scripts/check.py'))
 if($Task -eq 'simulate'){$taskArgs+=@('--simulate','--modelsim-bin',$ModelSimBin)}
 & $taskPython @taskArgs
 if($LASTEXITCODE -ne 0){throw 'Encoder checks failed'}
}
