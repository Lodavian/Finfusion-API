$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
try {
    Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
    $env:PYTHONNOUSERSITE = '1'
    if (-not (Test-Path -LiteralPath '.\.venv\Scripts\python.exe')) { throw 'Run setup-dev.ps1 first.' }
    & '.\.venv\Scripts\python.exe' -m finfusion_client @args
    if ($LASTEXITCODE -ne 0) { throw "Client exited: $LASTEXITCODE" }
} finally { Pop-Location }
