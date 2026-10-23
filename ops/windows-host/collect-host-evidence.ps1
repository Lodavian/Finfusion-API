#Requires -Version 5.1
[CmdletBinding()]
param([string]$OutputDirectory=(Join-Path $PSScriptRoot '..\..\build\host-acceptance'),
      [string]$Python=(Join-Path $PSScriptRoot '..\..\.venv\Scripts\python.exe'),[switch]$SkipClockProbe)
$ErrorActionPreference='Stop'
$taskOut=[IO.Path]::GetFullPath($OutputDirectory)
New-Item -ItemType Directory -Path $taskOut -Force | Out-Null
function Get-PowerValue([string]$Subgroup,[string]$Setting) {
    $raw=(& powercfg /query SCHEME_CURRENT $Subgroup $Setting 2>&1 | Out-String)
    $exit=$LASTEXITCODE
    $hex=[regex]::Matches($raw,'0x[0-9a-fA-F]+')
    if ($exit -ne 0 -or $hex.Count -lt 2) { return @{status='UNAVAILABLE'} }
    return @{ac=[Convert]::ToInt64($hex[$hex.Count-2].Value.Substring(2),16);dc=[Convert]::ToInt64($hex[$hex.Count-1].Value.Substring(2),16)}
}
$taskOs=Get-CimInstance Win32_OperatingSystem
$taskCs=Get-CimInstance Win32_ComputerSystem
$taskTasks=@(Get-ScheduledTask | Where-Object {$_.TaskName -match 'Finfusion|FastOrder-WSL'} | ForEach-Object {
    $info=Get-ScheduledTaskInfo -TaskName $_.TaskName -TaskPath $_.TaskPath
    [ordered]@{name=$_.TaskName;state=$_.State.ToString();user=$_.Principal.UserId;logonType=$_.Principal.LogonType.ToString();
        triggers=@($_.Triggers|ForEach-Object {$_.CimClass.CimClassName});lastRun=$info.LastRunTime.ToString('o');lastResult=$info.LastTaskResult;
        batteryStop=$_.Settings.StopIfGoingOnBatteries;executionLimit=$_.Settings.ExecutionTimeLimit}
})
$taskPolicy='HKLM:\SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate'
$taskTime=Get-Service W32Time
$taskEvents=@(Get-WinEvent -FilterHashtable @{LogName='System';Id=41,6008,42,107,1074,6005,6006;StartTime=(Get-Date).AddDays(-7)} -MaxEvents 60 -ErrorAction SilentlyContinue | ForEach-Object {
    @{at=$_.TimeCreated.ToString('o');id=$_.Id;provider=$_.ProviderName}
})
$taskRegistryTime=Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Services\W32Time\Parameters'
$taskReport=[ordered]@{capturedAt=(Get-Date).ToString('o');computer=$taskCs.Model;os=$taskOs.Caption;version=$taskOs.Version;
    boot=$taskOs.LastBootUpTime.ToString('o');timeZone=(Get-TimeZone).Id;memoryFreeMB=[int]($taskOs.FreePhysicalMemory/1024);
    power=@{sleep=(Get-PowerValue SUB_SLEEP STANDBYIDLE);hibernate=(Get-PowerValue SUB_SLEEP HIBERNATEIDLE);
        hybrid=(Get-PowerValue SUB_SLEEP HYBRIDSLEEP);disk=(Get-PowerValue SUB_DISK DISKIDLE);
        criticalBatteryAction=(Get-PowerValue SUB_BATTERY BATACTIONCRIT);criticalBatteryPercent=(Get-PowerValue SUB_BATTERY BATLEVELCRIT)};
    battery=@(Get-CimInstance Win32_Battery | Select-Object BatteryStatus,EstimatedChargeRemaining);
    w32time=@{status=$taskTime.Status.ToString();startType=$taskTime.StartType.ToString();type=$taskRegistryTime.Type;peers=$taskRegistryTime.NtpServer};
    update=@{policy=(Get-ItemProperty $taskPolicy -ErrorAction SilentlyContinue | Select-Object SetActiveHours,ActiveHoursStart,ActiveHoursEnd);
        automatic=(Get-ItemProperty "$taskPolicy\AU" -ErrorAction SilentlyContinue | Select-Object NoAutoUpdate,AUOptions);
        effectiveUX=(Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\WindowsUpdate\UX\Settings' -ErrorAction SilentlyContinue | Select-Object ActiveHoursStart,ActiveHoursEnd);
        rebootPending=(Test-Path 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\RebootRequired');
        patches=@(Get-HotFix|Sort-Object InstalledOn -Descending|Select-Object -First 3 HotFixID,InstalledOn)};
    tasks=$taskTasks;taskHistoryEnabled=(Get-WinEvent -ListLog 'Microsoft-Windows-TaskScheduler/Operational').IsEnabled;
    events=$taskEvents;hardwarePowerReturn='NOT_VERIFIED';networkUps='NOT_VERIFIED';preLoginRecovery='NOT_TESTED';
    outageDrill='NOT_TESTED';windowsPolicyModified=$false;orders=0}
$taskReport | ConvertTo-Json -Depth 7 | Set-Content -LiteralPath (Join-Path $taskOut 'host.json') -Encoding utf8
if (!$SkipClockProbe) {
    if (!(Test-Path -LiteralPath $Python)) { throw 'Python runtime not found. Use -Python or -SkipClockProbe; no clock result was invented.' }
    & $Python (Join-Path $PSScriptRoot 'clock_probe.py') --output (Join-Path $taskOut 'clock.json')
    if ($LASTEXITCODE -ne 0) { throw 'Clock diagnostic failed.' }
}
Write-Output "Read-only evidence: $taskOut"
