# Recreate this project's added tools on this host; reuse existing HDL/WSL installations.
$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
try {
    & uv python install 3.8.20
    if ($LASTEXITCODE -ne 0) { throw 'Python installation failed' }
    if (-not (Test-Path '.venv-model\Scripts\python.exe')) {
        & uv venv --python 3.8.20 .venv-model
        if ($LASTEXITCODE -ne 0) { throw 'Virtual environment creation failed' }
    }
    # Download helpers use Python 3.13; model runtime remains Python 3.8.
    & uv run --no-project --python 3.13 scripts/fetch_model_wheel.py
    if ($LASTEXITCODE -ne 0) { throw 'TensorFlow wheel download failed' }
    & uv pip install --python .venv-model/Scripts/python.exe --link-mode copy --no-deps --offline .tools/wheels/tensorflow-2.4.0-cp38-cp38-win_amd64.whl
    if ($LASTEXITCODE -ne 0) { throw 'Local TensorFlow wheel installation failed' }
    & uv pip sync --python .venv-model/Scripts/python.exe --link-mode copy environment/requirements-model.lock.txt
    if ($LASTEXITCODE -ne 0) { throw 'Python dependency installation failed' }
    & uv run --no-project --python 3.13 scripts/install_native_toolchain.py
    if ($LASTEXITCODE -ne 0) { throw 'Nuclei toolchain installation failed' }
    & (Join-Path $PSScriptRoot 'tools.ps1') all
} finally {
    Pop-Location
}
