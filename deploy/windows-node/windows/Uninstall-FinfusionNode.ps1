#Requires -RunAsAdministrator
[CmdletBinding(SupportsShouldProcess, ConfirmImpact='High')]
param([switch]$KeepData)
$ErrorActionPreference = 'Stop'
if ($PSCmdlet.ShouldProcess('FinfusionNodeHost and FinfusionNode WSL distribution','Uninstall')) {
    sc.exe stop FinfusionNodeHost | Out-Null
    sc.exe delete FinfusionNodeHost | Out-Null
    if (-not $KeepData) {
        $installRoot = "$env:ProgramFiles\Finfusion Node"
        $dataRoot = "$env:ProgramData\Finfusion"
        $helper = Join-Path $installRoot 'Invoke-WslBootstrap.ps1'
        $result = Join-Path $dataRoot 'uninstall-result.json'
        $taskName = 'FinfusionNode-Uninstall'
        $arguments = "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$helper`" -UnregisterOnly -ResultPath `"$result`""
        $action = New-ScheduledTaskAction -Execute "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" -Argument $arguments
        $principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
        Register-ScheduledTask -TaskName $taskName -Action $action -Principal $principal -Force | Out-Null
        try {
            Start-ScheduledTask -TaskName $taskName
            $deadline = [DateTime]::UtcNow.AddMinutes(5)
            while (-not (Test-Path -LiteralPath $result)) {
                if ([DateTime]::UtcNow -gt $deadline) { throw 'WSL unregister timed out.' }
                Start-Sleep -Seconds 1
            }
            $taskResult = Get-Content -LiteralPath $result -Raw | ConvertFrom-Json
            if (-not $taskResult.success) { throw $taskResult.message }
        } finally { Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue }
    }
    $installRoot = "$env:ProgramFiles\Finfusion Node"
    $machinePath = [Environment]::GetEnvironmentVariable('Path','Machine')
    $remaining = ($machinePath -split ';' | Where-Object { $_ -and $_ -ne $installRoot }) -join ';'
    [Environment]::SetEnvironmentVariable('Path',$remaining,'Machine')
}
