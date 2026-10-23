param([switch]$DisposableVmConfirmed, [string]$Candidate="$PSScriptRoot\..\dist\installer\FinfusionClient-Setup-1.0.0-rc1.exe", [string]$Previous, [string]$Report="$PSScriptRoot\..\build\installer-lifecycle-1.0.json")
$ErrorActionPreference='Stop'
if (!$DisposableVmConfirmed) { throw '仅允许在用户提供的干净一次性 VM 运行，必须指定 -DisposableVmConfirmed。当前交易电脑禁止执行。' }
$identity=[Security.Principal.WindowsIdentity]::GetCurrent()
if (!(New-Object Security.Principal.WindowsPrincipal($identity)).IsInRole([Security.Principal.WindowsBuiltinRole]::Administrator)) { throw '生命周期测试需要管理员权限' }
$appId='{C0BFB545-5213-4D5C-BC59-FF5B2E974643}_is1'
$registry="HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\$appId"
if (Test-Path $registry) { throw '测试机已有 Finfusion 安装注册项，拒绝运行' }
$data=Join-Path $env:LOCALAPPDATA 'Finfusion\Client'
if (Test-Path $data) { throw '测试用户已有客户端数据，必须更换干净测试用户' }
if (!$Previous -or !(Test-Path -LiteralPath $Previous)) { throw '请先使用 build-installer.ps1 -Version 0.1.9-qa -OutputName FinfusionClient-Setup-0.1.9-qa 创建前序测试安装器。这不是旧版产品发布包。' }
$results=[ordered]@{machine=$env:COMPUTERNAME;user=$identity.Name;steps=@();ordinaryUserLaunch='PENDING_MANUAL';runtimeMissingOffline='PENDING_MANUAL';signature='UNSIGNED_INTERNAL_RC'}
function Install([string]$Path) {
  $p=Start-Process -FilePath $Path -ArgumentList '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /TASKS=desktopicon' -WindowStyle Hidden -Wait -PassThru
  if ($p.ExitCode -ne 0) { throw "安装失败：$($p.ExitCode)" }
}
function CheckApp {
  $app=Join-Path ${env:ProgramFiles} 'Finfusion Client\FinfusionClient.exe'
  if (!(Test-Path -LiteralPath $app)) { throw '应用主体缺失' }
  $temp=Join-Path $env:TEMP ('Finfusion-QA-'+[guid]::NewGuid()+'.json')
  $p=Start-Process -FilePath $app -ArgumentList "--smoke-test --smoke-result `"$temp`"" -WindowStyle Hidden -Wait -PassThru
  if ($p.ExitCode -ne 0) { throw '真实 WebView2 启动失败' }
  $r=Get-Content -LiteralPath $temp -Raw | ConvertFrom-Json
  if (!$r.guiOpened -or !$r.bridgeLoaded -or !$r.tradeDisabledBeforeAuth -or !$r.dpapiRoundTrip) { throw '启动验证未通过' }
}
try {
  Install $Previous; CheckApp; $results.steps+='previous-fixture-install-and-launch:PASS'
  New-Item -ItemType Directory -Path $data -Force | Out-Null
  $sentinel=Join-Path $data 'QA-data-preservation.sentinel'; [IO.File]::WriteAllText($sentinel,[guid]::NewGuid().ToString()); $hash=(Get-FileHash $sentinel).Hash
  Install $Candidate; CheckApp; $results.steps+='upgrade:PASS'
  Install $Candidate; CheckApp; $results.steps+='same-version-repair:PASS'
  $p=Start-Process -FilePath $Previous -ArgumentList '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART' -WindowStyle Hidden -Wait -PassThru
  if ($p.ExitCode -eq 0) { throw '降级未被拒绝' }; $results.steps+='downgrade-refusal:PASS'
  $uninstaller=Join-Path ${env:ProgramFiles} 'Finfusion Client\unins000.exe'
  $p=Start-Process -FilePath $uninstaller -ArgumentList '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART' -WindowStyle Hidden -Wait -PassThru
  if ($p.ExitCode -ne 0 -or (Test-Path $registry)) { throw '卸载失败' }
  if ((Get-FileHash $sentinel).Hash -ne $hash) { throw '用户数据被改动' }; $results.steps+='uninstall-data-preserved:PASS'
  Install $Candidate; CheckApp
  if ((Get-FileHash $sentinel).Hash -ne $hash) { throw '重装数据未保留' }; $results.steps+='reinstall:PASS'
  $results.manual='仍需普通用户启动、运行中覆盖拒绝、无运行时离线安装、DPAPI/SQLite 真实数据保留。请按 ACCEPTANCE-0.2.md 执行。'
} catch { $results.failure=$_.Exception.Message; throw }
finally { $results | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $Report -Encoding utf8 }
