# 已有部署与身份初始化工具

此目录归档了已执行部署所用的源码，不包含真实配置、账户注册记录、密钥或数据库。`formal-deployment` 包含 LIVE/SANDBOX 准备、秘密注入、只读 perimeter 与身份/账户验收；`casdoor-init` 为既有 Casdoor 初始化和本机登录工具。

这些工具会读写真实身份、账户绑定、配置或服务；它们不是本次仓库更新自动运行的步骤。运行前核对路径、目标环境、当前服务状态、备份和用户授权。新机器必须重新配置秘密，不复用旧 clientId 或 DPAPI 私钥。历史 README/STATUS/LIVE-ACCEPTANCE 记录原部署过程，最新状态见根 docs/CURRENT-STATUS.md。

部分诊断工具明确加载 `/opt/finfusion/current`，另有旧工作树绝对路径；这是站点特定运维输入，不是应用运行时依赖。复制至新站点前先调整配置并验证，不直接执行批量初始化或启用交易。
