#Requires -Version 5.1
# Prepared replacement, NOT installed or substituted for the current startup task.
param([ValidatePattern('^[A-Za-z0-9_.-]+$')][string]$Distro='Ubuntu')
$ErrorActionPreference='Stop'
$taskRoot=Join-Path $env:LOCALAPPDATA 'Finfusion\Host'
New-Item -ItemType Directory -Path $taskRoot -Force | Out-Null
$taskInfo=New-Object Diagnostics.ProcessStartInfo
$taskInfo.FileName=Join-Path $env:SystemRoot 'System32\wsl.exe'
$taskInfo.Arguments="--distribution $Distro --exec /bin/sleep infinity"
$taskInfo.UseShellExecute=$false; $taskInfo.CreateNoWindow=$true
$taskFailures=0
while ($true) {
    $taskChild=[Diagnostics.Process]::Start($taskInfo)
    while (!$taskChild.WaitForExit(30000)) {
        $taskTime=Get-Service W32Time
        @{at=(Get-Date).ToString('o');windowsBoot=(Get-CimInstance Win32_OperatingSystem).LastBootUpTime.ToString('o');
          keepalivePid=$taskChild.Id;w32time=$taskTime.Status.ToString();tradingActivated=$false;scope='HOST_KEEPALIVE_ONLY'} |
            ConvertTo-Json | Set-Content (Join-Path $taskRoot 'keepalive.json') -Encoding utf8
        $taskFailures=0
    }
    $taskFailures++
    @{at=(Get-Date).ToString('o');wslExitCode=$taskChild.ExitCode;failures=$taskFailures;scope='HOST_KEEPALIVE_ONLY'} |
        ConvertTo-Json | Set-Content (Join-Path $taskRoot 'keepalive.json') -Encoding utf8
    $taskChild.Dispose()
    # No global wsl shutdown/terminate, no restart of production components and no order replay.
    Start-Sleep -Seconds ([math]::Min(60,5*$taskFailures))
}
