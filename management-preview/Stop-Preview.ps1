$ErrorActionPreference = 'Stop'
$pidFile = Join-Path $PSScriptRoot 'preview.pid'
if (-not (Test-Path -LiteralPath $pidFile)) { Write-Output 'No saved preview process.'; exit }
$previewProcessId = [int](Get-Content -LiteralPath $pidFile)
$previewProcess = Get-CimInstance Win32_Process -Filter "ProcessId=$previewProcessId"
$expectedScript = Join-Path $PSScriptRoot 'preview_server.py'
if ($previewProcess -and $previewProcess.CommandLine.Contains($expectedScript)) {
    Stop-Process -Id $previewProcessId
    Write-Output 'Preview stopped.'
} else { Write-Output 'Saved process is absent or belongs to another application. No process stopped.' }
