# 本机长期作为服务器的运行约定与验收

适用：Dell Vostro 5481、Windows 10 Pro 19045、WSL2 Ubuntu、服务器 1.0.0-rc1。北京时间，2026-10-12。本轮不执行真实订单。生产仍为 READ_ONLY；运行正常与交易允许分别判断。

## 本轮实际检查

证据目录：`D:\Finfusion Client\build\host-acceptance`。脚本目录：`D:\Finfusion Client\ops\windows-host`。只读采样约在 21:59—22:04 完成，尚未执行管理员设置或中断服务的演练。

| 项目 | 实测 | 判断 |
|---|---|---|
| 睡眠 | AC 600 秒、DC 240 秒；混合睡眠启用；硬盘空闲 30 秒关闭 | 不满足长期运行 |
| 系统事件 | 10-12 10:35:36 睡眠、10:35:38 唤醒；历史存在 6008 异常关机事件 | 已发生中断风险；不能把 6008 单独解释为停电 |
| 更新 | 活动时间 08:00—17:00；没有本项目更新策略；当前没有检测到 Windows Update RebootRequired | 尚未保护美股时段；不能据此保证没有所有类型的待重启 |
| 启动任务 | FastOrder-WSL-KeepAlive 为 Running、Password；Boot + Logon、开机延迟 30 秒、无执行时限、转电池不停止 | 已配置；尚未证明登录前 API 可用 |
| 启动证据 | Task Scheduler Operational 日志禁用；LastTaskResult 数值 2147946720，任务仍 Running | 保留原值，不能把该值或 Running 单独判定冷启动 PASS |
| WSL 服务 | PID 1 systemd；API、Tunnel、PostgreSQL、Casdoor、启动默认关闭门禁和两个运维 timer 均 active | 当前检查通过；不等于重启通过 |
| 时间 | W32Time Stopped / Manual；两个 NTP 源偏差 +1.0457、+1.0400 秒，往返约 0.067 秒；WSL 时间落在宿主采样区间内 | 当前偏差达标；Windows 持续校时未保障 |
| 签名时间窗 | 正式 HTTPS 的 GET /v1/accounts：0、+20、-20 秒均 200；+45、-45 秒均 403 ACCESS_DENIED | 5/5 通过，未改系统时间、未发单 |
| 供电 | 内置电池 100%、AC 在线；原临界电池 2% 时休眠 | 没有负载续航、路由器 UPS 或来电自启证据 |
| 公网 | /livez 200、ok=true、Cloudflare DYNAMIC，未命中缓存；运维 health OK，交易关闭 | 当前可用；不是登录前恢复证据 |

原始记录：`host.json`、`clock.json`、`signature-clock.json`、`policy-precondition.json`、`public-current.json`。NTP 为未认证的诊断读数，不能作为防篡改时间证明；双源一致降低单源异常风险。11 项离线测试覆盖偏差阈值、源冲突、错误原始时间、未同步、异常延迟及采样期间跳时，结果 `clock-tests.xml`。PowerShell 解析结果 `script-parse.json`。管理员变更、登录前启动、断电、更新重启均尚未验收。

## 日常运行约定

1. 接市电、保持散热和开盖运行；屏幕可以熄灭，锁屏可以，禁止使用睡眠、休眠或手工 `wsl --shutdown`。不把关闭终端当作保活机制。系统更新、WSL 更新、驱动、BIOS 及软件安装重启都纳入维护窗口。
2. Windows 用户 `Finfusion Tech` 保持现有身份；Ubuntu 是该用户的发行版。启动任务保持同一 Windows 身份，使用 Password 登录类型，不能改为 SYSTEM，也不采用自动登录。Windows 密码修改后由管理员更新任务凭据并重新验收。密码只在 Windows 本机界面输入，不能进入脚本、聊天、日志。
3. 建议活动时间 16:00 至次日 10:00（18 小时），涵盖当前美股主要运行时段及冬夏令时变化；默认维护约定每周日 10:00—12:00。此时间是运维安排，不是交易日历或券商可用性保证。更新采用通知下载；负责人至少每周检查一次并安排安全补丁，紧急漏洞及时安排临时维护。不能靠永久停用 Windows Update 换可用性。
4. 日常关注本机健康记录与客户端提示。Windows/网络完全断电时本机告警也无法发送；本轮没有独立外部监控或外部通知。30 秒运维检查和三次失败阈值是现有服务的观测机制，不是保证 90 秒恢复。
5. 不在交易电脑同时启动 4 GB QA VM：当前约 8 GB 总内存、空闲约 1.2 GB。CPU、内存和磁盘不足优先报告，不自动关闭用户软件或停止服务器。C 盘约 68 GB、D 盘约 443 GB 空闲是本次读数；WSL 虚拟盘显示的最大空间不能替代宿主实际磁盘余量。
6. 每日检查备份成功与新鲜度（现有 02:00 加密备份、7 个每日+4 个周代表），每月安排隔离恢复。仅本机备份不覆盖物理磁盘或整机损坏；备份解密密钥与受保护的原数据不得写入文档。数据库隔离恢复 PASS 不等于停电恢复、整机或异机灾备 PASS。

