param([string]$Compiler = "$PSScriptRoot\packaging\tools\Inno\ISCC.exe", [string]$Version='1.0.0-rc1', [string]$OutputName='')
$ErrorActionPreference='Stop'
if (!$OutputName) { $OutputName="FinfusionClient-Setup-$Version" }
if ($Version -notmatch '^(\d+)\.(\d+)\.(\d+)(?:-rc(\d+))?(?:-qa)?$') { throw 'Unsupported package version.' }
$taskFileVersion = "$($Matches[1]).$($Matches[2]).$($Matches[3]).$([int]$Matches[4])"
$runtime=Join-Path $PSScriptRoot 'packaging\vendor\MicrosoftEdgeWebView2RuntimeInstallerX64.exe'
if (!(Test-Path -LiteralPath $Compiler)) { throw '需要 Inno Setup 7.1.0 x64 编译器。可通过 -Compiler 指定。' }
$sig=Get-AuthenticodeSignature -LiteralPath $runtime
if ($sig.Status -ne 'Valid' -or $sig.SignerCertificate.Subject -notlike '*Microsoft Corporation*') { throw '微软 WebView2 完整安装器签名验证失败' }
& $Compiler '/DInternalUnsignedRc' "/DMyAppVersion=$Version" "/DMyFileVersion=$taskFileVersion" "/DMyOutputBaseFilename=$OutputName" "/DStagingDir=$PSScriptRoot\dist\FinfusionClient" "$PSScriptRoot\packaging\FinfusionClient.iss"
if ($LASTEXITCODE -ne 0) { throw 'Inno 编译失败' }
Write-Output '未签名内部候选；当前电脑未执行应用安装。'
