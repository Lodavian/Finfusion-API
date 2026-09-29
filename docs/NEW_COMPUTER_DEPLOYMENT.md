# 新电脑部署指南

本文面向从 GitHub 首次取得 Finfusion API 的部署人员，也可交给新电脑上的开发助手作为交接说明。仓库地址：<https://github.com/Lodavian/Finfusion-API>。

**当前是开发交付版本，尚未完成全新电脑上的完整安装验收。** 本文依据仓库脚本编写，不代表所有部署步骤已经实测成功。现在的开发电脑不安装服务；以下安装操作只在以后指定的目标电脑执行。

## 1. 先了解你拿到了什么

| 内容 | 是否在 Git 仓库 | 说明 |
|---|---|---|
| Python API、管理员网页、数据库迁移、客户端 SDK | 是 | 不依赖原三个参考项目 |
| Windows 宿主、控制台、Linux 运维脚本 | 是 | 包含源代码和构建脚本 |
| 配置模板、依赖版本、测试、接口文档 | 是 | 模板中的占位符必须替换 |
| Python 虚拟环境、.NET SDK、NuGet 缓存 | 否 | 在新电脑重新安装或下载 |
| Debian rootfs、Casdoor、cloudflared、Python wheel 包 | 否 | 构建时准备，放入本项目的 build 目录 |
| 完整发布安装包 | 尚未生成 | Windows 两个组件编译成功不等于完整安装包验收成功 |
| 域名、Tunnel token、Webull 密钥、数据库密码 | 否 | 部署者提供，不能提交 Git |
| 运行数据库、用户配置、券商 token、备份 | 否 | 新装时生成；迁移已有节点时通过加密备份恢复 |

已完成的开发验证：38 项自动化测试通过（含真实 PostgreSQL 临时库测试）、独立性检查通过、两个 Windows 项目编译通过。详细证据见 [verification.json](verification.json) 和 [DELIVERY.md](DELIVERY.md)。新电脑运行普通测试脚本时，没有配置测试数据库会有 1 项跳过，这是明确的验证范围差异。

## 2. 部署架构与执行位置

用户程序 → 公网 HTTPS 域名 → Cloudflare Tunnel → WSL2 内的 Finfusion API → Webull。

- Windows 宿主服务：`FinfusionNodeHost`，以 `LocalSystem` 运行。
- 专用 WSL2 发行版：`FinfusionNode`，Debian 12 amd64，由安装器在 **LocalSystem 账户下**导入。
- WSL 内服务：PostgreSQL 17、Casdoor、Finfusion、cloudflared、Vault 及节点监控。
- Python API 在 Linux 中运行；Windows `.venv` 用于开发、测试和客户端示例。
- 管理员通过 Casdoor 登录网页；普通调用程序用 `clientId` 和 P-256 私钥签名，不进行网页登录。

**不要在普通 Windows 用户下手工导入同名 FinfusionNode。** 普通终端的 `wsl -l -v` 看不到系统账户下的发行版，不足以说明安装丢失。日常操作通过管理员终端里的 Windows 宿主命令完成。

目录约定：

| 路径 | 用途 |
|---|---|
| `C:\Finfusion API` | 本文示例源码目录；可以改到其他盘，支持空格 |
| `C:\Finfusion API\build\release-inputs` | 当前项目内的构建输入 |
| `C:\Program Files\Finfusion Node` | 默认 Windows 安装目录 |
| `C:\ProgramData\Finfusion` | 默认节点数据、WSL 磁盘及安装记录 |
| `/opt/finfusion` | WSL 内安装副本及版本目录 |
| `/etc/finfusion` | WSL 配置 |
| `/var/lib/finfusion` | Vault、券商 token 和身份服务数据 |

源码目录不是运行数据目录。后续 `git pull` 不会自动升级已安装服务。

## 3. 开始前准备清单

