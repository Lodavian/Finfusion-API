# Development compiler only; this does not install Finfusion Client.
$ErrorActionPreference='Stop'
$installer=Join-Path $PSScriptRoot 'packaging\vendor\innosetup-7.1.0-x64.exe'
$compilerDir=Join-Path $PSScriptRoot 'packaging\tools\Inno'
$sig=Get-AuthenticodeSignature -LiteralPath $installer
if ($sig.Status -ne 'Valid' -or $sig.SignerCertificate.Subject -notlike '*Pyrsys*') { throw 'Inno Setup 官方编译器签名验证失败' }
$arguments='/CURRENTUSER /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /NOICONS /DIR="'+$compilerDir+'"'
$p=Start-Process -FilePath $installer -ArgumentList $arguments -WindowStyle Hidden -Wait -PassThru
if ($p.ExitCode -ne 0) { throw '编译器安装失败' }
Write-Output '已准备当前用户的 Inno Setup 7.1.0 开发编译工具，未安装 Finfusion Client。'
