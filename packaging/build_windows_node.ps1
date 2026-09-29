[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$DebianRootfs,
    [Parameter(Mandatory)][string]$DebianRootfsSha256,
    [Parameter(Mandatory)][string]$DebianBaseManifest,
    [Parameter(Mandatory)][string]$DebianBaseManifestSha256,
    [Parameter(Mandatory)][string]$CasdoorArchive,
    [string]$CasdoorVersion = '3.143.0',
    [string]$CasdoorSha256 = '76ab880fdc9a7630dc081ac49aaddb07db0ff4da73a8e663e2a72df76db65f24',
    [Parameter(Mandatory)][string]$CloudflaredBinary,
    [string]$CloudflaredVersion = '2026.9.1',
    [string]$CloudflaredSha256 = '03f1f25d1cc93b9ad6c60569d44060bc4f17ed97075760ed8cfca4b12dcd68cc',
    [Parameter(Mandatory)][string]$PahoMqttSdist,
    [string]$PahoMqttSdistSha256 = '2a8291c81623aec00372b5a85558a372c747cbca8e9934dfe218638b8eefc26f',
    [string]$SignTool,
    [string]$SigningCertificateThumbprint,
    [string]$TimestampUrl,
    [string]$OutputDirectory = 'build/windows-node',
    [string]$DotNetExe = 'dotnet',
    [string]$PythonExe = 'python',
    [string]$InnoCompiler = 'ISCC.exe',
    [switch]$SkipWheelDownload,
    [switch]$InternalUnsigned
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$env:NUGET_PACKAGES = Join-Path $repo 'build/nuget'
$env:DOTNET_CLI_HOME = Join-Path $repo 'build/dotnet-home'
$output = [IO.Path]::GetFullPath((Join-Path $repo $OutputDirectory))
$stage = Join-Path $output 'stage'
$bundle = Join-Path $output 'FinfusionNode-online'
$buildRoot = [IO.Path]::GetFullPath((Join-Path $repo 'build'))
if (-not $output.StartsWith($buildRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) { throw 'OutputDirectory must stay below the repository build directory.' }

function Assert-Hash([string]$Path,[string]$Expected) {
    $resolvedInput = [IO.Path]::GetFullPath($Path)
    if (-not $resolvedInput.StartsWith($repo.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Release inputs must be copied into this project first.' }
    $actual = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($Expected -notmatch '^[a-fA-F0-9]{64}$' -or $actual -ne $Expected.ToLowerInvariant()) { throw "Invalid SHA-256 for $Path" }
}
Assert-Hash $DebianRootfs $DebianRootfsSha256
Assert-Hash $DebianBaseManifest $DebianBaseManifestSha256
if ($CasdoorVersion -ne '3.143.0' -or $CasdoorSha256.ToLowerInvariant() -ne '76ab880fdc9a7630dc081ac49aaddb07db0ff4da73a8e663e2a72df76db65f24') { throw 'This release requires the reviewed Casdoor 3.143.0 archive and official SHA-256.' }
if ($CloudflaredVersion -ne '2026.9.1' -or $CloudflaredSha256.ToLowerInvariant() -ne '03f1f25d1cc93b9ad6c60569d44060bc4f17ed97075760ed8cfca4b12dcd68cc') { throw 'This release requires reviewed cloudflared 2026.9.1 amd64 and its locked SHA-256.' }
Assert-Hash $CasdoorArchive $CasdoorSha256
Assert-Hash $CloudflaredBinary $CloudflaredSha256
Assert-Hash $PahoMqttSdist $PahoMqttSdistSha256
$signToolPath = $null
if (-not $InternalUnsigned) {
    if (-not $SignTool) { throw 'SignTool is required for a release build.' }
    if ($SigningCertificateThumbprint -notmatch '^[a-fA-F0-9]{40}$') { throw 'SigningCertificateThumbprint must be a SHA-1 certificate thumbprint.' }
    if ($TimestampUrl -notmatch '^https://') { throw 'TimestampUrl must use HTTPS.' }
    $signToolPath = (Get-Command $SignTool -ErrorAction Stop).Source
    if ((Get-AuthenticodeSignature -LiteralPath $signToolPath).Status -ne 'Valid') { throw 'SignTool itself must have a valid Authenticode signature.' }
}
$workspaceRoot = [IO.Path]::GetFullPath($repo).TrimEnd('\') + '\'
foreach ($target in @($stage,$bundle)) {
    $resolvedTarget = [IO.Path]::GetFullPath($target)
    if (-not $resolvedTarget.StartsWith($workspaceRoot,[StringComparison]::OrdinalIgnoreCase)) { throw 'Build output must remain inside this project.' }
}
Remove-Item -LiteralPath $stage,$bundle -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $stage,$bundle,(Join-Path $stage 'app'),(Join-Path $stage 'vendor'),(Join-Path $stage 'wheelhouse') | Out-Null

& $DotNetExe publish (Join-Path $repo 'deploy/windows-node/windows/Finfusion.NodeHost/Finfusion.NodeHost.csproj') -c Release -o (Join-Path $output 'node-host') --self-contained true
if ($LASTEXITCODE -ne 0) { throw 'Node host build failed.' }
& $DotNetExe publish (Join-Path $repo 'deploy/windows-node/windows/Finfusion.Control/Finfusion.Control.csproj') -c Release -o (Join-Path $output 'control') --self-contained true
if ($LASTEXITCODE -ne 0) { throw 'Control GUI build failed.' }
$hostProduct = Join-Path $output 'node-host/finfusion-node.exe'
$guiProduct = Join-Path $output 'control/FinfusionServer-Control.exe'
if (-not $InternalUnsigned) {
    & $signToolPath sign /sha1 $SigningCertificateThumbprint /fd SHA256 /tr $TimestampUrl /td SHA256 $hostProduct $guiProduct
    if ($LASTEXITCODE -ne 0) { throw 'Host/GUI Authenticode signing failed.' }
    foreach ($product in @($hostProduct,$guiProduct)) {
        if ((Get-AuthenticodeSignature -LiteralPath $product).Status -ne 'Valid') { throw "Invalid Authenticode signature: $product" }
    }
}
Copy-Item -LiteralPath $hostProduct -Destination (Join-Path $bundle 'FinfusionServer-NodeHost.exe')
Copy-Item -LiteralPath $guiProduct -Destination $bundle
Copy-Item -LiteralPath $DebianRootfs -Destination (Join-Path $bundle 'debian-12-wsl-rootfs.tar.gz')
Copy-Item -LiteralPath (Join-Path $repo 'deploy/windows-node/windows/Install-FinfusionNode.ps1') -Destination $bundle
Copy-Item -LiteralPath (Join-Path $repo 'deploy/windows-node/windows/Uninstall-FinfusionNode.ps1') -Destination $bundle
Copy-Item -LiteralPath (Join-Path $repo 'deploy/windows-node/windows/Invoke-WslBootstrap.ps1') -Destination $bundle
Copy-Item -LiteralPath (Join-Path $repo 'deploy/windows-node/config.example.json') -Destination $bundle
Copy-Item -LiteralPath (Join-Path $repo 'deploy/windows-node/dependencies.lock.json') -Destination $bundle
Copy-Item -Recurse -LiteralPath (Join-Path $repo 'packaging/LICENSES') -Destination $bundle

foreach ($sourceName in @('finfusion_common','finfusion','server_admin')) {
    $sourceDirectory = Join-Path $repo $sourceName
    Get-ChildItem -LiteralPath $sourceDirectory -Recurse -File | Where-Object { $_.FullName -notmatch '[\\/]__pycache__[\\/]' -and $_.Extension -notin @('.pyc','.pyo') } | ForEach-Object {
        $relative = [IO.Path]::GetRelativePath($sourceDirectory,$_.FullName)
        $destination = Join-Path (Join-Path $stage 'app') (Join-Path $sourceName $relative)
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $destination) | Out-Null
        Copy-Item -LiteralPath $_.FullName -Destination $destination
    }
}
New-Item -ItemType Directory -Force -Path (Join-Path $stage 'bin'),(Join-Path $stage 'systemd') | Out-Null
Get-ChildItem -LiteralPath (Join-Path $repo 'deploy/windows-node/linux/bin') -File | ForEach-Object {
    Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $stage 'bin')
}
Get-ChildItem -LiteralPath (Join-Path $repo 'deploy/windows-node/linux/systemd') -File | ForEach-Object {
    Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $stage 'systemd')
}
Copy-Item -LiteralPath (Join-Path $repo 'deploy/windows-node/linux/install.sh') -Destination $stage
& $PythonExe (Join-Path $repo 'packaging/extract_casdoor_release.py') $CasdoorArchive (Join-Path $stage 'vendor/casdoor-release') --manifest-out (Join-Path $stage 'casdoor-release-manifest.json') --expected-sha256 $CasdoorSha256
if ($LASTEXITCODE -ne 0) { throw 'Casdoor release archive validation/extraction failed.' }
Copy-Item -LiteralPath $CloudflaredBinary -Destination (Join-Path $stage 'vendor/cloudflared')
Copy-Item -LiteralPath (Join-Path $repo 'packaging/VERSION') -Destination $stage
Copy-Item -LiteralPath $DebianBaseManifest -Destination (Join-Path $stage 'debian-base-manifest.json')
if (-not $SkipWheelDownload) {
    $pahoBuildVenv = Join-Path $output 'paho-build-venv'
    & $PythonExe -m venv $pahoBuildVenv
    if ($LASTEXITCODE -ne 0) { throw 'Could not create isolated paho-mqtt build environment.' }
    $pahoPython = Join-Path $pahoBuildVenv 'Scripts/python.exe'
    & $pahoPython -m pip install 'pip==24.0' 'setuptools==69.5.1' 'wheel==0.43.0'
    if ($LASTEXITCODE -ne 0) { throw 'Could not provision pinned paho-mqtt build tools.' }
    & $pahoPython -m pip wheel --no-deps --no-build-isolation --wheel-dir (Join-Path $stage 'wheelhouse') $PahoMqttSdist
    if ($LASTEXITCODE -ne 0) { throw 'paho-mqtt 1.6.1 wheel build failed.' }
    & $PythonExe -m pip download --only-binary=:all: --platform manylinux2014_x86_64 --python-version 311 --implementation cp --find-links (Join-Path $stage 'wheelhouse') --dest (Join-Path $stage 'wheelhouse') -r (Join-Path $repo 'deploy/windows-node/python-requirements.in')
    if ($LASTEXITCODE -ne 0) { throw 'Linux wheel download failed.' }
}
$wheels = Get-ChildItem -LiteralPath (Join-Path $stage 'wheelhouse') -File
if (-not $wheels) { throw 'Wheelhouse is empty.' }
$requirementLines = foreach ($wheel in $wheels) {
    $parts = $wheel.Name.Split('-')
    if ($parts.Count -lt 2) { throw "Cannot parse wheel name: $($wheel.Name)" }
    $name = $parts[0].Replace('_','-')
    $version = $parts[1]
    "$name==$version --hash=sha256:$((Get-FileHash -LiteralPath $wheel.FullName -Algorithm SHA256).Hash.ToLowerInvariant())"
}
$requirementLines | Set-Content -LiteralPath (Join-Path $stage 'python-requirements.lock') -Encoding utf8
tar.exe -czf (Join-Path $bundle 'bootstrap.tar.gz') -C $stage .
if ($LASTEXITCODE -ne 0) { throw 'Bootstrap archive failed.' }

$files = [ordered]@{}
Get-ChildItem -LiteralPath $bundle -Recurse -File | Where-Object Name -ne 'bundle-manifest.json' | Sort-Object FullName | ForEach-Object {
    $relative = [IO.Path]::GetRelativePath($bundle,$_.FullName).Replace('\','/')
    $files[$relative] = [ordered]@{ sha256=(Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant(); bytes=$_.Length }
}
$manifest = [ordered]@{
    schemaVersion=1; product='Finfusion Node'; version=(Get-Content (Join-Path $repo 'packaging/VERSION') -Raw).Trim(); createdUtc=[DateTime]::UtcNow.ToString('o')
    target='windows-x64+wsl2-debian12-amd64'; uiHashes=(Get-Content (Join-Path $repo 'packaging/ui-hashes.json') -Raw | ConvertFrom-Json)
    dependencies=[ordered]@{ debianBase=(Get-Content $DebianBaseManifest -Raw | ConvertFrom-Json); casdoor=$CasdoorVersion; cloudflared=$CloudflaredVersion; webullSdk='2.0.18'; dotnetRuntime='8.0.13-self-contained' }
    files=$files
}
$manifest | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath (Join-Path $bundle 'bundle-manifest.json') -Encoding utf8
$report = [ordered]@{ success=$true; bundle=$bundle; fileCount=$files.Count; generatedUtc=[DateTime]::UtcNow.ToString('o'); signed=(-not $InternalUnsigned); internalUnsigned=[bool]$InternalUnsigned; signingCertificateThumbprint=$SigningCertificateThumbprint }
$version = (Get-Content -LiteralPath (Join-Path $repo 'packaging/VERSION') -Raw).Trim()
$innoPath = (Get-Command $InnoCompiler -ErrorAction Stop).Source
$innoSignature = Get-AuthenticodeSignature -LiteralPath $innoPath
if ($innoSignature.Status -ne 'Valid' -or $innoSignature.SignerCertificate.Subject -notmatch 'Pyrsys B\.V\.') { throw 'Inno Setup compiler signature validation failed.' }
$innoDefines = @("/DArtifactsDir=$bundle", "/DOutputDir=$output", '/DReleasePayload', "/DProductVersion=$version")
if ($InternalUnsigned) { $innoDefines += '/DInternalUnsignedPayload' }
& $InnoCompiler @innoDefines (Join-Path $repo 'packaging/FinfusionServer.iss')
$setupName = if ($InternalUnsigned) { 'FinfusionServer-Setup-x64-INTERNAL.exe' } else { 'FinfusionServer-Setup-x64.exe' }
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath (Join-Path $output $setupName))) { throw 'Inno Setup build failed.' }
$setupProduct = Join-Path $output $setupName
if (-not $InternalUnsigned) {
    & $signToolPath sign /sha1 $SigningCertificateThumbprint /fd SHA256 /tr $TimestampUrl /td SHA256 $setupProduct
    if ($LASTEXITCODE -ne 0 -or (Get-AuthenticodeSignature -LiteralPath $setupProduct).Status -ne 'Valid') { throw 'Installer Authenticode signing failed.' }
}
$report['windowsProducts'] = [ordered]@{
    controlGui=[ordered]@{ path=(Join-Path $bundle 'FinfusionServer-Control.exe'); sha256=(Get-FileHash -LiteralPath (Join-Path $bundle 'FinfusionServer-Control.exe') -Algorithm SHA256).Hash.ToLowerInvariant() }
    installer=[ordered]@{ path=$setupProduct; sha256=(Get-FileHash -LiteralPath $setupProduct -Algorithm SHA256).Hash.ToLowerInvariant() }
}
$report | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $output 'build-report.json') -Encoding utf8
$hashProducts = @(
    $setupProduct,
    (Join-Path $bundle 'FinfusionServer-Control.exe'),
    (Join-Path $bundle 'FinfusionServer-NodeHost.exe'),
    (Join-Path $bundle 'bundle-manifest.json'),
    (Join-Path $output 'build-report.json')
)
$hashProducts | ForEach-Object {
    "$((Get-FileHash -LiteralPath $_ -Algorithm SHA256).Hash.ToLowerInvariant())  $([IO.Path]::GetRelativePath($output,$_).Replace('\','/'))"
} | Set-Content -LiteralPath (Join-Path $output 'SHA256SUMS.txt') -Encoding ascii
if ($InternalUnsigned) {
    Write-Warning 'Built an INTERNAL unsigned package. Windows SmartScreen may warn; do not publish it as a signed release.'
} else {
    Write-Host "Built signed control GUI: $(Join-Path $bundle 'FinfusionServer-Control.exe')"
}
Write-Host "Built installer: $setupProduct"