目标机器需要 Windows x64、硬件虚拟化和可用的 WSL2，安装者有本机管理员权限。建议使用有持续供电、稳定网络和足够磁盘空间的机器；关闭自动休眠并保持系统时间同步。资源容量还未做负载基准测试，不把任何硬件配置视为吞吐量保证。

若在该电脑从源码构建，还需要：

- Git、Python 3.11（包含 `py` 启动器）。
- PowerShell 7：发布脚本使用较新的 .NET API，构建时使用 `pwsh`。
- .NET 8 SDK；当前组件编译验证使用 8.0.415。
- Inno Setup 编译器 `ISCC.exe`；脚本要求其 Authenticode 签名有效且发布者符合校验。
- 一个可用的 Linux/WSL **构建环境**，运行 Debian 镜像构建脚本。它与正式运行的 `FinfusionNode` 不同。
- 可访问 GitHub、Python/NuGet 包源、Debian 和 PostgreSQL 包源。

可在独立构建机完成第 5～6 节，再把完整包交给部署机。单纯安装已构建的包不需要在部署机安装上述编译工具。

业务输入应提前准备：三个不同的域名、Cloudflare Tunnel、Webull Sandbox 机构凭据、Casdoor 初始化方案、数据库密码、备份公钥和明确的风险上限。首次采用 SANDBOX，不能把生产凭据填入测试环境。

## 4. 获取源码并验证开发环境

在普通 PowerShell 7 中执行；本文后续构建命令均以此目录为工作目录：

```powershell
git clone https://github.com/Lodavian/Finfusion-API.git 'C:\Finfusion API'
Set-Location 'C:\Finfusion API'
git status --short
git rev-parse HEAD
py -3.11 --version
pwsh --version
dotnet --list-sdks
.\setup-dev.ps1
.\run-tests.ps1
```

记录 `git rev-parse HEAD` 的提交号，构建及验收期间固定使用该版本。私有仓库需要先取得 GitHub 访问权限。不要复制旧电脑的 `.venv`，也不要设置指向旧项目的 `PYTHONPATH`。

普通测试预期：当前版本 37 项通过、真实 PostgreSQL 测试因未配置而跳过；若准备项目内 PostgreSQL 二进制，可使用：

```powershell
.\.venv\Scripts\python.exe tools\test_with_postgres.py --bin-dir 'build\tool-cache\postgresql-17.11-3\pgsql\bin'
```

