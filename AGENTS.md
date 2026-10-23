# Finfusion API：服务器与客户端开发工作规则

本仓库是从 FastOrder 来源整理的独立 Finfusion API 项目，不是旧 FastOrder 桌面项目。当前任务是私有 Git → Windows 10 + WSL2 Ubuntu 的部署交接。先阅读本文件，再阅读 `docs/CURRENT-STATUS.md` 与 `docs/DEVELOPMENT-HANDOFF.md`；旧迁移背景见 `docs/server-deployment-handoff.md`；按实际 clone 根目录给出这些文件的完整路径。

## 工作方式

- 先审查再修改：核实 repo root、branch、HEAD、remote、private 可见性和工作区状态，再读源码与现有模板。
- 默认最小改动，仅处理明确授权的迁移/部署范围；不得为了部署进行无关重构。
- 所有面向用户的文件和操作路径必须写完整绝对路径。执行前确认 Linux 与 Windows 的路径归属，不假设旧机器盘符或用户目录存在。
- QA 必须包含逐步操作、预期结果、实际结果和失败时的停止条件；不能只给摘要表。
- 不覆盖用户未提交内容。未经明确授权不得 force push、重写 Git 历史、重置数据库或删除节点。

## 不可改变的边界

- 不修改 TradingService 业务语义、Broker Gateway 行为、Risk、Ledger/幂等语义、UNKNOWN 不重发规则或 SELL 持仓检查。
- `server_admin/` 视为 frozen UI，不得自行修改；不得自动升级 Broker SDK 或主要生产依赖、重写锁文件。
- 不得自动执行真实 LIVE 订单；任何实盘验收需要用户另行明确账户、股票、方向、数量、价格边界和时段。
- 不得降低现有安全边界：签名/防重放、权限、环境隔离、loopback 监听、密钥权限、启动默认交易关闭、节点/Tunnel/行情/事件/对账门禁均需保留。
- 若接手版本存在“远程 LIVE fail-closed/禁止远程 LIVE”规则，不得绕过、删除、弱化或以配置伪装本地来规避。先报告实际代码状态，不凭其他项目文档推定本仓库规则。
- 当前 Ubuntu 目标尚未端到端验收；Debian 专用节点脚本不是 Ubuntu 安装器。不得为让健康检查变绿而伪造节点心跳或关闭检查。

## 秘密、数据和 Git

- 默认 remote 必须确认是 PRIVATE；无法确认就停止推送并说明登录/权限步骤。clone 成功本身不能证明 private。2026-10-23 用户已明确批准本次将脱敏源码与文档推送当前公开的 Lodavian/Finfusion-API；该例外仅用于本次整理，不能用于公开任何秘密或运行数据。
- 不得将真实 .env、App Key/Secret、Account ID、Access Token、Cookie、API Token、TLS 私钥、Windows Credential、券商 token/cache 写入 Git。
- 不提交 .venv、build、dist、安装包、Nuitka 制品、缓存、日志、数据库、runtime 或个人机器数据。模板只允许无真实值的明确占位符。
- `.gitignore` 不会清除已跟踪文件或历史：提交前同时检查暂存区和相关历史；审计日志只能输出路径/提交/问题类别，不打印秘密值。
- 一旦发现真实秘密进入历史，立即停止 push，报告文件和 commit，要求 rotate/purge；不得擅自重写历史后声称问题解决。
- 通过系统秘密注入或项目已有 Vault/受限文件机制配置新节点，不从旧机复制秘密目录、旧 token/cache 或数据库。

## 权限和操作

- 遇到 Windows 管理员权限步骤，必须暂停该步骤，给用户明确的管理员 PowerShell 命令、影响及检查方式，待用户执行/反馈后继续；不得自行安装服务、启用 Windows 功能、导入/注销系统账户 WSL 或提权绕过。
- Linux 系统变更也必须先核对目标和当前授权。部署前保留回滚路径；涉及已有生产数据的恢复/覆盖必须单独确认。
- 不把 `git pull` 当成服务升级，不把 Git 源码当成运行数据库备份。迁移工作不创建正式 `v1.0.0` release tag。
- 完成时报告精确 SHA、测试证据、push 结果和 clean 状态；区分模拟验证、真实数据库测试、目标服务器验收和实盘验收。
