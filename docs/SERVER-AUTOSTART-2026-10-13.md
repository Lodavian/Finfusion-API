# 服务器自动启动与长期运行：2026-10-13 补充

合格目标：通电、启动 Windows 后，无需人工登录或打开终端，Ubuntu、PostgreSQL、Casdoor、正式 API 与 Tunnel 自动启动并持续运行。异常有可核查记录，恢复后查询原订单/请求，交易开关保持关闭，完成时间与对账检查后由管理员决定授权。该目标必须由冷启动和独立电脑的公网证据证明。

## 今天发现并修复

1. `/run/finfusion` 是重启即丢失的目录。两个启动 unit 使用其作为 ReadWritePaths，却没有在构造 systemd 隔离命名空间之前创建；实际报 226/NAMESPACE。已安装 `/etc/tmpfiles.d/finfusion-runtime.conf`，开机创建 root:finfusion、0750 的共享父目录，两个 unit 显式依赖 tmpfiles setup。已在隔离文件系统测试创建两次与权限/属主，PASS。
2. Tunnel 原 `Wants=finfusion-connectivity.service` 会拉起旧的无券商验证服务，它与正式服务 Conflicts，导致正式服务被停止。最初尝试的空值 drop-in 无法移除 systemd 依赖，已撤销该自建 drop-in，并只改 Tunnel 原 unit 的 Wants/After 依赖行；其 Service 段没有改变。实际加载的 Wants 已核对为 network-online.target 与 finfusion.service，不再包含旧验证服务。
3. Windows 保活任务已配置 Boot+Logon、Password，但本次状态为 Ready，最新 LastTaskResult=1，尚未持续运行。这项必须在管理员窗口启动、验证任务身份/凭据；不能把 Linux 修复当成 Windows 无人登录验收。
4. 原管理员脚本读 Windows localhost:8081，遇到 WSL 转发或验证代理会得到错误来源。已改为在同用户 Ubuntu 内检查 LIVE 正式 unit、正式 MainPID 对应的监听端口以及直接 /readyz JSON；要求两个交易开关是布尔 false，不能用缺字段、数字0、验证服务或任意代理响应通过。冷启动时最多30秒只读等待，不启动交易、不改门禁。实际证明已返回 offConfirmed=true；HTTP503在交易关闭时可以符合该证明。

Linux 变更前证据、配置副本、哈希和结果位于 `/var/lib/finfusion/acceptance/host-startup/20261013T080432315954Z`。没有改券商 SDK、交易代码、环境绑定或生产数据库；没有执行订单。仅恢复原正式只读服务的启动机制。修复工具源码：`D:\Finfusion Client\ops\windows-host\repair_linux_startup.py`。

## 实际结果与边界

- 本次宿主工具自动化 **21 passed**；tmpfiles 隔离重复创建/权限测试 PASS；PowerShell语法检查通过。
- 正式 service 可启动，密钥解封和默认关闭门禁 active；直接检查确认 LIVE、端口8080属于正式进程、全局与有效交易均关闭。
- 重新只读客户端探测期间，部分账户查询通过，随后行情及后续接口出现502/530；不能记完整公网联调PASS。证据 `D:\Finfusion Client\build\host-acceptance\readonly-integration-degraded-2026-10-13.json`。需保活稳定后重新测，不通过开启交易或重新发单来验证。
- Windows保活任务未保持Running，管理员电源/更新/校时尚未应用；Windows冷启动、登录前公网访问、停电、来电恢复、跨日稳定性均仍待验收。没有自动重启Windows、终止WSL或拔电。

## 当前下一步