## 管理员设置：已准备，尚未应用

先阅读：`D:\Finfusion Client\ops\windows-host\apply-host-policy.ps1` 和 `restore-host-policy.ps1`。管理员 PowerShell 执行：

```powershell
& 'D:\Finfusion Client\ops\windows-host\apply-host-policy.ps1'
```

脚本先检查本机 /readyz 的全局和有效交易均关闭；不能确认就停止。域加入电脑拒绝本地覆盖，交由域策略管理。脚本会：

- 保留原电源方案，复制为独立 Finfusion Server Host，AC/DC 自动睡眠、休眠、混合睡眠及硬盘空闲关闭均设为 0；低电量 20%、临界 10% 关机，保留电池保护。开盖运行，盖子和电源按钮行为不修改；不能保证管理员手动休眠被禁止。临界关机是最后保护，不代替维护人员提前正常关闭服务。
- 设置活动时间 16→10、AUOptions=2 通知下载；保持更新可用，不关闭更新服务。关闭 Fast Startup，避免把休眠恢复当作完整冷启动。活动时间不是全天禁止重启，其他策略、更新期限或人为操作仍需检查。
- W32Time 改为 Automatic，启动，配置 time.windows.com 与 time.cloudflare.com，请求重新同步。校时只在交易关闭时执行；不能在生产运行中故意调快/调慢时钟测试。
- 启用任务运行日志；将改进的保活脚本放入系统盘 `C:\ProgramData\Finfusion\Host\Startup`，仅任务所属用户可读执行、SYSTEM/管理员可修改。不会替换现有任务、存储新密码或改变其身份，不自动重启。

变更前快照位于 `C:\ProgramData\Finfusion\Host\<时间>\rollback.json`。任一步失败即停止并记录部分变更，不声称设置已完成。回滚在管理员 PowerShell 使用实际生成的路径：

```powershell
& 'D:\Finfusion Client\ops\windows-host\restore-host-policy.ps1' -Snapshot 'C:\ProgramData\Finfusion\Host\实际时间\rollback.json'
```

恢复原活动电源方案、被改的策略、时间服务配置和日志状态；保留诊断电源方案和证据，不删除文件或数据库。当前脚本只有语法、只读前置条件和参数别名验证，管理员应用/回滚必须单独实际验收。

应用后普通 PowerShell 复查（不依赖未应用设置输出 PASS）：

```powershell
& 'D:\Finfusion Client\ops\windows-host\collect-host-evidence.ps1' -OutputDirectory 'D:\Finfusion Client\build\host-acceptance\after-policy'
w32tm /query /status
```

预期：睡眠/混合/休眠 AC/DC 均 0，W32Time Running+Automatic；重新同步来源明确，两个时间源一致且偏差小于 5 秒，Windows/WSL 比较 PASS，策略值准确，历史日志已开启，生产健康 OK、交易仍关闭。实际空闲至少 20 分钟后再取一份证据、检查期间未出现新的睡眠事件；不要使用强制 sleep 演练或假造心跳。校时源不可达/相互冲突时标 UNVERIFIED，不能沿用旧 PASS。

## 登录前启动与重启验收

现有 `C:\ProgramData\FastOrder\Startup\Keep-FastOrderWSLRunning.ps1` 是持续 `/bin/sleep infinity`，WSL 的 systemd 管理现有服务。保活任务与 Linux systemd 同时需要；微软明确 systemd 服务本身不会保持 WSL 活跃。现有任务已经 Password + Boot，无需重新登记账号或复制发行版。

改进脚本 `keep-wsl-running.ps1` 在 WSL 进程退出后以最多 60 秒间隔重试，每 30 秒记录脱敏宿主心跳。它不启用交易、不终止 WSL、不重启业务组件、不重发命令。准备完成不等于已运行。

