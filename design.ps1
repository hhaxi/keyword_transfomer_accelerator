param(
    [ValidateSet('calibrate','export','numeric','mac','fourstate','accel','soc','synth','synth-soc','all')]
    [string]$Task='all'
)
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'env.ps1')
$DesignPython=Join-Path $PSScriptRoot '.venv-model/Scripts/python.exe'
Push-Location $PSScriptRoot
try {
    if ($Task -in @('calibrate','all')) {
        & $DesignPython scripts/export_vectors.py --split training --samples 24 --output output/calibration
        if ($LASTEXITCODE) { throw 'Training-split calibration checks failed' }
    }
    if ($Task -in @('export','all')) {
        & $DesignPython scripts/export_vectors.py --samples 120
        if ($LASTEXITCODE) { throw 'Reference export failed' }
    }
    if ($Task -eq 'numeric') {
        & $DesignPython scripts/run_design.py numeric
        if ($LASTEXITCODE) { throw 'Numeric model checks failed' }
    }
    if ($Task -in @('mac','fourstate','accel','soc','synth','synth-soc','all')) {
        & $DesignPython scripts/run_design.py $Task
        if ($LASTEXITCODE) { throw 'Design checks failed' }
    }
} finally { Pop-Location }