在同一 Windows Ubuntu 所属账号的管理员 PowerShell 中执行：

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned -Force
& 'D:\Finfusion Client\ops\windows-host\apply-host-policy.ps1'
Get-ScheduledTask -TaskName 'FastOrder-WSL-KeepAlive' | Select-Object TaskName,State
```

更新后的脚本先检查既有 Password 保活任务；未运行则由该管理员进程调用 Start-ScheduledTask，5秒后仍未Running即停止并报告。任务持续运行后，检查正式 LIVE 关闭证明，再应用可回滚电源/更新/时间配置。若任务凭据失效，密码只在Windows任务计划程序输入，不发到聊天。若以另一个Windows管理员账号登录，不能假定它拥有同一个Ubuntu发行版。

脚本的影响与回滚见 `D:\Finfusion Client\docs\SERVER-HOST-RUNBOOK-2026-10-12.md`。包括临界10%电量关机、不自动重启、保存原电源方案与策略快照。没有为使检查通过移除交易关闭保护。

完成后：先连续观察任务Running、正式服务/公网/订单与行情只读查询至少20分钟，再安排人工维护重启。停在登录界面，用另一电脑记录公网API在登录前恢复；登录后关联任务日志、WSL和Windows启动时间。缺少独立证据时仍标待验收。

## 其他必须形成约定和证据的设置

| 优先级 | 设置/约定 | 证据与当前状态 |
|---|---|---|
| P0 | 保活任务使用发行版所属Windows身份；开机触发、无限运行、转电池不停止；密码改变后更新凭据 | 已配置，但当前Ready/退出1，需管理员启动与冷启动验证 |
| P0 | AC/DC自动睡眠、休眠、混合睡眠及硬盘空闲关闭；保持开盖散热，不手工关闭WSL | 脚本准备；尚未应用，仍需真正空闲20分钟测试 |
| P0 | 更新通知下载、16至次日10点活动时间；每周日10—12维护；安全补丁有负责人 | 尚未应用；活动时间并非全天禁止重启，还需核对适用ESU或受支持系统迁移 |
| P0 | Windows与WSL分别校时；目标偏差<5秒，≥15秒停止新的人工交易操作调查 | 前次双源约1.04秒；Windows校时服务原停止，待配置与重启后复测；不放大30秒签名窗口 |
| P0 | 来电开机与供电缓冲；电脑及光猫/路由器供电一起考虑 | Dell Wake on AC官方有选项，但BIOS设置和现场续航/网络UPS均未核验 |
| P1 | API、数据库、身份、Tunnel、行情/事件连接、备份新鲜度与启动失败告警 | 既有本机运维检查；整机/网络停电时本机告警不可达，不宣称外部监控 |
| P1 | 数据库持久化、磁盘余量与健康；保留加密备份及定期隔离恢复 | 本次实测PostgreSQL fsync/full_page_writes/synchronous_commit均on；这不替代真实停电或磁盘故障验收 |
| P1 | 有线网络优先；核查网卡节能、路由器重启、DNS/外网失联后的连接恢复 | 尚未实际修改或网络中断演练；保留loopback和Tunnel，不关闭防火墙 |
| P1 | 防资源争用与日志占满；应用和数据分离，8GB主机不同时跑4GB测试VM | 资源余量需持续记录；不自动结束用户应用；日志轮转/磁盘告警需独立核查 |
| P1 | 密钥、任务账号、权限与系统补丁；密码变更/密钥轮换/升级都有维护记录 | 保持现有DPAPI/age、受限目录；不启用自动登录、不改SYSTEM运行用户发行版 |
| P1 | 发布前备份、固定版本、回滚；更新后检查原请求状态与身份关联 | 已有release与数据库隔离恢复；Windows升级和硬件灾备不因此通过 |

当前仍是单台电脑，维修、断网或硬件故障会中断服务。现有备份为本机加密备份；将来需明确独立介质/异机恢复与独立监测范围，不能把同机备份当作物理磁盘损坏后的保障。本轮未新增异机备份或外部消息。

依据：[systemd依赖覆盖规则](https://github.com/systemd/systemd/blob/main/man/systemd.unit.xml)、[WSL systemd不保持发行版活跃](https://learn.microsoft.com/en-us/windows/wsl/systemd)、[PostgreSQL WAL持久化设置](https://www.postgresql.org/docs/17/runtime-config-wal.html)。

管理员步骤由用户执行，依据 `/home/<LINUX_USER>/worktrees/finfusion-server-1.0/AGENTS.md` 的明确规定；没有通过Linux调用Windows程序绕过提权。
