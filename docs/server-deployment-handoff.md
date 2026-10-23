> 2026-10-23 仓库汇总说明：最新整体状态见根目录 `docs/CURRENT-STATUS.md`；本文保留各阶段背景，历史机器路径不代表新 clone 的路径。

# 给新服务器 Codex 的正式部署交接

交接日期：2026-10-04（Asia/Hong_Kong）。先读仓库根目录 `AGENTS.md`。本文记录源码真实状态与迁移边界，不宣称 Ubuntu 部署已经通过。

## 1. 仓库身份与固定基线

- 本地原仓库根目录：`E:\Finfusion API`。用户历史称 FastOrder，本仓库实际产品名和 Python 包名为 Finfusion。
- GitHub private repository：`https://github.com/Lodavian/Finfusion-API.git`。
- remote：`origin`；branch：`main`。
- 本次交接前的业务源码 baseline：`13d1e64ce0ce61e515cc15ff8582a5a18bc19dc5`。
- private 状态已通过带身份认证的 GitHub REST repository API 核对：`private=true`、`visibility=private`。新服务器推送前仍须重新核实。
- 交接提交包含本文、AGENTS.md、忽略规则与审计文档等迁移材料；**交接提交 SHA 以交接者最终提供的 SHA 为准**，不可把上述业务 baseline 误当成交接文档提交。提交无法在自己的内容中包含自己的最终哈希。
- 未创建正式 release tag，也不依赖 migration tag。不要从未知新提交直接启动生产服务。

### 推荐 clone

以下在新服务器的 **WSL2 Ubuntu Bash** 内执行。约定源码绝对路径 `/srv/finfusion-api`，应提前由部署者准备为当前部署用户可写、非共享目录。不要用 root 保存 GitHub 凭据，也不要把 PAT 写到 clone URL。

```bash
git clone --branch main --single-branch https://github.com/Lodavian/Finfusion-API.git /srv/finfusion-api
cd /srv/finfusion-api
git remote -v
git branch --show-current
git rev-parse HEAD
git status --short
```

把输出的完整 SHA 与本次交接消息中的 SHA 逐字核对。若不一致，先查看新增提交并停止部署，不盲目 reset。私有仓库认证失败时由用户登录 GitHub/配置有权限的凭据管理器或部署密钥，不改为公开仓库。

新 Codex 第一份文件：`/srv/finfusion-api/AGENTS.md`；第二份：`/srv/finfusion-api/docs/server-deployment-handoff.md`。如果用户选择其他 clone 根目录，所有绝对路径必须相应替换并报告。

## 2. 用途、架构与必需源码

用户程序以 P-256 签名调用 API；服务器做客户端鉴权、用户/账户授权、风控、PostgreSQL 订单记录及幂等处理，再用统一机构凭据访问 Webull。管理员网页使用 Casdoor。每个券商账户只分配给一个用户，公开 API 使用 opaque accountRef。

网络：外部 HTTPS → Cloudflare Tunnel → Linux loopback aiohttp API → Webull；订单事件经 `/v1/events` WebSocket 返回。账户级交易串行，数据库单进程 advisory lock，订单 UNKNOWN 先查询/对账，不自动重发交易命令。SELL 持仓检查不得改变。

必须保留以下完整源码，不从旧 FastOrder 目录导入或链接：

| 新服务器绝对路径 | 用途 |
|---|---|
| `/srv/finfusion-api/finfusion/` | API、安全、服务、网关、数据库；包含 migrations SQL |
| `/srv/finfusion-api/finfusion_common/` | 共享工具、错误及状态 |
| `/srv/finfusion-api/server_admin/` | frozen 管理员网页资源 |
| `/srv/finfusion-api/deploy/windows-node/linux/` | Linux 运维脚本、环境模板和 systemd 模板 |
| `/srv/finfusion-api/deploy/windows-node/windows/` | 原 Windows 专用 Debian 节点源码；不是 Ubuntu 安装脚本 |
| `/srv/finfusion-api/packaging/` | 打包输入清单、脚本及许可证 |
| `/srv/finfusion-api/client_sdk/`、`/srv/finfusion-api/examples/` | 客户端和只读示例 |
| `/srv/finfusion-api/tests/`、`/srv/finfusion-api/tools/` | 自动化验证工具 |

