# Finfusion：服务器与 Windows 客户端

当前开发版本：服务器 **1.0.0-rc1**、客户端 **1.0.0-rc1**。2026-10-23 汇总本机已开发、部署和验证的成果，保留原仓库历史。当前生产为 **LIVE READ_ONLY**，不代表已经通过真实交易验收。

先读 [最新项目状态](docs/CURRENT-STATUS.md)、[继续开发与部署交接](docs/DEVELOPMENT-HANDOFF.md) 和 [工作规则](AGENTS.md)。2026-10-04 的部署交接与旧 README 作为历史保留，不能代替最新状态。

## 仓库目录

| 路径 | 内容 |
|---|---|
| `finfusion/`、`finfusion_common/` | Linux 服务器、签名鉴权、权限、风控、PostgreSQL、券商网关 |
| `server_admin/` | 已获用户授权的管理界面；通过 Casdoor 登录 |
| `windows-client/` | 独立 Windows 客户端源码、UI、依赖锁定、许可证、构建及验收脚本 |
| `ops/` | 本机备份、健康检查、候选部署/恢复验证及 Windows 宿主工具 |
| `deployment-tools/` | 已有身份初始化与正式部署工具；包含站点路径，执行前必须审查 |
| `management-preview/` | 仅模拟数据的只读管理界面预览，不转发生产 API |
| `tools/live_db_acceptance/` | 数据库验收工具；其 `run` 会读取生产快照，需另行安排 |
| `tests/`、`docs/` | 服务器测试、协议、项目状态、历史交接和验收边界 |

## 开发入口

服务器使用 Python 3.11，依赖见根目录 `requirements-dev.txt`；不要使用 `windows-client` 的依赖环境启动服务器。根目录 `pytest.ini` 只收集服务器测试。完整隔离数据库测试入口是 `ops/test_candidate.py`，步骤及前置条件见交接文档。

Windows 客户端使用 Python 3.12 x64。在 PowerShell 切换到 clone 中的 `windows-client` 目录，再执行 `setup-dev.ps1`、`run.ps1` 或 `run-tests.ps1 -q`。运行目录下不需要服务器包或券商 SDK。构建入口为 `build-windows.ps1`、`build-installer.ps1`。

编译器、WebView2 完整离线运行时、ISO、EXE/ZIP、虚拟环境、数据库与真实配置不进入 Git。客户端打包前按 `windows-client/BUILDING.md` 准备本机工具；源码仓库本身不是可直接安装的软件包。

## 本次验证

- 客户端：59 passed；客户端独立性：16 个 Python 文件，0 错误。
- 服务器：临时 PostgreSQL、LIVE 合成数据、无外网隔离，64 passed，0 skipped。
- 宿主工具：21 passed；服务器独立性：103 个受检文件，0 错误。
- 核对线上核心源码与本次服务器源码一致。服务活跃、公网存活 HTTP 200；全局和有效交易开关均关闭。完整只读探测结果见最新状态。

真实订单、干净 VM 安装生命周期、独立电脑身份、登录前冷启动及跨日稳定性仍需单独验收。没有因上传仓库而升级生产服务、打开交易或迁移数据库。
