[CmdletBinding()]
param(
    [string]$OutputDirectory = 'build/windows-node-dev',
    [string]$DotNetSdkVersion = '8.0.415',
    [string]$InnoVersion = '7.1.0'
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$env:NUGET_PACKAGES = Join-Path $repo 'build/nuget'
$env:DOTNET_CLI_HOME = Join-Path $repo 'build/dotnet-home'
$output = [IO.Path]::GetFullPath((Join-Path $repo $OutputDirectory))
$buildRoot = [IO.Path]::GetFullPath((Join-Path $repo 'build'))
if (-not $output.StartsWith($buildRoot + [IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)) { throw 'OutputDirectory must stay below build.' }
$tools = Join-Path $buildRoot 'tool-cache'
$dotnetRoot = Join-Path $tools "dotnet-$DotNetSdkVersion"
$dotnetInstall = Join-Path $tools 'dotnet-install.ps1'
$innoRoot = Join-Path $tools "inno-$InnoVersion"
$innoInstaller = Join-Path $tools "innosetup-$InnoVersion-x64.exe"
if (Test-Path -LiteralPath $output) { Remove-Item -LiteralPath $output -Recurse -Force }
New-Item -ItemType Directory -Force -Path $tools,$output | Out-Null

if (-not (Test-Path -LiteralPath $dotnetInstall)) {
    Invoke-WebRequest -UseBasicParsing 'https://dot.net/v1/dotnet-install.ps1' -OutFile $dotnetInstall
}
if (-not (Test-Path -LiteralPath (Join-Path $dotnetRoot 'dotnet.exe'))) {
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $dotnetInstall -Version $DotNetSdkVersion -Architecture x64 -InstallDir $dotnetRoot -NoPath
    if ($LASTEXITCODE -ne 0) { throw '.NET SDK installation failed.' }
}
$dotnet = Join-Path $dotnetRoot 'dotnet.exe'
& $dotnet publish (Join-Path $repo 'deploy/windows-node/windows/Finfusion.NodeHost/Finfusion.NodeHost.csproj') -c Release -o (Join-Path $output 'host') --self-contained true
if ($LASTEXITCODE -ne 0) { throw 'Node host compilation failed.' }
& $dotnet publish (Join-Path $repo 'deploy/windows-node/windows/Finfusion.Control/Finfusion.Control.csproj') -c Release -o (Join-Path $output 'control') --self-contained true
if ($LASTEXITCODE -ne 0) { throw 'Control GUI compilation failed.' }
$artifacts = Join-Path $output 'artifacts'
New-Item -ItemType Directory -Force -Path $artifacts | Out-Null
Copy-Item -LiteralPath (Join-Path $output 'host/finfusion-node.exe') -Destination (Join-Path $artifacts 'FinfusionServer-NodeHost.exe') -Force
Copy-Item -LiteralPath (Join-Path $output 'control/FinfusionServer-Control.exe') -Destination $artifacts -Force
foreach ($name in @('Install-FinfusionNode.ps1','Uninstall-FinfusionNode.ps1','Invoke-WslBootstrap.ps1')) {
    Copy-Item -LiteralPath (Join-Path $repo "deploy/windows-node/windows/$name") -Destination $artifacts -Force
}
Copy-Item -LiteralPath (Join-Path $repo 'deploy/windows-node/config.example.json') -Destination $artifacts -Force

if (-not (Test-Path -LiteralPath $innoInstaller)) {
    $url = "https://github.com/jrsoftware/issrc/releases/download/is-7_1_0/innosetup-$InnoVersion-x64.exe"
    Invoke-WebRequest -UseBasicParsing $url -OutFile $innoInstaller
}
$signature = Get-AuthenticodeSignature -LiteralPath $innoInstaller
if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'Pyrsys B\.V\.') { throw 'Inno Setup installer signature validation failed.' }
$iscc = Join-Path $innoRoot 'ISCC.exe'
if (-not (Test-Path -LiteralPath $iscc)) {
    & $innoInstaller /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP- /CURRENTUSER "/DIR=$innoRoot"
    if ($LASTEXITCODE -ne 0) { throw 'Inno Setup tool installation failed.' }
}
$version = (Get-Content -LiteralPath (Join-Path $repo 'packaging/VERSION') -Raw).Trim()
& $iscc "/DArtifactsDir=$artifacts" "/DOutputDir=$output" "/DProductVersion=$version" (Join-Path $repo 'packaging/FinfusionServer.iss')
if ($LASTEXITCODE -ne 0) { throw 'Inno Setup compilation failed.' }

$products = @('FinfusionServer-Control.exe','FinfusionServer-NodeHost.exe','FinfusionServer-Setup-x64.exe')
$files = [ordered]@{}
foreach ($name in $products) {
    $path = if ($name -eq 'FinfusionServer-Setup-x64.exe') { Join-Path $output $name } else { Join-Path $artifacts $name }
    if (-not (Test-Path -LiteralPath $path)) { throw "Missing expected product: $name" }
    $files[$name] = [ordered]@{ path=$path; sha256=(Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant(); bytes=(Get-Item -LiteralPath $path).Length; authenticode=(Get-AuthenticodeSignature -LiteralPath $path).Status.ToString() }
}
$report = [ordered]@{
    schemaVersion=1; developmentBuild=$true; liveCapable=$false; generatedUtc=[DateTime]::UtcNow.ToString('o')
    dotnetSdkVersion=$DotNetSdkVersion; dotnetInstallScriptSha256=(Get-FileHash -LiteralPath $dotnetInstall -Algorithm SHA256).Hash.ToLowerInvariant()
    innoVersion=$InnoVersion; innoInstallerSha256=(Get-FileHash -LiteralPath $innoInstaller -Algorithm SHA256).Hash.ToLowerInvariant(); innoPublisher=$signature.SignerCertificate.Subject
    files=$files; missingReleaseInputs=@('reviewed Debian 12 rootfs + package manifest + hashes','Casdoor binary/version/hash','cloudflared binary/version/hash','Authenticode signing certificate')
}
$report | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath (Join-Path $output 'development-build-report.json') -Encoding utf8
Write-Host "Built: $($files['FinfusionServer-Control.exe'].path)"
Write-Host "Built: $($files['FinfusionServer-Setup-x64.exe'].path)"