## 3. Python、依赖与入口

Python 要求 **3.11**。不要默认使用 Ubuntu 自带的其他 Python 版本，也不得为适配 Ubuntu 自动升级依赖。

- 生产依赖：`/srv/finfusion-api/requirements.txt`。
- 完整约束：`/srv/finfusion-api/requirements.lock`。
- 开发测试依赖：`/srv/finfusion-api/requirements-dev.txt`。
- Linux 打包清单：`/srv/finfusion-api/deploy/windows-node/python-requirements.in`、`/srv/finfusion-api/packaging/server-requirements.lock`。
- Broker SDK 锁定为 `webull-openapi-python-sdk==2.0.18`，本次未变更。
- 服务入口：`/srv/finfusion-api/finfusion/main.py`，模块调用 `python -m finfusion.main`，仅允许 Linux。
- 正式服务模板工作目录 `/opt/finfusion/current`，解释器 `/opt/finfusion/venv/bin/python`。源码 clone 不会自动创建这些安装副本。

## 4. 部署模式与 LIVE 安全边界（必须按真实代码理解）

以 `/srv/finfusion-api/finfusion/environment.py`、`/srv/finfusion-api/finfusion/main.py`、`/srv/finfusion-api/finfusion/infrastructure.py` 为准：

| 名称 | 当前真实状态 |
|---|---|
| LOCAL | 没有名为 LOCAL 的运行模式；本地模拟仅存在于测试替身，不是可用的离线生产启动模式 |
| SANDBOX_REMOTE | 没有这个配置枚举；远程测试使用 SANDBOX + Tunnel + 签名客户端 |
| SANDBOX | 默认环境，使用 Sandbox 的 HTTP、行情和事件端点；仍需要有效 Sandbox 凭据和外部服务 |
| LIVE | 存在；必须显式 FINFUSION_LIVE_ALLOWED=true，并满足环境/权限/风控等检查 |

**当前代码不是“远程 LIVE 一律禁止”。** loopback 限制的是服务器监听地址，Tunnel 仍允许远程访问；不能把 loopback 解释为远程实盘禁令。缺少显式 LIVE 允许会拒绝启动，环境目录和数据库不匹配也会拒绝；启动后全局交易开关默认关闭，节点、Tunnel、行情、事件和对账异常会限制新单/改单。

本次迁移不打开 LIVE，不改变任何门禁。如果接手后的版本新增远程 LIVE fail-closed/禁止远程 LIVE 规则，新 Codex **不得绕过、删除、弱化、伪造本地模式或心跳来规避**，应报告并保留。不得把用户的部署目标当成执行真实订单的授权。

## 5. Ubuntu 与现有安装路径的差异

目标是 Windows 10 + WSL2 Ubuntu，但已有发布脚本锁定 **Debian 12 amd64 + PostgreSQL 17 + LocalSystem 专用 FinfusionNode**。本次仅交接，没有把安装器改造成 Ubuntu 安装器。

新 Codex 必须先读取 `/etc/os-release`、检查 Python 3.11、systemd、PostgreSQL 版本和现有服务。不得在 Ubuntu 上直接运行 `/srv/finfusion-api/deploy/windows-node/linux/install.sh`：它要求构建 stage 目录、vendor、wheelhouse 和 Debian 精确包清单，普通 clone 不具备这些输入。

Ubuntu 下系统依赖提供方式、Python 3.11 安装副本、首次 PostgreSQL/Casdoor 初始化及节点/Tunnel 心跳服务仍需部署审查和验证。源代码可接手；不能承诺 clone 后一条命令上线。已有详细指南 `/srv/finfusion-api/docs/NEW_COMPUTER_DEPLOYMENT.md` 讲的是 Debian 专用节点，其系统安装命令不得误用于 Ubuntu。

## 6. 端口、反向代理与 systemd

