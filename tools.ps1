param(
    [ValidateSet('all','model','rtl','synth','sdk','lint','sta','versions')]
    [string]$Task = 'all'
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'env.ps1')
& (Join-Path $PSScriptRoot '.venv-model\Scripts\python.exe') (Join-Path $PSScriptRoot 'scripts\check_environment.py') $Task
if ($LASTEXITCODE -ne 0) { throw "Environment check failed: $Task (exit $LASTEXITCODE)" }
