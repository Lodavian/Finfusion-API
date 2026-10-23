# 服务器宿主运维工具

完整约定、实际结果和逐步验收：`D:\Finfusion Client\docs\SERVER-HOST-RUNBOOK-2026-10-12.md`。

最新启动修复、保活任务待执行项与其他设置清单：`D:\Finfusion Client\docs\SERVER-AUTOSTART-2026-10-13.md`。管理员脚本已改为直接核对Ubuntu正式进程，而不是Windows端口代理；Linux开机目录和旧验证服务启动依赖已修复。冷启动与持续公网仍待独立验收。

- `collect-host-evidence.ps1`：只读检查、诊断 SNTP 与 WSL 时间/服务；会调用当前用户已有的 Ubuntu（不能用它启动 WSL后证明登录前启动）。
- `clock_probe.py`：Python 标准库，无券商依赖；双源不足/冲突不可判 PASS，不更改时钟。
- `apply-host-policy.ps1`、`restore-host-policy.ps1`：管理员人工执行的可回滚配置，当前未应用/未实际回滚。
- `keep-wsl-running.ps1`：保活、退避、宿主心跳；未替换现有任务，不修改订单或门禁。
- `check-boot-evidence.ps1`：管理员只读采集任务与登录先后，不调用 WSL、不自行判断完整启动通过。
- `probe-public.ps1`：独立电脑采集 HTTPS 存活；本机当前可用不能代替登录前取证。
- `test_clock_probe.py`：离线协议/偏差诊断测试，不连接真实券商。

未安装新服务、未重新注册发行版、未读取任务保存的 Windows 密码；不运行任何真实交易。先审阅脚本再按 runbook 执行管理员配置和安排演练。证据默认在项目 build 目录，不打入客户端安装包。
