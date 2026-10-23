#Requires -Version 5.1
# Run on another Windows computer while the server stays at the sign-in screen.
param([ValidateRange(1,60)][int]$Samples=12,[ValidateRange(1,60)][int]$IntervalSeconds=10,
      [string]$Output=(Join-Path $PWD 'finfusion-public-boot-probe.json'))
$ErrorActionPreference='Stop'
$taskHasher=[Security.Cryptography.SHA256]::Create()
try { $taskHash=([BitConverter]::ToString($taskHasher.ComputeHash([Text.Encoding]::UTF8.GetBytes($env:COMPUTERNAME)))).Replace('-','').Substring(0,16) }
finally { $taskHasher.Dispose() }
$taskReport=[ordered]@{sourceHostHash=$taskHash;startedAt=(Get-Date).ToString('o');endpoint='https://api.finfusion.asia/livez';checks=@();mutations=0}
$taskOutputDirectory=Split-Path -Parent ([IO.Path]::GetFullPath($Output))
New-Item -ItemType Directory -Path $taskOutputDirectory -Force | Out-Null
for ($taskIndex=0;$taskIndex -lt $Samples;$taskIndex++) {
    $taskCheck=[ordered]@{at=(Get-Date).ToString('o');result='FAIL';status=0}
    try {
        $taskUri=$taskReport.endpoint+'?hostProbe='+[guid]::NewGuid().ToString('N')
        $taskResponse=Invoke-WebRequest $taskUri -UseBasicParsing -TimeoutSec 5 -MaximumRedirection 0 -UserAgent 'FinfusionServerHealth/1.0.0-rc1' -Headers @{'Cache-Control'='no-cache'}
        $taskBody=$taskResponse.Content|ConvertFrom-Json
        $taskCheck.status=[int]$taskResponse.StatusCode
        $taskCheck.cache=@($taskResponse.Headers['CF-Cache-Status']) -join ','
        if ($taskCheck.status -eq 200 -and $taskBody.ok -eq $true -and $taskCheck.cache -notmatch 'HIT|STALE|UPDATING|REVALIDATED') {$taskCheck.result='PASS'}
    } catch {$taskCheck.reason=$_.Exception.GetType().Name}
    $taskReport.checks+= $taskCheck
    $taskReport | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $Output -Encoding utf8
    if ($taskIndex+1 -lt $Samples) {Start-Sleep -Seconds $IntervalSeconds}
}
Write-Output "Public GET evidence: $Output. It proves pre-login availability only when run independently and correlated with a fresh server boot."
