#Requires -Version 5.1
#Requires -RunAsAdministrator
param([Parameter(Mandatory)][string]$Snapshot)
$ErrorActionPreference='Stop'
$taskRoot=[IO.Path]::GetFullPath((Join-Path $env:ProgramData 'Finfusion\Host'))
$taskPath=[IO.Path]::GetFullPath($Snapshot)
if (!$taskPath.StartsWith($taskRoot+'\',[StringComparison]::OrdinalIgnoreCase)) { throw 'Snapshot must be under ProgramData\Finfusion\Host.' }
$taskData=Get-Content -Raw -LiteralPath $taskPath | ConvertFrom-Json
foreach ($guid in @($taskData.originalPowerPlan,$taskData.newPowerPlan)) { if ($guid -notmatch '^[0-9a-fA-F-]{36}$') { throw 'Invalid power-plan snapshot.' } }
$taskAllowed=@('HKLM:\SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate','HKLM:\SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate\AU','HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager\Power','HKLM:\SYSTEM\CurrentControlSet\Services\W32Time\Parameters')
foreach ($value in $taskData.registry) { if ($value.path -notin $taskAllowed) { throw 'Unexpected registry target.' } }
& powercfg /setactive $taskData.originalPowerPlan
if ($LASTEXITCODE -ne 0) { throw 'Cannot restore original power plan.' }
foreach ($value in $taskData.registry) {
    if ($value.exists) { New-ItemProperty -Path $value.path -Name $value.name -PropertyType $value.kind -Value $value.value -Force | Out-Null }
    else { Remove-ItemProperty -LiteralPath $value.path -Name $value.name -ErrorAction SilentlyContinue }
}
$taskStartup=@{Auto='Automatic';Manual='Manual';Disabled='Disabled'}[$taskData.timeStartMode]
if (!$taskStartup) { throw 'Unknown service start mode.' }
Set-Service W32Time -StartupType $taskStartup
if ($taskData.timeState -eq 'Running') { Start-Service W32Time; & w32tm /config /update }
elseif ($taskData.timeState -eq 'Stopped') { Stop-Service W32Time }
& wevtutil sl 'Microsoft-Windows-TaskScheduler/Operational' "/e:$($taskData.taskHistoryEnabled.ToString().ToLowerInvariant())"
if ($LASTEXITCODE -ne 0) { throw 'Cannot restore task logging.' }
Write-Output 'Original plan/policies/service settings restored. Diagnostic power plan retained for inspection; no files or tasks deleted.'
