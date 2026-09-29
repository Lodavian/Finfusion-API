#Requires -RunAsAdministrator
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$BundleDirectory,
    [string]$InstallRoot = "$env:ProgramFiles\Finfusion Node",
    [string]$DataRoot = "$env:ProgramData\Finfusion",
    [switch]$SkipWslImport,
    [switch]$AllowUnsignedDevelopment
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Assert-Hash([string]$Path, [string]$Expected) {
    $resolved = (Resolve-Path -LiteralPath $Path).Path
    $actual = (Get-FileHash -LiteralPath $resolved -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne $Expected.ToLowerInvariant()) { throw "SHA-256 mismatch: $resolved" }
}

$bundle = (Resolve-Path -LiteralPath $BundleDirectory).Path
$manifestPath = Join-Path $bundle 'bundle-manifest.json'
$manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
foreach ($file in $manifest.files.PSObject.Properties) {
    $candidate = Join-Path $bundle $file.Name
    Assert-Hash $candidate ([string]$file.Value.sha256)
}
$controller = Join-Path $bundle 'FinfusionServer-NodeHost.exe'
$signature = Get-AuthenticodeSignature -LiteralPath $controller
if (-not $AllowUnsignedDevelopment -and $signature.Status -ne 'Valid') {
    throw 'The Finfusion controller has no valid Authenticode signature. Use only -AllowUnsignedDevelopment in an isolated test environment.'
}
$restartRequired = $false
foreach ($featureName in @('Microsoft-Windows-Subsystem-Linux','VirtualMachinePlatform')) {
    $feature = Get-WindowsOptionalFeature -Online -FeatureName $featureName
    if ($feature.State -ne 'Enabled') {
        $result = Enable-WindowsOptionalFeature -Online -FeatureName $featureName -All -NoRestart
        if ($result.RestartNeeded -or (Get-WindowsOptionalFeature -Online -FeatureName $featureName).State -ne 'Enabled') {
            $restartRequired = $true
        }
    }
}
if ($restartRequired) {
    New-Item -ItemType Directory -Force -Path "$env:ProgramData\Finfusion" | Out-Null
    Set-Content -LiteralPath "$env:ProgramData\Finfusion\REBOOT-REQUIRED" -Value 'Reboot Windows, then rerun the signed Finfusion installer.' -Encoding ascii
    throw 'WSL2 Windows features were enabled or are pending. Reboot Windows and rerun the installer; no distribution was imported.'
}
wsl.exe --status | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'WSL is not ready. Install/update WSL, reboot if requested, then rerun.' }
Remove-Item -LiteralPath "$env:ProgramData\Finfusion\REBOOT-REQUIRED" -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $InstallRoot,$DataRoot | Out-Null
$distroRoot = Join-Path $DataRoot 'wsl'
Copy-Item -LiteralPath (Join-Path $bundle 'FinfusionServer-NodeHost.exe') -Destination (Join-Path $InstallRoot 'FinfusionServer-NodeHost.exe') -Force
Copy-Item -LiteralPath (Join-Path $bundle 'FinfusionServer-Control.exe') -Destination (Join-Path $InstallRoot 'FinfusionServer-Control.exe') -Force
Copy-Item -LiteralPath (Join-Path $bundle 'Invoke-WslBootstrap.ps1') -Destination (Join-Path $InstallRoot 'Invoke-WslBootstrap.ps1') -Force
$acl = New-Object System.Security.AccessControl.DirectorySecurity
$acl.SetAccessRuleProtection($true, $false)
$acl.AddAccessRule((New-Object System.Security.AccessControl.FileSystemAccessRule('SYSTEM','FullControl','ContainerInherit,ObjectInherit','None','Allow')))
$acl.AddAccessRule((New-Object System.Security.AccessControl.FileSystemAccessRule('BUILTIN\Administrators','FullControl','ContainerInherit,ObjectInherit','None','Allow')))
Set-Acl -LiteralPath $InstallRoot -AclObject $acl
Set-Acl -LiteralPath $DataRoot -AclObject $acl
$machinePath = [Environment]::GetEnvironmentVariable('Path','Machine')
if (($machinePath -split ';') -notcontains $InstallRoot) {
    [Environment]::SetEnvironmentVariable('Path', ($machinePath.TrimEnd(';') + ';' + $InstallRoot), 'Machine')
}

if (-not $SkipWslImport) {
    $staging = Join-Path $DataRoot 'install-staging'
    New-Item -ItemType Directory -Force -Path $staging | Out-Null
    $rootfs = Join-Path $staging 'debian-12-wsl-rootfs.tar.gz'
    $bootstrap = Join-Path $staging 'bootstrap.tar.gz'
    Copy-Item -LiteralPath (Join-Path $bundle 'debian-12-wsl-rootfs.tar.gz') -Destination $rootfs -Force
    Copy-Item -LiteralPath (Join-Path $bundle 'bootstrap.tar.gz') -Destination $bootstrap -Force
    Set-Acl -LiteralPath $staging -AclObject $acl
    $result = Join-Path $staging 'result.json'
    $helper = Join-Path $InstallRoot 'Invoke-WslBootstrap.ps1'
    $taskName = 'FinfusionNode-Install'
    $arguments = "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$helper`" -DistroRoot `"$distroRoot`" -Rootfs `"$rootfs`" -Bootstrap `"$bootstrap`" -ResultPath `"$result`""
    $action = New-ScheduledTaskAction -Execute "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" -Argument $arguments
    $principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
    Register-ScheduledTask -TaskName $taskName -Action $action -Principal $principal -Force | Out-Null
    try {
        Start-ScheduledTask -TaskName $taskName
        $deadline = [DateTime]::UtcNow.AddMinutes(20)
        while (-not (Test-Path -LiteralPath $result)) {
            if ([DateTime]::UtcNow -gt $deadline) { throw 'LocalSystem WSL bootstrap timed out.' }
            Start-Sleep -Seconds 2
        }
        $bootstrapResult = Get-Content -LiteralPath $result -Raw | ConvertFrom-Json
        if (-not $bootstrapResult.success) { throw "Linux bootstrap failed: $($bootstrapResult.message)" }
    } finally {
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
    }
}

$exe = Join-Path $InstallRoot 'FinfusionServer-NodeHost.exe'
if (Get-Service -Name FinfusionNodeHost -ErrorAction SilentlyContinue) { throw 'FinfusionNodeHost service already exists.' }
sc.exe create FinfusionNodeHost binPath= "`"$exe`" service" start= auto obj= LocalSystem | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Could not create FinfusionNodeHost service.' }
sc.exe failure FinfusionNodeHost reset= 86400 actions= restart/5000/restart/15000/none/0 | Out-Null
sc.exe description FinfusionNodeHost 'Finfusion WSL2 control host (LocalSystem)' | Out-Null
sc.exe start FinfusionNodeHost | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Could not start FinfusionNodeHost service.' }
Write-Host 'Installed. Trading remains OFF. Use FinfusionServer-Control.exe or FinfusionServer-NodeHost.exe.'
