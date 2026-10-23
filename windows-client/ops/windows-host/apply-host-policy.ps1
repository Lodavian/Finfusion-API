#Requires -Version 5.1
#Requires -RunAsAdministrator
[CmdletBinding()]
param([ValidateRange(0,23)][int]$ActiveHoursStart=16,[ValidateRange(0,23)][int]$ActiveHoursEnd=10)
$ErrorActionPreference='Stop'
$taskHours=($ActiveHoursEnd-$ActiveHoursStart+24)%24
if ($taskHours -lt 1 -or $taskHours -gt 18) { throw 'Active hours must span 1..18 hours; 24-hour no-restart protection is not supported.' }
$taskCs=Get-CimInstance Win32_ComputerSystem
if ($taskCs.PartOfDomain) { throw 'Domain joined: use domain update/time policy instead of overwriting it.' }
$taskKeepalive=Get-ScheduledTask -TaskName 'FastOrder-WSL-KeepAlive' -ErrorAction SilentlyContinue
if (!$taskKeepalive -or !$taskKeepalive.Settings.Enabled -or $taskKeepalive.Principal.LogonType.ToString() -ne 'Password') {
    throw 'A working boot task for the Ubuntu owner is required; no host policies were changed.'
}
if ($taskKeepalive.State.ToString() -ne 'Running') {
    # This is executed by the human in administrator PowerShell, never by the agent.
    Start-ScheduledTask -TaskName $taskKeepalive.TaskName
    Start-Sleep -Seconds 5
    $taskKeepalive=Get-ScheduledTask -TaskName $taskKeepalive.TaskName
    if ($taskKeepalive.State.ToString() -ne 'Running') { throw 'WSL keepalive task failed to stay running. Check its credentials/action; no host policies were changed.' }
}
$taskReady=$null
# Verify the formal unit and socket owner inside this user's Ubuntu. Windows localhost
# forwarding or a connectivity-only proxy cannot establish that LIVE trading is OFF.
try {
    $taskProof=& "$env:SystemRoot\System32\wsl.exe" -d Ubuntu -u root --cd / --exec /usr/bin/python3 /opt/finfusion-ops/host_ready_guard.py
    if ($LASTEXITCODE -ne 0) { throw 'WSL guard could not execute.' }
    $taskReady=($taskProof | Out-String) | ConvertFrom-Json
} catch { throw 'Cannot read formal Ubuntu service state; no host settings were changed.' }
if (!$taskReady -or $taskReady.offConfirmed -isnot [bool] -or $taskReady.offConfirmed -ne $true) { throw 'Cannot confirm formal LIVE trading is OFF; stop before changing host time or policy.' }
$taskRoot=Join-Path $env:ProgramData 'Finfusion\Host'
New-Item -ItemType Directory -Path $taskRoot -Force | Out-Null
& icacls $taskRoot /inheritance:r /grant:r '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Cannot restrict rollback directory.' }
$taskRun=Join-Path $taskRoot (Get-Date -Format 'yyyyMMdd-HHmmss')
New-Item -ItemType Directory -Path $taskRun | Out-Null
$taskScheme=[regex]::Match((& powercfg /getactivescheme | Out-String),'[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}').Value
if (!$taskScheme) { throw 'Cannot resolve current power plan.' }
$taskService=Get-CimInstance Win32_Service -Filter "Name='W32Time'"
$taskTimePath='HKLM:\SYSTEM\CurrentControlSet\Services\W32Time\Parameters'
$taskHistory=Get-WinEvent -ListLog 'Microsoft-Windows-TaskScheduler/Operational'
$taskKeys=@(
    @{path='HKLM:\SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate';names=@('SetActiveHours','ActiveHoursStart','ActiveHoursEnd')},
    @{path='HKLM:\SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate\AU';names=@('NoAutoUpdate','AUOptions')},
    @{path='HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager\Power';names=@('HiberbootEnabled')},
    @{path=$taskTimePath;names=@('Type','NtpServer')})
$taskValues=@(foreach ($key in $taskKeys) { foreach ($name in $key.names) {
    $item=Get-Item -LiteralPath $key.path -ErrorAction SilentlyContinue
    $exists=$item -and $item.GetValueNames() -contains $name
    @{path=$key.path;name=$name;exists=[bool]$exists;value=if($exists){$item.GetValue($name)}else{$null};kind=if($exists){$item.GetValueKind($name).ToString()}else{$null}}
}})
$taskNewScheme=[guid]::NewGuid().ToString()
@{originalPowerPlan=$taskScheme;newPowerPlan=$taskNewScheme;registry=$taskValues;timeStartMode=$taskService.StartMode;
    timeState=$taskService.State;taskHistoryEnabled=$taskHistory.IsEnabled;capturedAt=(Get-Date).ToString('o')} |
    ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $taskRun 'rollback.json') -Encoding utf8
