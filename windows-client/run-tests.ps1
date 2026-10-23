$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
try {
    Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
    $env:PYTHONNOUSERSITE = '1'
    & '.\.venv\Scripts\python.exe' -m pytest --junitxml=build/test-results.xml @args
    if ($LASTEXITCODE -ne 0) { throw 'Tests failed.' }
    & '.\.venv\Scripts\python.exe' tools\verify_independence.py
    if ($LASTEXITCODE -ne 0) { throw 'Independence check failed.' }
} finally { Pop-Location }
