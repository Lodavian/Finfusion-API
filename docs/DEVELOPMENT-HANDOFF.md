# 继续开发与部署交接

更新时间：2026-10-23（Asia/Shanghai）。基线提交 `f581d3b7fc7ad42dbe07c234b48771c0fda778d8`。服务器与 Windows 客户端按不同 Python 环境开发；原工作树及运行 release 保留，本次使用独立汇总目录。

## 先读哪些文件

1. 根目录 `AGENTS.md` 和 `docs/CURRENT-STATUS.md`。
2. 服务器协议 `docs/API.md`、`docs/openapi.json`、`docs/MARKET.md`。
3. 客户端 `windows-client/README.md`、`windows-client/docs/DELIVERY-1.0.md`、`windows-client/docs/ACCEPTANCE-1.0.md`。
4. 运维 `docs/SERVER-AUTOSTART-2026-10-13.md`、`docs/SERVER-HOST-RUNBOOK-2026-10-12.md` 和 `ops/windows-host/README.md`；这些历史记录中的状态以 CURRENT-STATUS 为准。
5. 旧迁移背景 `docs/server-deployment-handoff.md`；它记录的是迁入前状态。

## 源码来源和整合原则

- 服务器：已有 `finfusion-server-1.0` 工作树；另保留原 workspace 中未提交的基础设施测试修正。
- 管理界面：用户已批准的独立管理 UI，线上通过单独静态目录提供；不将旧 release 中的 frozen UI 误当成最新界面。
- 客户端：原 Windows 客户端工程整体源码、锁文件、素材和许可证，迁入 `windows-client/`；移除重复服务器副本、QA 参考截图和本机下载产物。
- 运维：补入已部署的最新 `health.py`、缺失的部署/恢复脚本、systemd 备份与健康检查模板及数据库 helper。
- 路径调整仅用于本仓库布局：管理预览读取根 `server_admin`；客户端管理入口读取相邻 `deployment-tools`；Windows 验收 helper 读取 `windows-client`；候选测试使用当前解释器及仓库内 helper。
- 历史部署工具含已有机器的服务名/目录，属于运维源码档案，不是通用的一键安装器。不要从旧机器复制秘密、令牌、数据库或整个运行目录。

## 验证步骤、预期与停止条件

### Windows 客户端

在 clone 的 `windows-client` 目录，以 Python 3.12 x64 执行 `setup-dev.ps1` 后运行 `run-tests.ps1 -q`。预期 59 项测试通过，独立性检查无错误。实际本次使用原有已安装依赖的 Python 对汇总目录执行，59 passed。测试失败时停止打包，不用真实订单替代测试。

### 服务器完整数据库测试

需要 Linux、Python 3.11 开发依赖、PostgreSQL 17 binaries、`ip`、`unshare` 和独立网络命名空间权限。由管理员在已审查的 clone 根目录运行 `<SERVER_PYTHON> ops/test_candidate.py`。脚本建立 `/run` 下的临时 cluster，仅本地回环、合成数据库/券商，最终停止并清理临时 cluster；不会读取生产凭据、使用生产 DSN 或调用真实券商。不要通过放宽网络隔离让失败的测试通过。

实际：64 passed、0 skipped，证据本地 `build/server-1.0-pg.xml`。普通 `pytest` 未提供测试 DSN 时不等于这项完整验收；`tests/test_live_database.py` 要求隔离 LIVE 测试 DSN。`tools/live_db_acceptance/acceptance.py run` 是另一条读取真实快照的流程，不是这项纯合成测试命令。

### 宿主工具与独立性

运行 `<SERVER_PYTHON> -m pytest -q ops/windows-host`，预期/实际 21 passed。根 `tools/verify_independence.py` 检查服务器运行源码和构建输入；历史 `deployment-tools` 档案单独审阅，`windows-client` 由自身 checker 检查。`ops/verify_restore.py` 明确加载已安装 release 进行隔离恢复，不是运行时对旧项目的依赖。两侧检查实际均通过；没有删除任何运行时隔离检查。

### 现场验收

先检查服务活跃、公网 `/livez`、签名 `/v1/info`、只读权限和 `/readyz` 中真实门禁。预期交易关闭是安全状态，不以 HTTP 200 或服务 active 代替可交易证明。失败时记录实际错误，不开启门禁、不修改健康字段、不重试未知订单。本次没有重启宿主或服务。

## 后续顺序

1. 在干净 Windows 测试机完成安装、升级、卸载及 DPAPI/数据保留，不能把服务器宿主当一次性测试机。
2. 新客户端独立生成密钥、登记公钥与读取权限；不要共享现有 DPAPI 私钥或测试身份。
3. 按宿主 runbook 完成管理员设置、登录前冷启动和独立电脑公网证据，完成跨日稳定性观察。
4. 明确异机加密备份、恢复介质、外部告警及代码签名安排。
5. 真实订单必须重新获得具体账户、股票、方向、数量、价格边界和时段授权。历史零成交限制和过期授权不能延用。

Git 更新只更新源码，不自动部署，不恢复数据库，也不启用 LIVE 交易。
