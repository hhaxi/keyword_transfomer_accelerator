# Dot-source this file: . .\env.ps1
$TransformerProjectRoot = $PSScriptRoot
$env:TRANSFORMER_ROOT = $TransformerProjectRoot
$env:VIRTUAL_ENV = Join-Path $TransformerProjectRoot '.venv-model'
$env:KWT_SOURCE = Join-Path $TransformerProjectRoot 'assets\sources\keyword-transformer-237e4097afd4f6851e0b82f0a8d65c2dfe8eae30'
$env:KWT_DATA_DIR = Join-Path $TransformerProjectRoot 'assets\datasets\speech_commands_v0.02'
$env:HBIRD_SDK_ROOT = Join-Path $TransformerProjectRoot 'assets\references\hbird-sdk-0e0e9083569721578c42f07a95b05a26c0760db6'
$env:COMPILE_PREFIX = 'riscv64-unknown-elf-'
$TransformerLocalConfig = Join-Path $TransformerProjectRoot 'environment\local-tools.json'
$TransformerExtraPaths = @()
if (Test-Path -LiteralPath $TransformerLocalConfig) {
    $TransformerToolConfig = Get-Content -LiteralPath $TransformerLocalConfig -Raw | ConvertFrom-Json
    foreach ($TransformerKey in @('iverilog_bin', 'modelsim_bin', 'gtkwave_bin')) {
        if ($TransformerToolConfig.$TransformerKey) {
            $TransformerExtraPaths += $TransformerToolConfig.$TransformerKey
        }
    }
}
$TransformerBinPaths = @(
    (Join-Path $TransformerProjectRoot '.venv-model\Scripts'),
    (Join-Path $TransformerProjectRoot '.tools\nuclei-gcc\gcc\bin'),
    (Join-Path $TransformerProjectRoot '.tools\build-tools\win32-buildtools-1.2\bin')
) + $TransformerExtraPaths
$TransformerExistingPaths = $env:PATH -split ';'
$env:PATH = (($TransformerBinPaths + $TransformerExistingPaths | Select-Object -Unique) -join ';')
$TransformerPythonPaths = @($env:KWT_SOURCE) + @($env:PYTHONPATH -split ';' | Where-Object { $_ })
$env:PYTHONPATH = (($TransformerPythonPaths | Select-Object -Unique) -join ';')
Write-Host 'Transformer project environment ready (current PowerShell session only).'