- HTTP API：默认 `127.0.0.1:8080`，由 FINFUSION_BIND_HOST / FINFUSION_PORT 控制；禁止改成公网监听来绕过 Tunnel。
- WebSocket：同一个 8080 端口，路径 `/v1/events`，公网为 WSS；不是单独进程或端口。
- 存活 `/livez`；就绪 `/readyz`。存活不代表可交易；还要检查 readyz 的各健康字段和 effectiveTradeEnabled。
- Casdoor：8000；PostgreSQL 模板连接端口：5432；cloudflared 健康/metrics：`127.0.0.1:2000`；公网客户端使用 HTTPS 443。
- **Nginx 模板不存在**。当前采用 Cloudflare Tunnel，不需要凭空寻找 nginx.conf。本次不新增 Nginx 或另一套部署入口。
- systemd 模板目录：`/srv/finfusion-api/deploy/windows-node/linux/systemd/`；包含 finfusion、finfusion-vault、finfusion-node-default-off、finfusion-tunnel-health service/timer、casdoor、cloudflared。PostgreSQL unit 来自系统包。
- 模板安装目标 `/etc/systemd/system/`；Ubuntu 是否可直接使用须逐项检查用户、目录、依赖 unit、systemd 沙箱及绑定路径，不得直接启用尚未配置的服务。

## 7. Secret 注入：名称、位置和权限

**没有名为 BrokerSecretProvider 的类。** 实际是 `/srv/finfusion-api/finfusion/main.py` 的 `_secret_file` 加 `/srv/finfusion-api/deploy/windows-node/linux/bin/vault.py`，由 age Vault 解密到 `/run` 的受限文件，再注入 GatewayConfig。

用户在新服务器私密配置中重新提供以下字段；此处只列名称，不列秘密值：

```text
webullAppKey
webullAppSecret
databaseDsn
casdoorClientSecret
casdoorDataSourceName
tunnelToken
accountMasterKey
```

还需单独保管备份解密 identity；私有 Git 访问凭据由 Git 凭据管理器/部署密钥负责，不属于应用配置。真实 Account ID 经管理员登记，不填进仓库模板；用户程序私钥留在各自客户端。Casdoor Client ID、域名、backupRecipient 公钥和风险配置也需重新填写，但不能把它们误当成已在 Git 中配置完成。

应用读取的环境变量名（值为文件路径，不是明文秘密）：

```text
FINFUSION_WEBULL_APP_KEY_FILE
FINFUSION_WEBULL_APP_SECRET_FILE
FINFUSION_DATABASE_DSN_FILE
FINFUSION_ACCOUNT_KEY_FILE
FINFUSION_CASDOOR_CLIENT_SECRET_FILE
```

对应 Vault 字段：`webull_app_key`、`webull_app_secret`、`database_dsn`、`account_master_key`、`casdoor_client_secret`；共享节点字段为 `casdoor_data_source`、`tunnel_token`。SANDBOX 的 API 秘密目录为 `/run/finfusion/secrets/sandbox`，LIVE 为 `/run/finfusion/secrets/live`。目录必须归运行服务 UID 所有且 0700，秘密文件 0600，禁止链接；不得 chmod 777 或绕过检查。

配置模板位置：`/srv/finfusion-api/deploy/windows-node/config.example.json` 和 `/srv/finfusion-api/deploy/windows-node/linux/server.env.template`。后者仅是部分环境模板，必须核对 main.py 的所有必填项；安装后的 `/etc/finfusion/server.env` 由节点配置流程生成。首次 Casdoor 组织/应用/管理员初始化尚无全自动闭环，不能伪造 Client ID/Secret 让服务启动。

首次 accountMasterKey 应安全生成和托管；重配已有数据必须使用原值。不得随意轮换导致账户解密失败。任何已有生产数据恢复须另行授权和制定加密传输方案，本次不复制旧机数据。

## 8. 数据、日志与持久化

