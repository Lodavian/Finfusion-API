#Requires -RunAsAdministrator
$ErrorActionPreference = 'Stop'
Write-Output 'This enables Hyper-V for a disposable QA VM. It does not change power, sleep, updates, WSL registration or server auto-start settings.'
Write-Output 'A Windows restart may be required. This script never restarts the computer.'
$taskResult = Enable-WindowsOptionalFeature -Online -FeatureName Microsoft-Hyper-V-All -All -NoRestart
$taskResult | Select-Object FeatureName,State,RestartNeeded
Write-Output 'If RestartNeeded is True, save work and arrange a manual restart before creating the VM.'
