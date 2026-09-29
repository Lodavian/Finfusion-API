$ErrorActionPreference = 'Stop'
$python = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    py -3.11 -m venv (Join-Path $PSScriptRoot '.venv')
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.11 is required.' }
}
$env:PIP_CACHE_DIR = Join-Path $PSScriptRoot 'build/pip-cache'
& $python -m pip install -r (Join-Path $PSScriptRoot 'requirements-dev.txt')
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
Write-Host 'Ready. Run run-tests.ps1. This does not start any trading service.'
