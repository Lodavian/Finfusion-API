#Requires -RunAsAdministrator
param([string]$Iso=(Join-Path $PSScriptRoot '..\..\build\vm-media\Windows11-Enterprise-Evaluation-zh-cn-x64.iso'),[switch]$Start)
$ErrorActionPreference='Stop'
if (!(Get-Module -ListAvailable Hyper-V)) { throw 'Run enable-hyperv.ps1 in administrator PowerShell, then complete any required manual restart.' }
Import-Module Hyper-V
$taskIsoPath=[IO.Path]::GetFullPath($Iso)
if (!(Test-Path -LiteralPath $taskIsoPath -PathType Leaf) -or [IO.Path]::GetExtension($taskIsoPath) -ne '.iso') { throw 'Official Windows evaluation ISO is missing.' }
if ((Get-FileHash -LiteralPath $taskIsoPath -Algorithm SHA256).Hash -ne 'B37A06D5121EEE017826C0B133250BBD21BEC694C2D607C60EDD29090E667A84') { throw 'ISO does not match the Microsoft published zh-CN Enterprise Evaluation SHA256.' }
$taskProject=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$taskVmRoot=[IO.Path]::GetFullPath((Join-Path $taskProject 'build\vm-qa'))
if (!$taskVmRoot.StartsWith($taskProject+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)) { throw 'VM path is outside project build directory.' }
$taskName='Finfusion-Client-1.0-QA'
if (Get-VM -Name $taskName -ErrorAction SilentlyContinue) { throw 'QA VM already exists; preserve it and its evidence instead of overwriting.' }
$taskSwitch=Get-VMSwitch -Name 'Default Switch' -ErrorAction SilentlyContinue
if (!$taskSwitch) { throw 'Hyper-V Default Switch is unavailable; no host network settings were changed.' }
New-Item -ItemType Directory -Path $taskVmRoot -Force | Out-Null
$taskVhd=Join-Path $taskVmRoot 'Finfusion-QA.vhdx'
if (Test-Path -LiteralPath $taskVhd) { throw 'VM disk already exists; refusing overwrite.' }
New-VHD -Path $taskVhd -SizeBytes 64GB -Dynamic | Out-Null
New-VM -Name $taskName -Generation 2 -MemoryStartupBytes 4GB -VHDPath $taskVhd -Path $taskVmRoot -SwitchName $taskSwitch.Name | Out-Null
Set-VM -Name $taskName -ProcessorCount 2 -AutomaticStartAction Nothing -AutomaticStopAction ShutDown
Set-VMMemory -VMName $taskName -DynamicMemoryEnabled $false
Set-VMKeyProtector -VMName $taskName -NewLocalKeyProtector
Enable-VMTPM -VMName $taskName
Add-VMDvdDrive -VMName $taskName -Path $taskIsoPath
$taskDvd=Get-VMDvdDrive -VMName $taskName
Set-VMFirmware -VMName $taskName -EnableSecureBoot On -SecureBootTemplate MicrosoftWindows -FirstBootDevice $taskDvd
$taskInfo=[ordered]@{name=$taskName;ramGB=4;cpu=2;diskGB=64;iso=$taskIsoPath;hyperVGeneration=2;created=$true;started=$false;installation='PENDING';productionServerTouched=$false}
if ($Start) {
    $taskFreeMB=(Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory/1024
    if ($taskFreeMB -lt 4500) { $taskInfo | ConvertTo-Json | Set-Content (Join-Path $taskVmRoot 'vm-state.json'); throw "Only $([int]$taskFreeMB) MB RAM free. VM preserved but not started; require at least 4500 MB without stopping the server." }
    Start-VM -Name $taskName; $taskInfo.started=$true
}
$taskInfo | ConvertTo-Json | Set-Content (Join-Path $taskVmRoot 'vm-state.json') -Encoding utf8
Write-Output "QA VM created: $taskName. Install Windows only into its new virtual disk, then checkpoint the clean guest."