function Run-Native([string]$Program,[string[]]$Arguments) { & $Program @Arguments; if ($LASTEXITCODE -ne 0) { throw "$Program failed ($LASTEXITCODE)" } }
try {
    Run-Native -Program powercfg -Arguments @('/duplicatescheme',$taskScheme,$taskNewScheme)
    Run-Native -Program powercfg -Arguments @('/changename',$taskNewScheme,'Finfusion Server Host')
    foreach ($source in @('/setacvalueindex','/setdcvalueindex')) {
        foreach ($setting in @('STANDBYIDLE','HIBERNATEIDLE','HYBRIDSLEEP')) { Run-Native -Program powercfg -Arguments @($source,$taskNewScheme,'SUB_SLEEP',$setting,'0') }
        Run-Native -Program powercfg -Arguments @($source,$taskNewScheme,'SUB_DISK','DISKIDLE','0')
        # Preserve a real low-battery shutdown boundary; never configure "do nothing" at critical battery.
        Run-Native -Program powercfg -Arguments @($source,$taskNewScheme,'SUB_BATTERY','BATLEVELLOW','20')
        Run-Native -Program powercfg -Arguments @($source,$taskNewScheme,'SUB_BATTERY','BATLEVELCRIT','10')
        Run-Native -Program powercfg -Arguments @($source,$taskNewScheme,'SUB_BATTERY','BATACTIONCRIT','3')
    }
    Run-Native -Program powercfg -Arguments @('/setactive',$taskNewScheme)
    # Lid and power-button behavior is unchanged: keep lid open, do not use sleep while serving.
    foreach ($key in $taskKeys) { New-Item -Path $key.path -Force | Out-Null }
    $wu=$taskKeys[0].path; $au=$taskKeys[1].path
    New-ItemProperty $wu SetActiveHours -PropertyType DWord -Value 1 -Force | Out-Null
    New-ItemProperty $wu ActiveHoursStart -PropertyType DWord -Value $ActiveHoursStart -Force | Out-Null
    New-ItemProperty $wu ActiveHoursEnd -PropertyType DWord -Value $ActiveHoursEnd -Force | Out-Null
    New-ItemProperty $au NoAutoUpdate -PropertyType DWord -Value 0 -Force | Out-Null
    New-ItemProperty $au AUOptions -PropertyType DWord -Value 2 -Force | Out-Null
    New-ItemProperty $taskKeys[2].path HiberbootEnabled -PropertyType DWord -Value 0 -Force | Out-Null
    Set-Service W32Time -StartupType Automatic
    Start-Service W32Time
    Run-Native -Program w32tm -Arguments @('/config','/manualpeerlist:time.windows.com,0x8 time.cloudflare.com,0x8','/syncfromflags:manual','/update')
    Run-Native -Program w32tm -Arguments @('/resync','/rediscover')
    Run-Native -Program wevtutil -Arguments @('sl','Microsoft-Windows-TaskScheduler/Operational','/e:true')
    # Stage a reviewed runner on the system drive, without replacing the existing task or its credentials.
    $taskExisting=Get-ScheduledTask -TaskName 'FastOrder-WSL-KeepAlive' -ErrorAction SilentlyContinue
    if ($taskExisting) {
        $taskOwner=New-Object Security.Principal.NTAccount($taskExisting.Principal.UserId)
        $taskSid=$taskOwner.Translate([Security.Principal.SecurityIdentifier]).Value
        $taskStartup=Join-Path $taskRoot 'Startup'
        New-Item -ItemType Directory -Path $taskStartup -Force | Out-Null
        Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'keep-wsl-running.ps1') -Destination $taskStartup -Force
        Run-Native -Program icacls -Arguments @($taskStartup,'/grant',"*$($taskSid):(OI)(CI)RX")
        Get-FileHash -LiteralPath (Join-Path $taskStartup 'keep-wsl-running.ps1') | Select-Object Path,Hash |
            ConvertTo-Json | Set-Content (Join-Path $taskRun 'startup-script.json')
    }
    'APPLIED_PENDING_ACCEPTANCE' | Set-Content (Join-Path $taskRun 'result.txt')
} catch {
    'FAILED_PARTIAL_CHANGE_REQUIRES_ROLLBACK' | Set-Content (Join-Path $taskRun 'result.txt')
    Write-Warning "Stop. Settings may be partially applied. Roll back using: restore-host-policy.ps1 -Snapshot '$taskRun\rollback.json'"
    throw
}
Write-Output "Applied; no restart, service shutdown, trading enable or scheduled-task replacement performed. Snapshot: $taskRun\rollback.json"
Write-Output 'Keep lid open. Critical battery now shuts down at 10%; network/UPS and pre-login recovery still require drills.'