| 位置 | 内容与约束 |
|---|---|
| PostgreSQL `finfusion_sandbox` / `finfusion_live`，schema `finfusion` | 订单、请求幂等、nonce、用户/客户端/账户授权、审计；不是 SQLite |
| PostgreSQL `casdoor` | 身份服务数据 |
| `/var/lib/postgresql/17/main` | Debian 默认集群常见位置；Ubuntu 实际位置必须通过 `sudo -u postgres psql -Atc 'SHOW data_directory;'` 核实，不硬编码迁移 |
| `/var/lib/finfusion/webull_tokens/sandbox` 或 `/var/lib/finfusion/webull_tokens/live` | SDK 令牌，环境隔离，不复制、不入 Git |
| `/var/lib/finfusion/vault` | 加密秘密与节点 identity，不入 Git |
| `/var/lib/finfusion/casdoor`、`/etc/finfusion` | 身份服务运行配置及节点配置 |
| `/run/finfusion` | 重启后重建的秘密、节点状态和临时数据；不得手工伪造健康状态 |
| systemd journal | API 默认输出到 stderr/stdout，无固定应用日志文件；用 journalctl 查看 |
| `/var/log/journal` 或 `/run/log/journal` | 取决于系统 journald 持久化设置，需在目标机确认 |

本仓库生产持久化是 PostgreSQL；`MemoryOrderStore` 是测试设施，不能当服务器数据存储。不存在应迁移的 `orders.db`。旧 Windows `C:\ProgramData\Finfusion\node-host.log` 只是原宿主日志，不属于 Ubuntu 部署输入。

## 9. 新 Codex 的逐步 QA 和部署交接顺序

### 9.1 只读审查

在 WSL Ubuntu 执行：

```bash
cd /srv/finfusion-api
git status --short
git rev-parse HEAD
cat /etc/os-release
python3.11 --version
ps -p 1 -o comm=
systemctl --version
```

预期：SHA 与交接一致、工作区 clean、解释器为 3.11、PID 1 为 systemd。缺少任何前提时先报告，不自动改交易代码或升级依赖。

### 9.2 隔离开发测试（不启动券商服务）

Python 3.11 已由用户准备后：

```bash
cd /srv/finfusion-api
unset PYTHONPATH
export PYTHONNOUSERSITE=1
python3.11 -m venv /srv/finfusion-api/.venv
/srv/finfusion-api/.venv/bin/python -m pip install -r /srv/finfusion-api/requirements-dev.txt
/srv/finfusion-api/.venv/bin/python -m pytest -q
/srv/finfusion-api/.venv/bin/python /srv/finfusion-api/tools/verify_independence.py
/srv/finfusion-api/.venv/bin/python -m pip check
```

当前不提供 FINFUSION_TEST_DSN 时预期 37 passed、1 skipped。真实数据库测试只能用新建、可丢弃且名称以 `finfusion_test_` 开头的数据库，不连接生产库。已有 PostgreSQL 17 二进制时，可由普通非 root 部署用户运行下面工具，它会在 runtime 内建立独立临时 cluster、监听 loopback 并在测试后停止：

```bash
/srv/finfusion-api/.venv/bin/python /srv/finfusion-api/tools/test_with_postgres.py --bin-dir /usr/lib/postgresql/17/bin
```

预期 38 passed、0 skipped；确认退出成功与临时库已停止。以上 Ubuntu 命令是待新服务器执行的 QA，不代表本次已在 Ubuntu 验证。

### 9.3 受控部署与启动

仅在 Ubuntu 安装方案经审查、依赖/目录/服务用户/秘密/Casdoor/Tunnel/数据库全部准备好后，才使用以下 **现有运行副本**命令。若 `/opt/finfusion/bin/node-control` 不存在，说明尚未完成安装，不要把 clone 目录当运行副本。

```bash
sudo /opt/finfusion/bin/node-control start
sudo /opt/finfusion/bin/node-control doctor
sudo /opt/finfusion/bin/node-control status
```

模板内部实际 API 命令是 `/opt/finfusion/venv/bin/python -m finfusion.main`，由 systemd 以 finfusion 用户、`/opt/finfusion/current` 工作目录及 `/etc/finfusion/server.env` 启动。它会连接真实所选环境的 Webull，并非离线 smoke test；不得在缺少配置时随意前台启动第二个交易进程。

### 9.4 健康检查

```bash
curl --fail --show-error http://127.0.0.1:8080/livez
curl --show-error --include http://127.0.0.1:8080/readyz
sudo journalctl --no-pager -n 100 -u finfusion -u casdoor -u cloudflared
```

