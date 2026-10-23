param([switch]$Production, [switch]$NoBrowser, [int]$Port = 8765)
$ErrorActionPreference = 'Stop'
if ($Production) {
    Start-Process 'https://api.finfusion.asia/admin/'
    exit
}
$previewUrl = "http://127.0.0.1:$Port/admin/"
$healthUrl = "http://127.0.0.1:$Port/preview-health"
$expectedRoot = Join-Path (Split-Path $PSScriptRoot -Parent) 'server_admin'
$running = $false
try {
    $status = Invoke-RestMethod -Uri $healthUrl -TimeoutSec 2
    if ($status.application -ne 'finfusion-admin-readonly-preview' -or $status.root -ne $expectedRoot) {
        throw 'The preview port belongs to another application.'
    }
    $running = $true
} catch {
    if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) {
        throw "Port $Port is occupied. Use -Port with a free port."
    }
}
if (-not $running) {
    $pythonCandidates = @(
        (Join-Path (Split-Path $PSScriptRoot -Parent) '.venv\Scripts\python.exe'),
        (Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe')
    )
    $pythonPath = $pythonCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    if (-not $pythonPath) {
        $command = Get-Command python.exe -ErrorAction SilentlyContinue
        if ($command) { $pythonPath = $command.Source }
    }
    if (-not $pythonPath) { throw 'Python 3.11+ is required for the local preview.' }
    $serverPath = Join-Path $PSScriptRoot 'preview_server.py'
    $process = Start-Process -FilePath $pythonPath -ArgumentList @('"' + $serverPath + '"', '--port', "$Port") -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -PassThru
    $process.Id | Set-Content -LiteralPath (Join-Path $PSScriptRoot 'preview.pid') -Encoding Ascii
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        Start-Sleep -Milliseconds 200
        try {
            $status = Invoke-RestMethod -Uri $healthUrl -TimeoutSec 1
            if ($status.application -eq 'finfusion-admin-readonly-preview' -and $status.root -eq $expectedRoot) { $running = $true; break }
        } catch { }
        if ($process.HasExited) { break }
    }
    if (-not $running) { throw 'The preview did not start. Run preview_server.py in a terminal for diagnostics.' }
}
Write-Output "Read-only admin preview: $previewUrl"
if (-not $NoBrowser) { Start-Process $previewUrl }
