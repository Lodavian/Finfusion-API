# 正式 LIVE 数据库隔离验收工具

本工具仅适用于已核对的 WSL2 Ubuntu 部署：PostgreSQL 17.11、LIVE 只读运行版本 `f581d3b-market-20261009-2`。源码及部署覆盖层文档/测试必须按 manifest 哈希复制到独立工作目录，不修改原仓库或正式 release。当前完整验收目录为 `/opt/finfusion-acceptance/live-db`。

运行命令（WSL root，仅备份读取和临时集群管理）：

```powershell
wsl -d Ubuntu -u root -- /home/<LINUX_USER>/worktrees/finfusion-client-market/.venv/bin/python /opt/finfusion-acceptance/live-db/tools/live_db_acceptance/acceptance.py run
```

固定使用既有测试虚拟环境，不向生产环境安装 pytest；生产 Python 仅用于 PostgreSQL 身份下的只读快照采集。完整独立源代码已归入验收目录，无 editable 安装或 PYTHONPATH 注入。

## 行为与保护

- 校验运行 release、部署覆盖层及完整 Python 源码哈希、生产健康状态和交易关闭。
- 以 PostgreSQL 身份在只读 REPEATABLE READ 事务中导出快照，pg_dump 使用相同 snapshot。采集 LIVE 和 Casdoor 表行数/摘要、结构、索引、约束和序列；身份关联核对不一致即停止。
- 以现有服务 age identity 的公钥加密备份。备份含恢复验证所需账户加密主密钥及仅作参考的 server.env；不含券商 App Key、App Secret 或 token。不要将密钥或备份复制到 Git。
- 正式库不做 migrate、DDL、DML；不调用 node-restore、启用门禁、重启生产服务或调用生产交易 API。
- 集成测试及恢复都在新网络命名空间内执行，无外网接口；两个独立临时 PostgreSQL 集群仅使用唯一 Unix socket 和随机角色密码。
- LIVE 合成库验证真实数据库与模拟券商；恢复库验证真实生产快照。restore 使用 no-owner/no-acl，不导入生产角色密码。
- 每次恢复连接核对随机 socket、目标标记、数据库名称及服务端 data_directory；拒绝正式数据库目标。
- 测试退出后停止临时 PostgreSQL，删除 /run 中明文备份、密钥、临时数据目录。每次结果及加密备份保留在 `/var/lib/finfusion/acceptance/live-db/<runId>`，仅 root 可读。

## 结果与边界

`result.json` 总体 PASS 需测试全部通过、恢复精确核对、重启持久化、密文解密、迁移不改记录、错误目标/错误密钥/损坏备份拒绝及生产前后状态一致。`tests.xml` 为真实 PostgreSQL 回归证据。

早期失败尝试单独保留，不覆盖历史记录；诊断日志为受限本机文件，不能直接公开。报告仅含计数、哈希及状态。出现失败立即停止，不修复生产。

这是本机隔离恢复，不是生产覆盖恢复或异机灾备。加密备份依赖现有 age identity；该 identity 也丢失时无法解密，本轮没有验证离线密钥保管和整机丢失恢复。两数据库各自一致性快照，额外核对身份关联，不声称跨数据库原子快照。序列若在采集过程中变化则停止并重取。
