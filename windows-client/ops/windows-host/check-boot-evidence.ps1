#Requires -Version 5.1
#Requires -RunAsAdministrator
# Read Windows logs AFTER a controlled restart. Does not launch WSL or restart services.
param([string]$Output=(Join-Path $PSScriptRoot '..\..\build\host-acceptance\boot.json'))
$ErrorActionPreference='Stop'
$taskBoot=(Get-CimInstance Win32_OperatingSystem).LastBootUpTime
$taskOwner=Get-ScheduledTask -TaskName 'FastOrder-WSL-KeepAlive'
$taskAccount=New-Object Security.Principal.NTAccount($taskOwner.Principal.UserId)
$taskSid=$taskAccount.Translate([Security.Principal.SecurityIdentifier]).Value
function Event-Fields($Event) {
    $xml=[xml]$Event.ToXml(); $data=@{}
    foreach ($node in $xml.Event.EventData.Data) { $data[$node.Name]=$node.'#text' }
    return $data
}
$taskLogons=@(Get-WinEvent -FilterHashtable @{LogName='Security';Id=4624;StartTime=$taskBoot} -ErrorAction SilentlyContinue | ForEach-Object {
    $data=Event-Fields $_
    if ($data.TargetUserSid -eq $taskSid -and $data.LogonType -in @('2','10')) { $_.TimeCreated }
} | Sort-Object)
$taskStarts=@(Get-WinEvent -FilterHashtable @{LogName='Microsoft-Windows-TaskScheduler/Operational';Id=100,200;StartTime=$taskBoot} -ErrorAction SilentlyContinue | ForEach-Object {
    $data=Event-Fields $_
    if ($data.TaskName -eq '\FastOrder-WSL-KeepAlive') { $_.TimeCreated }
} | Sort-Object)
$taskBefore=$taskStarts.Count -gt 0 -and $taskLogons.Count -gt 0 -and $taskStarts[0] -lt $taskLogons[0]
$taskResult=[ordered]@{boot=$taskBoot.ToString('o');firstTaskStart=if($taskStarts.Count){$taskStarts[0].ToString('o')}else{$null};
    firstOwnerInteractiveLogon=if($taskLogons.Count){$taskLogons[0].ToString('o')}else{$null};
    taskStartedBeforeOwnerLogin=if($taskBefore){'OBSERVED'}else{'UNVERIFIED'};
    publicApiBeforeLogin='REQUIRES_INDEPENDENT_EXTERNAL_EVIDENCE';wholeAcceptance='NOT_PASSED';
    distributionStartedByThisTool=$false;productionWrites=0}
$taskDir=Split-Path -Parent ([IO.Path]::GetFullPath($Output)); New-Item -ItemType Directory -Path $taskDir -Force | Out-Null
$taskResult | ConvertTo-Json | Set-Content -LiteralPath $Output -Encoding utf8
Write-Output 'Task log evidence only. Correlate independent public API probes and WSL boot/service logs; task invocation alone is not service recovery.'