上述目录不会随 Git 下载。需先从 [EDB 官方二进制页面](https://www.enterprisedb.com/download-postgresql-binaries) 准备对应二进制。工具会创建回环地址临时库，运行完整测试并停止数据库，不安装系统服务。测试日志在 `runtime/postgres-test-*`。

## 5. 准备完整构建输入

### 5.1 Debian 12 系统镜像

在构建电脑的 Linux/WSL 中，确认源码可见后运行。例如 Windows 源码在 `C:\Finfusion API` 时，其 Linux 路径通常为 `/mnt/c/Finfusion API`：

```bash
sudo bash '/mnt/c/Finfusion API/packaging/build_debian12_wsl_rootfs.sh' \
  '/mnt/c/Finfusion API/build/release-inputs'
```

此脚本会在**构建环境**安装 debootstrap 等工具，通过 Debian/PGDG 源构建 Debian 12 + PostgreSQL 17 镜像，要求 root 权限、网络及挂载能力。输出应包含：

- `debian-12-wsl-rootfs.tar.gz`
- `debian-12-base-manifest.json`
- `SHA256SUMS`

镜像与包清单必须是同一次构建的配对产物；不能用任意 Debian 压缩包替换。脚本记录实际包版本，不是固定日期的 Debian 仓库快照，不保证不同日期的构建逐字节相同。失败时保存日志，先解决构建问题，不进入安装步骤。

### 5.2 其他输入

把以下文件保存到 `build/release-inputs`。该目录被 Git 忽略；换电脑时需重新取得或传递经过核验的同一批文件。

| 文件 | 当前脚本要求 | 来源与核验 |
|---|---|---|
| `casdoor_Linux_x86_64.tar.gz` | Casdoor 3.143.0 | [官方版本页面](https://github.com/casdoor/casdoor/releases/tag/v3.143.0)，与仓库锁定哈希核对 |
| `cloudflared-linux-amd64` | cloudflared 2026.9.1 | [官方版本页面](https://github.com/cloudflare/cloudflared/releases/tag/2026.9.1)，与仓库锁定哈希核对 |
| `paho-mqtt-1.6.1.tar.gz` | paho-mqtt 1.6.1 源码包 | 从包源下载，构建脚本核对固定 SHA-256 |

下载 paho 源码包：

```powershell
New-Item -ItemType Directory -Force 'build\release-inputs' | Out-Null
.\.venv\Scripts\python.exe -m pip download --no-deps --no-binary=:all: 'paho-mqtt==1.6.1' --dest 'build\release-inputs'
Get-FileHash -Algorithm SHA256 'build\release-inputs\*'
```

具体锁定值见 [dependencies.lock.json](../deploy/windows-node/dependencies.lock.json) 和 [发布脚本参数](../packaging/build_windows_node.ps1)。Casdoor 解包器还要求包内包含 `casdoor`、`conf/app.conf` 和完整 `web/build` 资源。不要用只有后端的二进制替代完整压缩包，也不要通过改哈希来跳过来源审核。若上游无法取得完全匹配的产物，当前发布构建就尚不具备条件，需要先完成依赖复核和开发调整。

### 5.3 构建前检查

```powershell
$repo = (Get-Location).Path
$inputs = Join-Path $repo 'build\release-inputs'
$required = @('debian-12-wsl-rootfs.tar.gz','debian-12-base-manifest.json','casdoor_Linux_x86_64.tar.gz','cloudflared-linux-amd64','paho-mqtt-1.6.1.tar.gz')
foreach ($name in $required) {
    if (-not (Test-Path -LiteralPath (Join-Path $inputs $name))) { throw "缺少构建输入：$name" }
}
```

## 6. 构建内部 Sandbox 安装包

在 PowerShell 7、源码根目录执行。此命令构建包，不安装服务。`ISCC.exe` 必须已在 PATH 中，或把 `InnoCompiler` 改成实际绝对路径。

```powershell
$repo = (Get-Location).Path
$inputs = Join-Path $repo 'build\release-inputs'
$rootfs = Join-Path $inputs 'debian-12-wsl-rootfs.tar.gz'
$baseManifest = Join-Path $inputs 'debian-12-base-manifest.json'
$buildArgs = @{
    DebianRootfs = $rootfs
    DebianRootfsSha256 = (Get-FileHash -LiteralPath $rootfs -Algorithm SHA256).Hash
    DebianBaseManifest = $baseManifest
    DebianBaseManifestSha256 = (Get-FileHash -LiteralPath $baseManifest -Algorithm SHA256).Hash
    CasdoorArchive = (Join-Path $inputs 'casdoor_Linux_x86_64.tar.gz')
    CloudflaredBinary = (Join-Path $inputs 'cloudflared-linux-amd64')
    PahoMqttSdist = (Join-Path $inputs 'paho-mqtt-1.6.1.tar.gz')
    DotNetExe = 'dotnet'
    PythonExe = (Join-Path $repo '.venv\Scripts\python.exe')
    InnoCompiler = 'ISCC.exe'
    InternalUnsigned = $true
}
.\packaging\build_windows_node.ps1 @buildArgs
```

计算本地哈希用来绑定已经审核的镜像与清单，不能替代来源可信度核验。发布脚本还会下载 Linux Python wheels；不能用 Windows wheels 替换。首次构建不要使用 `-SkipWheelDownload`。

预期输出在 `build/windows-node`：

- `FinfusionServer-Setup-x64-INTERNAL.exe`
- 完整 `FinfusionNode-online` 目录，含 rootfs、bootstrap、manifest、宿主和控制台
- `build-report.json`、`SHA256SUMS.txt`

向另一台电脑交付时，应保留整套包和校验文件，不能只复制控制台 EXE。`build_windows_node_dev.ps1` 仅生成开发外壳，缺少 Linux 运行载荷，不能用它的安装器验收实际部署。

正式发布去掉 `InternalUnsigned`，提供 `SignTool`、`SigningCertificateThumbprint` 和 HTTPS `TimestampUrl`；证书由发布者准备。内部未签名包仅用于隔离的测试部署。目前完整构建尚未实测，任何阶段报错都需要先解决再继续。

## 7. 在目标电脑安装节点

以下开始改变目标电脑系统状态，应在准备好的测试部署电脑进行。

1. 根据 [Microsoft WSL 安装说明](https://learn.microsoft.com/en-us/windows/wsl/install) 准备 WSL2，按提示重启 Windows。
2. 在管理员 PowerShell 中执行 `wsl --status`，确保没有虚拟化或内核错误。
3. 确认没有正在使用的同名节点及 `FinfusionNodeHost` 服务；不要把首次安装当成覆盖升级。
4. 核对构建机提供的 SHA256SUMS 和传输后的文件，保留构建提交号。
5. 使用完整 bundle 安装。下面路径假设包放在 `C:\FinfusionDeploy`，按实际位置修改。

```powershell
$bundle = 'C:\FinfusionDeploy\FinfusionNode-online'
& (Join-Path $bundle 'Install-FinfusionNode.ps1') -BundleDirectory $bundle -AllowUnsignedDevelopment
```

只有内部测试包使用 `-AllowUnsignedDevelopment`；正式签名包省略该开关。首次安装不要使用 `-SkipWslImport`。若提示 `REBOOT-REQUIRED`，重启后再运行，不反复手工导入 WSL。

安装器导入 Linux、复制代码、建立服务，**不会替你提供域名和券商凭据**。完成后检查：

```powershell
Get-Service FinfusionNodeHost
$node = Join-Path $env:ProgramFiles 'Finfusion Node\FinfusionServer-NodeHost.exe'
& $node status
```

安装记录在 `C:\ProgramData\Finfusion\install-staging\result.json`，宿主日志在 `C:\ProgramData\Finfusion\node-host.log`。配置未完成时 Linux 业务服务尚未全部健康，不等同于可以交易。

## 8. 首次身份服务与网络初始化：当前需要人工联调

**这是尚未完成全新机器验收的关键步骤。** `configure` 要求已有 Casdoor Client ID/Secret；仓库没有自动创建首个 Casdoor 组织、应用和管理员的脚本。它还会使用 PostgreSQL，因此配置前必须确认数据库已启动。不要用虚构 Client ID 或临时生产凭据强行通过。

如果部署者尚未取得有效 Casdoor 配置，应在此停止后续业务启动，由开发/部署人员在目标 Sandbox 完成以下初始化闭环并记录方法：

1. 核验系统账户下 PostgreSQL、Vault 和 Casdoor 的首次启动顺序。
2. 在实际部署的 Casdoor 实例中建立组织 `finfusion`、应用 `finfusion-admin`、管理员和所需应用权限；创建用户等管理 API 也需要应用授权。
3. 取得真实 Client ID/Secret；配置授权码 + PKCE、回调地址 `https://admin.你的域名/admin/`、管理员源站的 token CORS。
4. 核验 JWT issuer、audience、JWKS 和 `finfusion-admin` 角色声明与服务端兼容；以实际管理员 API 返回结果为准，不能只以网页登录成功为准。
5. 保存稳定的账户加密主密钥，再进行最终节点配置。

参考 [Casdoor 应用配置](https://casdoor.ai/docs/application/config/)。当前宿主命令只暴露固定运维动作，未提供任意 Linux shell；若首次初始化需要系统账户下的维护通道，应先由开发人员准备并审核，不能在普通用户的另一套 WSL 中配置后误以为作用于正式节点。

Cloudflare 端建立 named Tunnel，并按 [官方应用发布说明](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/routing-to-tunnel/) 配置：

| 公网域名示例 | 节点内目标 |
|---|---|
| `api.example.com` | `http://127.0.0.1:8080` |
| `admin.example.com` | `http://127.0.0.1:8080`，浏览器入口为 `/admin/` |
| `auth.example.com` | `http://127.0.0.1:8000` |

这里的 loopback 是运行 cloudflared 的同一 WSL 节点，不是另一台电脑。已有 systemd 服务负责启动 cloudflared，不要额外再装一套 Windows Tunnel 服务。程序 API 不应被要求浏览器交互登录的访问策略拦截；必须验证 `/v1/events` 的 WebSocket 连通性。

## 9. 创建私有配置并应用

复制 [config.example.json](../deploy/windows-node/config.example.json) 到目标电脑受限目录，例如 `C:\FinfusionPrivate\sandbox.json`。该目录仅允许管理员和 SYSTEM 访问。文件使用 **UTF-8 无 BOM**，且不得提交 Git。

| 字段 | 填写规则 |
|---|---|
| `apiDomain` / `authDomain` / `adminDomain` | 三个不同的完整域名，不带 `https://` 和路径 |
| `environment` / `liveAllowed` | 首次固定 `SANDBOX` / `false` |
| `casdoorClientId` / `casdoorClientSecret` | 第 8 节初始化所得真实值 |
| `casdoorOrganization` / `casdoorApplication` | 与 Casdoor 实际组织和应用一致 |
| `databaseDsn` | `postgresql://finfusion:密码@127.0.0.1:5432/finfusion_sandbox` |
| `casdoorDataSourceName` | 按模板使用本机 PostgreSQL，角色 `casdoor`、数据库 `casdoor` |
| `webullAppKey` / `webullAppSecret` | Webull 机构 Sandbox 凭据 |
| `tunnelToken` | 此节点对应的 named Tunnel token |
| `backupRecipient` | age X25519 备份公钥，形如 `age1...`；解密私钥留在节点之外 |
| `accountMasterKey` | 模板未列出，可额外填写；32 字节随机数据的 base64url 无填充编码，必须安全保管 |
| `quoteStaleSeconds` | 行情有效期，必须大于 0 且不超过 60 秒 |
| `riskLimits` | 所有字段必填、正数；数量及未完成订单数为整数；模板数值不是业务推荐值 |

数据库密码建议使用密码管理器生成的长随机十六进制字符串，避免当前连接字符串解析对特殊字符的歧义。API 与 Casdoor 使用不同密码。不要在命令行参数中直接粘贴密钥。

`accountMasterKey` 首次可由程序生成，但当前没有专用导出命令；后续重新配置又要求提供原值。因此部署者宜预先通过密码管理工具生成并保管它，再写入私有配置。禁止重新生成主密钥去覆盖已经存有加密账户数据的节点。

在第 8 节前提满足后，以管理员 PowerShell 执行：

```powershell
$node = Join-Path $env:ProgramFiles 'Finfusion Node\FinfusionServer-NodeHost.exe'
& $node configure 'C:\FinfusionPrivate\sandbox.json'
if ($LASTEXITCODE -ne 0) { throw '配置失败，先检查脱敏日志，不继续启动' }
& $node start
& $node doctor
& $node status
```

`configure` 会创建/更新本地数据库角色、密封凭据并关闭节点激活状态；不是只做格式校验。失败可能已产生部分配置，须检查后再重试。配置文件应按私密材料保管，日志只共享脱敏版本。

## 10. 管理员配置和第一次只读 API 验证

1. 打开 `https://admin.你的域名/admin/`，使用 Casdoor 管理员登录。
2. 创建应用用户，登记机构凭据能够发现的账户，分配给对应用户。每个账户只能分配给一个用户。
3. 普通 API 用户在**自己的电脑**生成密钥：

```powershell
.\.venv\Scripts\python.exe -m client_sdk.keygen --directory runtime\my-client
```

4. 用户只提交 `public.pem`，管理员登记公钥、保存 `clientId` 并批准查询权限。用户保管 `private.pem`。
5. 在客户端电脑执行只读示例（替换域名和客户端 ID）：

```powershell
.\.venv\Scripts\python.exe -m examples.query_accounts --url https://api.example.com --client-id YOUR_CLIENT_ID --private-key runtime\my-client\private.pem
```

6. 根据 [API.md](API.md) 和 [openapi.json](openapi.json) 验证持仓、美元购买力、跨用户拒绝、禁用和轮换即时生效。对外使用 `accountRef`，不是 Webull 真实账户号。

先确认查询链路，再开交易权限。`/livez` 只表明进程存在；`/readyz` 还需检查数据库、行情、事件、对账、节点/Tunnel。初始总开关关闭时 `effectiveTradeEnabled=false` 是预期状态。

## 11. Sandbox 验收及交易开启顺序

准备好专用测试账户与订单参数后：

1. 确认配置仍为 SANDBOX，所有健康检查通过。
2. 管理员授予目标客户端交易/撤单权限，按需开启用户和账户交易开关。
3. 运行 `& $node activate` 激活节点基础设施门禁。
4. 在管理员网页最后开启全局交易开关；节点激活不等于全局交易开关已经打开。
5. 按下表验收，保存脱敏请求 ID、订单 ID、状态及测试时间。

| 场景 | 验收结果 |
|---|---|
| 账户、持仓、资金查询 | 只看到当前用户授权账户，无真实账户号/密钥泄漏 |
| 下单、改单、撤单 | 区分服务器接收、券商接受、部分成交和最终状态 |
| 相同幂等编号与内容 | 返回原结果，仅产生一笔券商订单 |
| 同一幂等编号但内容改变 | 返回冲突，不生成额外订单 |
| 请求超时/断线 | 查询原请求并对账；客户端不自动重发交易命令 |
| 行情未准备好或过期 | 新单/改单被拒绝，未发送给券商 |
| 客户端禁用、越权账户 | HTTP 和事件访问均被限制 |
| Tunnel/行情/事件/数据库故障 | 按门禁阻止新单/改单；查询、撤单按可用性和权限处理 |
| 重启 Windows 或服务 | 自动恢复服务后交易仍关闭，先对账再人工开启 |
| 加密备份及异机恢复 | 数据、权限、密钥可恢复，环境一致，交易保持关闭 |

实际断网和服务故障演练只在 Sandbox 测试节点进行。重启后不得用脚本自动恢复全局交易开关。

## 12. 日常控制、备份和迁移

以下命令均在目标电脑管理员 PowerShell 执行：

```powershell
$node = Join-Path $env:ProgramFiles 'Finfusion Node\FinfusionServer-NodeHost.exe'
& $node status
& $node doctor
& $node logs 200
& $node deactivate
```

`deactivate` 关闭基础设施交易门禁，但不等同于撤销已提交订单。`stop` 停止业务服务，`restart` 重启并保持节点关闭；有未完成订单时先查询、对账和制定操作方案。

备份前关闭交易，确认无正在处理的业务变更，并为每次备份使用新文件名：

```powershell
& $node deactivate
& $node backup 'C:\FinfusionBackups\sandbox-2026-09-29.age'
```

备份含数据库、Vault、token 和配置。文件加密不等于已验证可恢复；将副本保存到独立存储，并在另一台隔离测试节点执行恢复演练。解密 identity 不随备份放在同一位置。

以下恢复命令会改变目标数据，只在明确选定的恢复节点执行；需要同环境已初始化节点、原备份及外部解密私钥：

```powershell
& $node restore 'C:\FinfusionBackups\sandbox-2026-09-29.age' 'D:\OfflineKeys\backup-identity.txt'
```

恢复后先 `doctor`、`status`、查询账户及订单并完成对账，再决定是否激活。完整恢复仍待目标环境实测。GitHub 源码不能替代运行数据备份。

升级不是 `git pull`：当前 `update` 要求更新包、对应 manifest、minisign 签名以及节点上的受信公钥。仓库尚未提供经过验收的完整更新包发布流程；不能直接把安装器或 `bootstrap.tar.gz` 当成升级包使用。

## 13. 常见问题与停止条件

| 现象 | 先检查什么 |
|---|---|
| `py -3.11` 找不到 | Python 3.11 与启动器是否安装；不要复制旧虚拟环境 |
| 构建缺文件或 SHA-256 不匹配 | 第 5 节输入与锁定版本；不要关闭校验 |
| Linux wheel 下载失败 | 包源网络、锁定依赖和目标 Linux/Python 版本，不要混入 Windows wheel |
| Inno 签名校验失败 | 是否官方签名编译器，禁止删除签名校验后继续 |
| WSL 提示重启或虚拟化错误 | Windows 功能、BIOS 虚拟化、内核和重启状态 |
| 普通用户看不到 FinfusionNode | 检查 Windows 宿主状态；该发行版属于 LocalSystem |
| Host service unavailable / 拒绝访问 | `Get-Service FinfusionNodeHost`；终端是否以管理员身份运行 |
| 首次 configure 无法连接数据库 | 第 8 节初始化顺序；不要重复提交不同密钥碰运气 |
| Casdoor 登录或回调失败 | 实际应用、issuer/audience、PKCE、回调、CORS、JWT 角色 |
| doctor 报 wildcard listener | 定位哪个进程监听通配地址；包括 Casdoor 绑定配置，不应忽略该检查 |
| API 可查询但不能下单 | 客户端/用户/账户/全局权限、节点门禁、行情、事件、额度和对账 |
| 交易结果不确定 | 按 requestId / clientOrderId 查询，等待对账，不更换幂等号盲目重发 |
| 重新配置要求 accountMasterKey | 使用原密钥；遗失时走受控恢复，不生成新值覆盖 |
| 想把 SANDBOX 改成 LIVE | 当前禁止原地环境切换；先完成隔离部署方案 |

一台电脑当前默认只有一个固定名称的 `FinfusionNode`；文档中“独立环境”不代表现有安装器已经支持同机多节点。最直接的隔离方式是另一台目标电脑。不要手改环境、数据库或节点名称拼装未经验证的共存部署。

## 14. LIVE 前仍需完成的工作

- [ ] 全新目标电脑完成完整安装包构建和安装验收。
- [ ] 第 8 节首次 PostgreSQL/Casdoor 初始化闭环经实测，有可复现记录。
- [ ] 所有 Sandbox 场景与备份恢复通过。
- [ ] 生产域名、机构凭据、环境独立数据库/密钥/令牌目录及明确风险额度就绪。
- [ ] 生产节点安装后保持交易关闭，完成健康、授权及账户检查。
- [ ] 用户明确授权实盘账户、股票、方向、数量、价格边界和验收时段。

“部署完成”不自动授权实盘下单。实盘动作另行确认具体参数。

## 15. 交给新电脑部署人员的交接记录

请另建不含密钥的验收记录，填写：源码提交号、构建时间和工具版本、所有构建输入哈希、包哈希、目标 Windows/WSL 版本、环境类型、域名、初始化方法、各验收结果、备份位置与恢复演练结果、未解决问题。密钥只记录保管位置，不记录明文。

交接时同时提供本文件、[部署概要](DEPLOYMENT.md)、[API 说明](API.md)、[交付边界](DELIVERY.md) 和完整构建包。若只交付 Git 仓库，就必须从第 3～6 节准备工具和构建输入，不能承诺离线一键安装。
