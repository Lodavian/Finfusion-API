# Windows + WSL2 部署与验收

首次使用新电脑请从 [新电脑详细部署指南](NEW_COMPUTER_DEPLOYMENT.md) 开始；本文保留架构与验收概要。

本文供后续在另一台目标电脑部署时使用，不是当前开发机的执行清单。当前仅进行开发、构建及自动化测试；目标机安装和真实券商联调留待部署阶段。

本版部署为 Windows 宿主服务 + 专用 `FinfusionNode` Debian 12 WSL2，内含 PostgreSQL、Casdoor、Finfusion、cloudflared 和 age Vault。源代码、构建输入从本项目取得；安装副本和数据使用系统服务目录。

## 发布前准备

1. 准备支持 WSL2 的 Windows x64 电脑、可用网络和系统时间同步，关闭自动休眠。验证 Windows 自带 `wsl --status` 正常。
2. 将经审核的 Debian rootfs/包清单、Casdoor 压缩包、cloudflared、paho-mqtt 源码包放在本项目 `build/release-inputs/`，按 `dependencies.lock.json` 和构建脚本核对 SHA-256。不能从旧项目读取这些制品。
3. 编译工具为 .NET 8 SDK、Python 3.11、Inno Setup；源码路径允许空格。构建缓存/包目录保留在本项目 `build/`。
4. 使用 `packaging/build_windows_node.ps1` 的必需参数指定项目内输入。正式发布需 Authenticode 签名；内部包显式使用 `-InternalUnsigned`。本轮未生成完整发布安装包。
5. 先在隔离的目标电脑安装内部 Sandbox 节点，验证安装、停止、重启、卸载与恢复。不要直接覆盖已有节点。

开发安装器构建脚本只用于检查 Windows 控制台与宿主程序，不代表完整 Linux/券商环境已可用。

## 配置环境

复制 `deploy/windows-node/config.example.json` 到受限的私有配置目录，填写以下内容，不提交 Git：

- 三个不同的 HTTPS 域名：API、管理员、身份认证。
- Cloudflare named Tunnel token，按域名将 API/管理员转发到 loopback 8080、身份认证转发到 loopback 8000。
- Casdoor 应用配置，管理员角色为 `finfusion-admin`，启用管理员网页所需的 OIDC PKCE 回调与 token CORS。
- 当前环境的 Webull 机构 App Key/App Secret。
- 本地 PostgreSQL DSN、Casdoor 数据库配置、离线备份 age 公钥。
- 明确的单笔数量/金额、市价单数量/估算金额、日累计额度与最大未完成订单数。

环境约束：

| 项目 | Sandbox | LIVE |
|---|---|---|
| `environment` | `SANDBOX` | `LIVE` |
| `liveAllowed` | `false` | 必须显式 `true` |
| 数据库名 | `finfusion_sandbox` | `finfusion_live` |
| API 密钥目录 | `/run/finfusion/secrets/sandbox` | `/run/finfusion/secrets/live` |
| SDK token 目录 | `/var/lib/finfusion/webull_tokens/sandbox` | `/var/lib/finfusion/webull_tokens/live` |

每个专用 WSL 节点固定一个环境。本版禁止已配置节点原地切换环境，先备份并按新节点流程部署另一环境。数据库内部还有环境标记校验，防止误连。

首次配置生成账户加密主密钥并密封到 Vault。再次配置必须提供原来的 `accountMasterKey`，不得生成新密钥覆盖已有账户数据。配置以管理员权限经控制台执行，完成后节点仍不激活。私有配置中的数据库密码和其他密钥不得写入文档或工单。

## 启动顺序

1. 运行节点诊断，确认 PostgreSQL、Vault、Casdoor、Finfusion、cloudflared 正常。
2. 在管理员网页创建用户、登记已发现的券商账户、分配账户、登记并批准程序公钥。
3. 客户端先调用账户/持仓/资金查询；检查跨账户拒绝行为。
4. 操作者激活节点；检查 `/readyz` 中数据库、行情、订单事件、对账、节点和 Tunnel 状态。
5. 管理员开启用户与账户交易权限，最后开启交易总开关。

`/livez` 只代表进程存在，不代表可交易。`/readyz` 的 `effectiveTradeEnabled` 才反映基础设施及全局开关的有效组合；具体用户仍受自身与账户开关约束。

应用重启后全局交易开关恢复关闭。节点/Tunnel 心跳异常时禁止新单和改单；服务仅监听 loopback，不直接开放 Python 服务端口到公网。

## 备份、恢复与升级

使用项目内提供的 `node-backup`、`node-restore`、`node-update` 和 `node-doctor`，由 Windows 控制台调用专用节点内安装副本。

- 备份包含当前环境的 PostgreSQL 数据、Casdoor 数据、Vault、token 和配置，整体加密为 `.age`；解密身份保留在节点之外。
- 恢复前检查归档路径、成员类型、权限、哈希及环境；禁止 Sandbox 备份恢复到 LIVE 节点或反向恢复。
- 恢复前生成加密回退备份；恢复后节点及交易开关保持关闭，先重新对账。
- 升级必须先关闭交易并备份，只接受经过签名验证的升级包。数据库变更本版为增量添加；安装前仍须做真实 PostgreSQL 迁移和回滚演练。
- 单环境只运行一个交易进程，PostgreSQL advisory lock 会阻止第二个进程绕过账户串行锁。

## 验收记录

**Sandbox**：远程签名请求、行情与事件链路、下单/查询/改单/撤单、重复请求、超时恢复、账户隔离、客户端轮换、断网/Tunnel 故障、重启默认关闭、备份恢复。

**生产**：核实生产域名与证书、机构凭据、账户列表、风险额度、时间同步、节点自动恢复和离线备份。完成后仍保持总开关关闭。

**实盘**：先明确授权的账户、股票、方向、数量及价格边界，再执行受控下单、改单、撤单和对账。没有这些输入，不自动提交任何实盘订单。
