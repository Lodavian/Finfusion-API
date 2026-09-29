# Invoked only by the installer as LocalSystem through a one-shot scheduled task.
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$ResultPath,
    [string]$DistroRoot,
    [string]$Rootfs,
    [string]$Bootstrap,
    [switch]$UnregisterOnly
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$imported = $false
try {
    if ([Security.Principal.WindowsIdentity]::GetCurrent().User.Value -ne 'S-1-5-18') { throw 'Bootstrap must run as LocalSystem.' }
    if ($UnregisterOnly) {
        wsl.exe --unregister FinfusionNode
    } else {
        foreach ($path in @($DistroRoot,$Rootfs,$Bootstrap)) { if (-not $path) { throw 'Missing bootstrap path.' } }
        if ((wsl.exe --list --quiet) -contains 'FinfusionNode') { throw 'FinfusionNode WSL distribution already exists for LocalSystem.' }
        New-Item -ItemType Directory -Force -Path $DistroRoot | Out-Null
        wsl.exe --import FinfusionNode $DistroRoot $Rootfs --version 2
        if ($LASTEXITCODE -ne 0) { throw 'WSL import failed.' }
        $imported = $true
        wsl.exe -d FinfusionNode -u root -- mkdir -p /mnt/finfusion-bootstrap
        $wslBootstrap = (wsl.exe -d FinfusionNode -u root -- wslpath -a $Bootstrap).Trim()
        if (-not $wslBootstrap) { throw 'Could not map bootstrap path.' }
        wsl.exe -d FinfusionNode -u root -- tar -xzf $wslBootstrap -C /mnt/finfusion-bootstrap
        wsl.exe -d FinfusionNode -u root -- bash /mnt/finfusion-bootstrap/install.sh
        if ($LASTEXITCODE -ne 0) { throw 'Linux bootstrap failed.' }
        wsl.exe --terminate FinfusionNode
    }
    @{ success=$true; message='ok' } | ConvertTo-Json | Set-Content -LiteralPath $ResultPath -Encoding utf8
} catch {
    if ($imported) { wsl.exe --unregister FinfusionNode | Out-Null }
    @{ success=$false; message=$_.Exception.Message } | ConvertTo-Json | Set-Content -LiteralPath $ResultPath -Encoding utf8
    exit 1
}