如采用该脚本：管理员打开任务计划程序，先导出原任务 XML 到快照目录（XML 不包含任务密码，但保留受限权限）。编辑现有 FastOrder-WSL-KeepAlive 的操作：

- 程序：`C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe`
- 参数：`-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy RemoteSigned -File "C:\ProgramData\Finfusion\Host\Startup\keep-wsl-running.ps1" -Distro Ubuntu`
- 用户保持 Finfusion Tech，Password／不论是否登录，开机延迟 30 秒、登录备用触发、无限运行、转电池不停止、忽略新实例。保存时若提示 Windows 密码，只在任务计划程序输入。现有最高权限不是 WSL 发行版跨用户运行的替代；不切换 SYSTEM、不打开自动登录。

改操作后不结束当前生产保活任务来试运行；在安排好的重启中验证新动作。脚本自身不更改已有任务或其凭据。回滚动作使用原 XML 和原脚本路径；保存凭据仍由用户本机操作。

演练步骤与证据：

1. 维护前：确认全局交易关闭且有效交易关闭；查询待确认请求和订单，对账未完成则暂停维护。新备份 PASS，保存 /opt/finfusion/current 指针、版本、Windows 启动时间、WSL boot ID。禁止对 UNKNOWN 请求重新发单。
2. 另一台 Windows 电脑执行 `probe-public.ps1 -Samples 30 -IntervalSeconds 10`，保留开始至恢复的结果。在该电脑调用：`& '实际复制目录\probe-public.ps1' -Output 'C:\Users\实际用户\Desktop\finfusion-public-boot-probe.json'`。探测为 HTTPS GET，检查 ok=true、拒绝重定向及缓存 HIT。源电脑指纹与服务器不同，时间已同步。
3. 由用户正常重启宿主；不执行 WSL 关闭、拔电或强制杀服务来代替重启。停在 Windows 登录屏幕至少 5 分钟，不先打开 WSL、不先登录。另一台电脑记录 API 从失败恢复到连续至少三次 200 的时间。暂定目标 5 分钟内恢复，实际耗时必须实测，不能预填。
4. 再登录，管理员执行 `check-boot-evidence.ps1`，采集任务 100/200 与当前用户第一次交互登录 4624 的顺序；普通 PowerShell 执行 collect-host-evidence 保存 after-reboot。缺日志/缺第一次交互登录事件就 UNVERIFIED。工具不启动 WSL，单独任务启动事件不构成 API 恢复 PASS。
5. 核对独立公网探测在该次开机之后、首次登录之前成功；Windows/WSL 新 boot ID、服务状态、门禁仍关闭、备份 timer、数据库与客户端原请求查询均正常。只验证重新查询，不重发。不存在真实待确认订单时，注明由合成 LIVE 数据恢复证据补足，不能伪称实际重启有真实订单。
6. 失败停止：启动任务凭据错误、找不到同用户 Ubuntu、密码已变、磁盘无法解密、日期偏差≥15秒、数据库或身份不一致、登录后才能恢复、公网持续失败。保留失败证据，必要时以同一用户手工启动 WSL用于恢复；这是人工恢复，不能记无人值守 PASS。

若 BitLocker、启动 PIN、BIOS 密码需要人工解锁，记录为登录前自动恢复的硬性条件；不为自动恢复关闭磁盘加密或删除密码。

## 停电与来电恢复

电池为短时供电缓冲，不证明 UPS 能力；路由器/光猫/交换机也需要供电保障。当前没有测得负载续航，Windows 的估计分钟数不作为保证。长时间停电可导致计算机、网络及本机告警同时失效；已有券商委托不会因客户端断线自动消失，不能承诺在断网时完成撤单。

Dell 此型号官方 BIOS Power management 提供 AC Behavior → Wake on AC；当前 BIOS 状态未核验。由用户在维护中检查该项并拍照/记值，实测来电开机。不要假设设置后无条件开机，保持硬盘保护与账户边界。

