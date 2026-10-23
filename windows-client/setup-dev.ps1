param([string]$PythonExecutable = 'python')
$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
try {
    Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
    $env:PYTHONNOUSERSITE = '1'
    & $PythonExecutable -c "import sys,struct;assert sys.version_info[:2]==(3,12) and struct.calcsize('P')==8,'Python 3.12 x64 required';import tkinter"
    if ($LASTEXITCODE -ne 0) { throw 'Need Python 3.12 x64 with Tkinter.' }
    if (-not (Test-Path -LiteralPath '.\.venv\Scripts\python.exe')) {
        & $PythonExecutable -m venv .venv
        if ($LASTEXITCODE -ne 0) { throw 'venv creation failed' }
    }
    & '.\.venv\Scripts\python.exe' -m pip install -r requirements-dev.lock
    if ($LASTEXITCODE -ne 0) { throw 'dependency installation failed' }
    & '.\.venv\Scripts\python.exe' -m pip check
    if ($LASTEXITCODE -ne 0) { throw 'dependency check failed' }
} finally { Pop-Location }
