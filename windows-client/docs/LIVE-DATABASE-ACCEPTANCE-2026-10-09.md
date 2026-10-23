# 正式 LIVE 数据库集成测试及隔离恢复验收

最终验收时间：2026-10-09 22:53–22:54（Asia/Shanghai）。总体结果：**PASS**。

基准：`/opt/finfusion/releases/f581d3b-market-20261009-2`，Git 基线 `f581d3b7fc7ad42dbe07c234b48771c0fda778d8`，PostgreSQL 17.11，Python 3.11.17。10 个覆盖层文件、22 个已部署 Python 源码文件已核对哈希。没有升级依赖、改动原服务端业务代码或推送代码。

## 实际执行与证据

| 步骤 | 预期及实际结果 | 失败停止条件 |
|---|---|---|
| 生产前置检查 | LIVE 运行版本正确；Finfusion、Casdoor、nginx、Tunnel 服务 active；数据库健康，交易有效开关 false | 版本/哈希不符、服务异常、交易已启用则停止 |
| 正式数据快照 | 以 PostgreSQL 用户在只读 REPEATABLE READ 事务内导出快照；pg_dump 使用相同 snapshot，两个数据库分别采集，序列未发生变化 | 来源非 LIVE、事务非只读、序列变动、身份关联不一致则停止 |
| 加密备份 | LIVE 与 Casdoor dump、恢复核对基准、参考配置和账户主密钥经 age 加密；恢复从加密文件重新解密，不复用原明文 dump | 解密/成员白名单验证失败则不进入恢复 |
| 两个隔离集群 | 新网络命名空间仅 loopback，独立 Unix socket/随机角色与密码；集成库和恢复库使用不同 cluster | 可见外网接口、目标路径或数据库标记异常则停止 |
| 真实 PostgreSQL 回归 | **54 passed，0 failed，0 errors，0 skipped**；原 PostgreSQL 测试副本改为 LIVE 绑定，新增三个 LIVE 场景；券商完全模拟 | 任一测试失败则不继续恢复 |
| Finfusion 精确恢复 | **11 张表、101 行**，表结构、列/默认值、约束、索引、各表摘要、序列一致 | 任何结构/摘要/序列不一致则停止 |
| Casdoor 精确恢复 | **44 张表、239 行**，结构、数据摘要及序列一致；1 名 Finfusion 用户与 Casdoor 关联核对通过 | 关联不一致则重新取样，不修改生产 |
| 重启及迁移 | 恢复 PostgreSQL 重启后再核对，两库仍完全一致；恢复库重复迁移及 LIVE 绑定未改变原记录 | 重启丢记录、迁移改记录或环境不符则停止 |
| 账户密文 | 受限私密进程中成功解密 **2 个账户**；不输出账户 ID 或金额 | 任一密文解密失败则停止 |
| 负向恢复 | 错误 age identity、篡改加密备份均解密失败；正式目录和 finfusion_live 恢复目标均被拒绝 | 不允许忽略失败继续导入 |
| 生产后置及清理 | 生产进程 PID、重启次数、健康布尔值、节点状态文件与权限摘要前后一致；两临时 PostgreSQL 已停止，/run 明文临时目录已清除 | 生产变化或残留集群则记录失败，不自动修复生产 |

## LIVE 合成数据库验证内容

使用真实 PostgreSQL 及 LIVE 环境标记，合成用户、账户和订单，模拟券商；不是 SANDBOX 验收，也不是对真实券商下单。

- 空库及重复迁移、LIVE 环境绑定、拒绝 SANDBOX 跨环境绑定、数据库 leader lock。
- 用户、公钥、读/交易/撤单权限、账户归属与密文持久化。
- 并发重复请求仅调用一次模拟 place，修改数量后的幂等冲突被拒绝。
- 下单、改单、撤单的原请求编号在关闭连接、重新打开 Store 后仍能查询。
- 防重放记录在重开连接后继续拒绝重复 nonce；启动读取控制时交易默认关闭。
- UNKNOWN 持久化，重开 Store 后对账仅调用模拟 query，未新增模拟 place。

生产快照订单为空，本轮没有为了填充数据制造真实订单。真实未确认订单恢复依据来自 LIVE 合成测试，不宣称已验证真实券商成交回传或实盘恢复。

## 精确路径

完整独立验收代码：`/opt/finfusion-acceptance/live-db`。

最终验收材料：`/var/lib/finfusion/acceptance/live-db/20261009T145334Z-a70890bd`。

- `result.json`：最终结果及计数。
- `tests.xml`：54 项测试的 JUnit 证据。
- `release-check.json`：当前部署与验收来源哈希。
- `health-before.json`、`health-after.json`、`health-final.json`：生产状态对比。
- `negative-backup-tests.json`：错误密钥和损坏备份拒绝证据。
- `live-db-backup.age`、`backup-manifest.json`：加密备份及校验清单。

加密备份 SHA256：`86a97df926ec8a35e337df3bade8a3d5b065f8cc83ac95ff36134918ead01f51`。

备份及私密日志留在 Linux 受限目录，未复制到 Windows、Git 或公开仓库。临时角色与生产角色不同，恢复使用 `--no-owner --no-acl`，没有恢复生产角色密码。数据库所有权和 ACL 特意不复制；应用用户/客户端权限按原表记录精确恢复。

## 重复验收

```powershell
wsl -d Ubuntu -u root -- /home/<LINUX_USER>/worktrees/finfusion-client-market/.venv/bin/python /opt/finfusion-acceptance/live-db/tools/live_db_acceptance/acceptance.py run
```

每次使用新 runId、新临时集群和新加密备份；不会覆盖历史证据或正式库。工具说明见 `D:\Finfusion Client\tools\live_db_acceptance\README.md`。

准备阶段曾遇到 PostgreSQL 用户无法访问测试虚拟环境、网络命名空间的 sysfs 视图和旧 OpenAPI 文档三个验收工具问题；修正后完成两次全流程 PASS，早期失败记录保留，不计入最终通过结果。没有降低安全约束或修改生产来使测试通过。

## 边界及待办

- 生产库只读；没有调用 node-restore、停止生产服务、覆盖正式库、启用任何交易开关或发送真实交易。
- 当前全局、节点及有效交易开关仍关闭，readiness 503 为预期。真实券商调用次数 0。
- 原服务器工作区仍保留用户已有 `tests/test_server_infrastructure.py` 修改，行情工作区已有改动未被重置；没有 commit/push。
- 本次为本机数据库隔离恢复，不包含生产覆盖恢复、Casdoor 应用启动后的完整登录流程、异机灾备、离线密钥保管或整机丢失恢复。
- 两库分别使用一致性快照并核对身份关系，不声称跨数据库原子快照。加密备份依赖现有 age identity，需在后续灾备工作中单独验收离线密钥保管。
