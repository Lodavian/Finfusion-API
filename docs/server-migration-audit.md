# 服务器迁移交接审计记录

日期：2026-10-04（Asia/Hong_Kong）。范围为 Finfusion API 私有 Git 源码交接，不是 Ubuntu 部署完成报告。

## Git 起点和可见性

- 根目录：`E:\Finfusion API`。
- 分支：`main`。
- 起始 HEAD：`13d1e64ce0ce61e515cc15ff8582a5a18bc19dc5`。
- remote：`origin` → `https://github.com/Lodavian/Finfusion-API.git`。
- 初始工作区 clean；fetch 后未发现远端新增提交或已有 release tag。
- 使用已有 Git 凭据管理器提供的身份在内存中请求 GitHub repository API，返回 `private=true` / `visibility=private`。未打印、落盘或提交身份凭据。匿名请求的 404 没有被当成 private 证明。

## 秘密及制品检查

检查本地所有可达历史，包含 main/origin/main 的 2 个提交：

- `13d1e64ce0ce61e515cc15ff8582a5a18bc19dc5`
- `999176defa8ebdb146c972cbba35954508cb79a9`

对 100 个不同文件对象检查私钥、GitHub token、JWT、age identity、云访问键、数据库连接密码模式；检查各提交中的 .env、数据库/日志、运行目录、安装包及构建制品路径。凭据字段候选经源码核对，为无真实值的配置模板或模拟测试数据，未发现明显真实秘密；未发现被跟踪的禁止制品。不涉及服务器不可见的 GitHub 缓存、已删除的不可达对象或第三方 fork，因此不声称这是所有潜在泄漏的绝对证明。

旧验证报告包含非秘密的开发机主机名，已从当前报告移除；它不是认证信息，不涉及 rotate。没有改写历史、删除分支或 force push。将来如发现真实秘密，必须立即停止推送并由用户处理 rotate / purge。

## 本次允许改动

- `/AGENTS.md`：先审查、最小修改、绝对路径、逐步 QA、禁止 LIVE 自动订单和秘密入 Git、冻结 UI/依赖、Windows 提权步骤交给用户。
- `/docs/server-deployment-handoff.md`：新服务器交接，明确 Ubuntu 与现有 Debian 节点差异及真实模式/安全门禁。
- `/docs/server-migration-audit.md`：本记录。
- `/.gitignore`：补齐 .env 变体、数据库附属文件、SDK 缓存、发布和原生编译制品规则；保留 .env.example 和已有精确模板。
- `/docs/verification.json`：仅移除本机主机名，不改写原测试日期或结果。
- `/README.md`：新增正式交接入口。

上述文件路径相对于审计根目录；实际 Windows 完整路径为 `E:\Finfusion API` 加对应路径，新服务器完整路径为 `/srv/finfusion-api` 加对应路径。没有改动 TradingService、Gateway、Risk、持久化/幂等、UNKNOWN、SELL 持仓检查、frozen UI、Broker SDK 或生产依赖。

## 实际验证步骤与结果

1. 用 `git check-ignore --no-index` 验证 18 个路径：秘密/制品按预期忽略，`.env.example`、config.example.json、server.env.template 按预期保留。
2. 执行 `E:\Finfusion API\run-tests.ps1`：37 passed、1 skipped（未设置专用 PostgreSQL DSN），独立性检查 69 个文件、0 错误，pip check 无冲突。
3. 执行项目临时 PostgreSQL 测试工具，使用项目内 PostgreSQL 17.11 二进制与全新回环地址 cluster：38 passed、0 skipped，覆盖真实迁移、持久化、防重放、环境绑定及重启恢复；退出成功，数据库已停止。没有调用 Webull。
4. 检查交接 Markdown 的仓库链接和 Bash 示例语法；仅做语法检查，不在本机执行 Linux 部署命令。
5. 提交前检查 `git diff --check` 和暂存文件范围，确认没有新增秘密或运行制品、没有业务/依赖改动。推送结果和最终精确提交 SHA 以交接消息和 GitHub 记录为准。

尚未验证：Windows 10 + WSL2 Ubuntu 首次安装、Ubuntu 服务启动/自动恢复、真实 Casdoor/Tunnel/Webull Sandbox、异机备份恢复和 LIVE。文档不授权新 Codex 为通过上述检查而绕过门禁。

本次不创建正式 v1.0.0 release，也不创建额外 baseline tag；以明确提交 SHA 交接。
