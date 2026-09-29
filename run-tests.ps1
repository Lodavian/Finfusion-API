$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$python = Join-Path $projectRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'Run setup-dev.ps1 first.' }
Push-Location $projectRoot
try {
    $env:PYTHONPATH = ''
    $env:PYTHONNOUSERSITE = '1'
    New-Item -ItemType Directory -Force -Path (Join-Path $projectRoot 'runtime') | Out-Null
    $testTemp = Join-Path $projectRoot ('runtime/pytest-' + [guid]::NewGuid().ToString('N'))
    & $python -m pytest -q --basetemp $testTemp
    if ($LASTEXITCODE -ne 0) { throw 'Tests failed.' }
    & $python tools/verify_independence.py
    if ($LASTEXITCODE -ne 0) { throw 'Independence verification failed.' }
    & $python -m pip check
    if ($LASTEXITCODE -ne 0) { throw 'Dependency check failed.' }
} finally { Pop-Location }
