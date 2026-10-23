> 2026-10-23 仓库汇总说明：最新整体状态见根目录 `docs/CURRENT-STATUS.md`；本文保留各阶段背景，历史机器路径不代表新 clone 的路径。

# Finfusion 管理台

## 现在怎么打开

双击本目录的 `Open-Admin.cmd`，会自动启动仅本机可访问的界面预览，并使用默认浏览器打开 `http://127.0.0.1:8765/admin/`。

它是浏览器网页，不是自动随服务器弹出的桌面窗口。布局参考用户提供的截图：深色导航、米白背景、细边框卡片、紧凑表格。

本地预览使用独立的虚构示例用户和账户。页面持续标注“本地界面预览”，提交按钮禁用；预览服务器对 POST/PATCH/PUT/DELETE 返回 405，不代理或访问真实管理 API。不需要账号密码，不能执行管理操作。

停止预览：运行 `powershell.exe -NoProfile -ExecutionPolicy Bypass -File "D:\Finfusion Client\admin-console\Stop-Preview.ps1"`。

## 正式使用

同一台电脑可以让 Ubuntu/WSL2 服务器在后台运行，前台通过 Windows 浏览器管理。浏览器发送管理 API 请求到 Ubuntu；关闭浏览器不会停止 Ubuntu 服务。已配置的 FastOrder-WSL-KeepAlive 计划任务负责 WSL 保活，不依赖管理员网页保持打开。电脑需保持开机，睡眠/关机期间服务不提供访问。

管理页面资源已保持原管理 API 契约，支持 Casdoor PKCE 登录、用户创建/启停/密码重置、公钥登记/clientId 分配、客户端批准/撤销/公钥轮换、查询/交易/撤单权限、账户登记/绑定/解绑，以及全局/用户/账户交易开关。

正式管理服务启用后，用浏览器打开 `https://api.finfusion.asia/admin/`，点击“管理员登录”，使用具有 `finfusion-admin` 角色的 Casdoor 用户登录。也可运行 `Open-Admin.ps1 -Production` 打开该地址。

目前公网运行的是只读连接验证服务，`/admin/` 返回 404，Casdoor 与正式服务未运行。界面完成不代表管理后台已部署。后续需要配置管理员身份、OIDC 登录地址和回调、Casdoor 管理服务凭据、正式服务及数据库，然后进行真实权限联调。此轮没有创建真实用户、授予权限、启用交易或更改当前运行服务。

## 源码与集成

- UI 交付目录：`D:\Finfusion Client\admin-console\server_admin`。
- 服务器隔离工作树：`/home/<LINUX_USER>/worktrees/finfusion-admin-ui`。
- 基线：`f581d3b7fc7ad42dbe07c234b48771c0fda778d8`。
- `Finfusion-Admin-UI.patch` 只改 `server_admin/` 资源；未改后端、交易逻辑或认证协议。与行情接口改动位于不同工作树，部署前需在同一发布工作树整合。
- 本项目 AGENTS 的 frozen UI 默认规则由用户本轮明确要求制作参考风格管理台覆盖，改动仍保持隔离。

复制本目录到其他位置后，预览入口会优先使用相邻客户端的 Python 环境，再尝试当前用户 Codex Python 或系统 Python 3.11+。此预览不是独立 EXE 安装包。

品牌图标复用客户端现有资产；导航图标来自 Bootstrap Icons 1.11.3（MIT，许可在 assets 内）。无 CDN、无外部字体请求。
