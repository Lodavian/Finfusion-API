# Finfusion API

面向程序调用的 Webull HK 机构交易服务器。用户以 P-256 私钥签名调用 HTTPS API，服务器负责账户授权、风控、订单去重、券商访问、持久化和状态回传。管理员通过 Casdoor 登录管理台。

本目录是独立项目，不读取原有项目目录。第一版只维护 Windows x64 + WSL2 Debian 12 的部署路线。Windows 原生 Python 环境用于开发和模拟测试；正式入口在 Linux 中运行。

当前电脑仅用于开发、构建和自动化测试；实际服务将部署到另一台 Windows 电脑。当前阶段不安装服务、不配置 Tunnel、不修复本机 WSL，也不进行真实券商联调。本机 WSL 状态不影响开发验收。

## 当前交付边界

- 已实现程序客户端登记/批准/禁用/公钥轮换与查询、交易、撤单权限。
- 已实现账户、持仓、美元购买力、下单、改单、撤单、幂等查询与 WebSocket 事件接口。
- 保留 PostgreSQL 持久化、管理员控制、节点健康门禁、加密备份及 Windows 节点部署源码。
- 默认 SANDBOX；LIVE 需要独立节点、数据库、密钥及显式配置，启动后交易总开关默认关闭。
- 本轮未安装系统服务、连接 Webull 或提交订单；真实 PostgreSQL、WSL2、Sandbox 与实盘部署验收见 `docs/DELIVERY.md`。

## 开发与验证

系统前提：Python 3.11；编译 Windows 节点还需要 .NET 8 SDK 和对应构建工具。项目依赖安装在本目录，不使用旧项目虚拟环境。

```powershell
Set-Location 'E:\Finfusion API'
.\setup-dev.ps1
.\run-tests.ps1
```

`run-tests.ps1` 清除旧 PYTHONPATH、运行模拟测试、检查项目独立性和 Python 依赖。它不会启动交易服务。真实 PostgreSQL 测试需显式设置指向全新 `finfusion_test_*` 数据库的 `FINFUSION_TEST_DSN`，未配置时该测试跳过。

也可使用项目内的临时数据库测试工具：它使用指定的 PostgreSQL 二进制文件，自动创建全新测试库，只监听回环地址，并在测试结束后停止数据库，不安装服务。已使用 [EDB Windows 二进制包](https://www.enterprisedb.com/download-postgresql-binaries) 中的 PostgreSQL 17.11 运行全部 38 项测试，全部通过。

```powershell
.\.venv\Scripts\python.exe tools\test_with_postgres.py --bin-dir 'build\tool-cache\postgresql-17.11-3\pgsql\bin'
```

二进制包及临时数据库不进入 Git；测试日志保存在 `runtime/postgres-test-*`。

## 程序接入流程

1. 用户在自己的电脑生成密钥：

   ```powershell
   .\.venv\Scripts\python.exe -m client_sdk.keygen --directory runtime\my-client
   ```

2. 只把 `public.pem` 提供给管理员；`private.pem` 留在用户电脑。
3. 管理员创建用户，登记机构凭据可访问的账户，并绑定给该用户。
4. 管理员在“程序客户端”登记公钥，保存返回的 `clientId`，再批准客户端及相应权限。
5. 用户使用 `clientId` 和自己的私钥调用 API。首次先查询账户、持仓与购买力，确认权限。

   ```powershell
   .\.venv\Scripts\python.exe -m examples.query_accounts --url https://api.example.com --client-id CLIENT_ID --private-key runtime\my-client\private.pem
   ```

下单接口不要求用户先登录网页或手工选择股票。服务器自动准备行情；行情未就绪时拒绝发送订单。客户端不会自动重发交易命令。

## 文档与目录

| 位置 | 用途 |
|---|---|
| `finfusion/` | API、认证、账户权限、交易服务、Webull 适配及 PostgreSQL |
| `finfusion_common/` | 项目内共享的状态、脱敏和数值工具 |
| `server_admin/` | 管理员网页 |
| `client_sdk/`、`examples/` | Python 签名客户端、密钥生成和只读示例 |
| `tests/` | 模拟与可选 PostgreSQL 集成测试 |
| `deploy/windows-node/` | 专用 WSL2 节点、Windows 服务、Vault 和运维脚本 |
| `packaging/` | 源码构建脚本、依赖锁定及许可证 |
| `docs/API.md`、`docs/openapi.json` | 签名规范、接口契约与恢复行为 |
| `docs/DEPLOYMENT.md` | 环境隔离、部署、备份和验收步骤 |
| `docs/source-manifest.json` | 复制来源与原文件 SHA-256 |

生成或更新 OpenAPI：`.\.venv\Scripts\python.exe tools\build_openapi.py`。

## 交易约束

仅美股整股、BUY/SELL、MARKET/LIMIT、DAY、CORE，不做空。一个 Webull 账户仅分配给一个用户，用户可拥有多个账户和客户端。单账户交易串行、券商请求共享限流。未知结果进入对账并阻止该账户的新单和改单；查询及有权限的撤单保留。

每个环境运行一个交易进程；数据库会拒绝第二个交易进程。关闭交易开关与禁用用户不同：前者保留查询和撤单，后者撤销访问权限。