1. 首轮只做短时断适配器测试：备份/门禁/电池健康确认，网络设备继续供电；不拆电池、不拔全部供电、不将电池耗尽。由用户操作，连续观察电池、系统事件、公网 GET 与客户端只读连接，10 分钟内恢复市电；电量≤20%立即结束并正常维护，不等临界关机。
2. 预期 Windows/WSL 没有新 boot ID、没有睡眠/休眠，API 连续可达、数据库可查询，恢复市电后仍不自动启用交易。10 分钟通过只证明该负载下的 10 分钟缓冲，不代表长时间 UPS 续航。
3. 网络设备断电／长时停电另设维护演练。本轮不自动制造；需明确允许中断，安排用户现场恢复与电池安全余量。正常关机后通过重新接适配器验证 BIOS 来电开机，按上一节登录前方法验证完整启动；不能用危险强制断电替代。
4. PostgreSQL WAL 恢复、真实请求状态、配置/密文身份、备份以及公网均需检查。无异常日志不等于曾实际断电恢复。最新隔离恢复只能提供数据库层证据。

## 时间偏差的运行约定

默认签名容差为 30 秒，不扩大该容差、不关闭防重放。日常目标偏差 <5 秒；5—15 秒警告并在交易关闭的维护窗口处理，≥15 秒或来源冲突停止新的人工交易操作并调查，重新对账/检查时间后才考虑权限。这里是运维约定，不宣称已新增自动交易时间门禁。

Windows 使用 W32Time、WSL 保持既有 NTP；本次 WSL timedatectl 报告 NTP=yes、NTPSynchronized=yes。启用 Windows 校时后在重启/恢复后分别测量两层，不能把任一同步标签等同外部时间精度。睡眠恢复、网络断开、校时失败都重新检查；不在运行生产服务时调时制造故障。

只读签名时间验证命令：在 `D:\Finfusion Client` 执行 `.\.venv\Scripts\python.exe -m tools.verify_host_signature_clock`。它仅改变请求中的签名时间，使用当前用户 DPAPI 密钥而不导出，所有调用为 GET。结果失败时检查来源，不自动调整系统时间或替换密钥。

## 本轮停止位置与验收清单

| 验收 | 结果 |
|---|---|
| 本机实际基线、两个外部时间源、WSL/服务、公网 | 已取证；发现睡眠、Windows 校时与更新窗口缺口 |
| 时间窗正式只读验证；离线异常时间包测试 | 5/5、11/11 PASS |
| 管理员电源/更新/时间设置及回滚 | 待用户执行，未验收 |
| 20 分钟真正空闲不睡眠 | 待设置后验证 |
| 更新安装后的真实重启恢复 | 待维护窗口；未安装任何更新 |
| 冷启动且登录前公网恢复 | 待用户重启与另一台电脑取证 |
| 短时电池供电、网络设备供电、来电开机 | 待用户现场演练/BIOS核查 |
| 系统时钟被人为调偏后的生产恢复 | 未执行；请求时间偏差验证不能替代该演练 |

Windows 10 普通支持已结束，需核实本机适用的 ESU 授权/更新覆盖或安排受支持系统迁移。WMI ESU 条目没有读到 LicenseStatus=1，但这不足以断言所有消费者订阅状态；补丁列表存在也不能证明 ESU 授权。未进行升级、购买或激活。

Windows 管理员步骤由用户执行，依据服务器工作树 `/home/<LINUX_USER>/worktrees/finfusion-server-1.0/AGENTS.md`：“遇到 Windows 管理员权限步骤，必须暂停该步骤，给用户明确的管理员 PowerShell 命令、影响及检查方式，待用户执行/反馈后继续”。本轮交付可审阅脚本和实测基线，没有自行提权、启用 Windows 功能、重启或断电。

官方依据：

- [微软 WSL systemd 生命周期](https://learn.microsoft.com/en-us/windows/wsl/systemd)
- [微软 WSL 生产用途与差异](https://learn.microsoft.com/en-us/windows/wsl/faq)
- [Windows 更新与重启政策](https://learn.microsoft.com/en-us/windows/deployment/update/waas-restart)
- [通知下载更新政策](https://learn.microsoft.com/en-us/windows/deployment/update/waas-wu-settings)
- [Windows 校时工具](https://learn.microsoft.com/en-us/windows-server/networking/windows-time-service/windows-time-service-tools-and-settings)
- [电池设置](https://learn.microsoft.com/en-us/windows-hardware/customize/power-settings/battery-settings)
- [Dell Vostro 5481 来电唤醒选项](https://www.dell.com/support/manuals/en-in/vostro-14-5481-laptop/vostro_5481_setup_specs/power-management?guid=guid-e5aabdc8-dcf8-45da-99a5-43001ee51520&lang=en-us)
- [Windows 10 商业 ESU](https://learn.microsoft.com/en-us/windows/whats-new/extended-security-updates)
