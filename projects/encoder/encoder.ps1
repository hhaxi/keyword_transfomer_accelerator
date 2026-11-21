param(
    [ValidateSet('export','soc','all')]
    [string]$Task = 'all',
    [ValidateRange(1,12)]
    [int]$Jobs = 4
)

$ErrorActionPreference = 'Stop'
$EncoderPython = Join-Path $PSScriptRoot '.venv-model/Scripts/python.exe'
Push-Location $PSScriptRoot
try {
    . (Join-Path $PSScriptRoot 'env.ps1')

    if ($Task -in @('export','all')) {
        & $EncoderPython scripts/export_encoder.py --split validation --sample-list model/validation-samples.json --samples 12
        if ($LASTEXITCODE) { throw 'Frozen encoder vector export failed' }
    }

    if ($Task -in @('soc','all')) {
        & $EncoderPython scripts/run_encoder.py soc --contest --compact 1 --input-stream 1 --tasks 12 --jobs $Jobs
        if ($LASTEXITCODE) { throw 'Compact single-lane encoder regression failed' }
    }
} finally {
    Pop-Location
}
