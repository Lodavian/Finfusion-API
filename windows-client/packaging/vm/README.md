# 客户端 1.0 一次性 VM

本机：Windows 10 Pro，8 GB 内存。已核对 Hyper-V 和管理模块未启用；微软 Windows 11 企业评估镜像已由官方 CDN 下载到项目 build/vm-media，并与微软公布的 SHA256 核对通过。VM 配置 4 GB 固定内存、2 vCPU、64 GB 动态磁盘、Gen2/安全启动/vTPM。至少约 4.5 GB 空闲内存再启动，以保留宿主和现有 WSL 服务余量。

服务器规则要求 Windows 管理员步骤由用户执行。先审阅脚本，再在**管理员 PowerShell**运行：

```powershell
& 'D:\Finfusion Client\packaging\vm\enable-hyperv.ps1'
```

仅启用 Hyper-V，不设置长期运行、电源或更新，不自动重启。如果提示需要重启，由用户保存工作并安排；重启后回到此任务继续。

ISO 下载成功后，在管理员 PowerShell 创建 VM（不启动）：

```powershell
& 'D:\Finfusion Client\packaging\vm\prepare-vm.ps1'
```

内存足够时可首次创建并启动：

```powershell
& 'D:\Finfusion Client\packaging\vm\prepare-vm.ps1' -Start
```

已有 VM 不允许覆盖，之后使用 Hyper-V 管理器启动它。安装只针对新虚拟磁盘，不能安装到宿主实体盘。微软评估版仅用于隔离测试，遵循其评估条款；不采用绕过硬件要求、认证或许可的脚本。

干净安装后建立快照，依 docs/ACCEPTANCE-1.0.md 在 VM 内执行完整安装矩阵。guest 新密钥由 guest 当前用户生成，不能复制宿主 DPAPI 私钥。真实账户读取使用新 clientId 的只读批准；任何实盘下单均不属于 VM 自动安装脚本。

本目录中的脚本准备完成不等于 VM 安装验收通过；缺管理员启用、内存或完成 guest 安装时，验收应标 PENDING。