逐项确认 livez HTTP 成功、readyz 数据库/行情/订单事件/对账/节点/Tunnel 状态；交易关闭期间 effectiveTradeEnabled=false 是预期，不能仅以 livez 成功宣布部署完成。日志输出前脱敏。之后在远端程序验证签名查询、权限隔离与 WebSocket 断线补查；本次不给出或自动执行 LIVE 订单命令。

### 9.5 停止

```bash
sudo /opt/finfusion/bin/node-control deactivate
sudo /opt/finfusion/bin/node-control stop
```

先确认已有订单状况；deactivate/stop 不等于券商撤单。该 stop 同时停止节点的数据库、Casdoor、API、Tunnel 与 Vault，执行前确认目标节点无其他共用业务。

## 10. 回滚方法

源码回滚与运行数据恢复分开：先 deactivate，记录订单/请求状态并保留加密备份；停止节点，再决定代码/数据库恢复方案。不要删除或清空订单账本、幂等表来让旧版本启动，不得重发 UNKNOWN。

本次只改交接材料和忽略规则，不产生数据库 migration。若仅需查看迁移前源码，可在干净源码 checkout 中使用：

```bash
git -C /srv/finfusion-api switch --detach 13d1e64ce0ce61e515cc15ff8582a5a18bc19dc5
```

这只改变源码，**不升级或回滚 `/opt/finfusion` 安装副本**，也会使本次新增 AGENTS/交接文件不再出现在该 checkout。操作前先保存交接规则；不要在脏工作区执行 reset --hard。运行副本的版本切换、venv、配置与数据库兼容性需先审查，当前没有已验证的 Ubuntu 一键回滚流程。

恢复运行数据使用受控加密备份及原密钥，须明确授权覆盖目标数据。不得直接复制旧 Windows 数据库文件/WSL 磁盘到 Ubuntu，也不得把 Sandbox 备份恢复到 LIVE。恢复完成先对账、查询验证，交易保持关闭。

## 11. WSL2 特别事项

- Windows 10 的系统支持/更新资格需用户核实；不要因旧系统而降低 TLS、签名或安全门禁。网络与电源稳定、时间同步、自动休眠和重启行为均需验收。
- 遇到 WSL 安装、功能启用、管理员权限或 Windows 服务操作，**暂停并让用户执行**明确命令。首先给出的只读管理员检查命令可为 `wsl.exe --status` 和 `wsl.exe --list --verbose`；不得自行提权、注销发行版或修复用户现有磁盘。
- Ubuntu `/etc/wsl.conf` 的 systemd 配置及是否需重启 WSL，应根据实际版本核实。`wsl.exe --shutdown` 会影响所有运行中的发行版，不能自动执行。
- 将源码 clone 到 Linux 文件系统 `/srv/finfusion-api`；不要把 Windows `.venv` 搬到 Linux，也不要用共享目录存放明文秘密。文件权限必须在 Linux 实测。
- 标准用户 Ubuntu 与旧安装器 LocalSystem 的 FinfusionNode 是不同实例；不得混用目录、账户、宿主控制命令或假定自动启动一致。
- Windows 重启后的 WSL 启动和服务自动恢复尚待 Ubuntu 目标实测；systemd enable 本身不证明 Windows 登录前服务已在线。
- Cloudflare Tunnel 必须在与 API 相同的 Linux 网络上下文访问 loopback；不得因为 Windows→WSL 转发问题改成 0.0.0.0。

## 12. 禁止复制与本次审计证据

禁止从旧电脑复制到仓库或当成部署输入：真实 .env、所有券商/身份/TLS/Windows 凭据、Account ID 清单、令牌/cache/cookie、数据库、日志、runtime、用户目录、.venv、build/dist、Nuitka 制品、Windows 安装包、旧 WSL 磁盘、Git credential store。模板和明确审核的源码才走私有 Git。正式运行数据迁移需要另外的加密备份恢复任务，本次不包含。

本次审计范围、测试及 Git 状态见 `/srv/finfusion-api/docs/server-migration-audit.md`。模式扫描与人工核对只能说明未发现明显真实秘密，不保证任意未来提交没有泄漏；新 Codex 提交前必须重做暂存文件及相关历史检查。
