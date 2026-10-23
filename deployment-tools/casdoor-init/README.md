# Casdoor 本机初始化验收

日期：2026-10-09。目标：本机 WSL2 Ubuntu 26.04.1 LTS。

## 使用入口

双击 `D:\Finfusion Client\Open-Casdoor.cmd`，选择账号，按需勾选 Show initial password，再点击 Open login page。密码默认隐藏，没有写进此文档或聊天。窗口提供两组独立账号：

- `built-in / admin`：Casdoor 自身的系统管理员，可管理组织、应用和用户；登录地址 `http://127.0.0.1:8000/login`。
- `finfusion / admin`：Finfusion 管理员，具有 `finfusion-admin` 角色；独立登录地址 `http://127.0.0.1:8000/login/finfusion-admin`。

初始密码通过 Windows DPAPI 加密，存放于 `C:\Users\<WINDOWS_USER>\AppData\Local\Finfusion\Admin\casdoor-login.json`，只能由当前 Windows 用户解密。更改网页密码后，该文件仍保存旧的初始密码，不会自动更新。窗口不自动填写网页，也不会将密码复制到剪贴板。

当前 Windows PowerShell 的执行策略为 Restricted；启动入口仅对本次 PowerShell 进程使用 Bypass 来运行本地查看脚本，不修改系统或用户的执行策略。脚本已做语法检查和只解密不显示的校验；图形窗口未自动启动或点击。

## 已完成的服务器配置

- Casdoor 固定为 3.143.0；实际二进制 SHA256：`cdde5f88b65e9a91803a745748710760757bc0f8834e7d7c971d5fbddb4e3f43`。
- 独立 PostgreSQL 数据库 `casdoor`，独立登录角色 `casdoor_service`，不具备超级用户、创建数据库或创建角色权限；撤销 PUBLIC 的数据库连接权限。
- `/var/lib/finfusion/casdoor/conf/app.conf`：finfusion 所有，0600。HTTP 只监听 `127.0.0.1:8000`。
- 两组管理员使用不同的随机强密码，数据库按 bcrypt 存储。公开注册、游客登录已关闭。
- 独立随机生成的 4096 位 RSA 签名证书，RS256；应用使用 JWT-Custom，仅选择 Owner、Name、DisplayName、Roles、Type，另有标准 JWT 字段，不携带密码字段。
- Finfusion 应用启用授权码 + S256 PKCE，另启用正式后端所需的 client_credentials；Client Secret 只保存在 Linux root 受限目录和数据库中，没有放入前端公开连接信息或 Windows 密码文件。
- 已移除示例 LDAP 数据；LDAP/LDAPS 不监听。此固定版本的 RADIUS 无关闭开关，`0` 会分配随机 UDP 端口；配置 `-1` 使其拒绝绑定。已经检查无 Casdoor UDP 监听，日志中预期会有 RADIUS 端口无效提示，不影响 HTTP/OAuth 服务。
- 一次性初始化导入文件已删除，initDataFile 为空。服务重启不会重新导入账号或重置配置。
- `casdoor.service` 已启用、运行；它随 Ubuntu 的 systemd 启动。本轮没有重启整台电脑或整个 WSL，仅重启并验证了 Casdoor。

## 正式后端的后续连接信息

公开配置：`D:\Finfusion Client\admin-console\casdoor-init\connection-public.json`；Linux 副本：`/var/lib/finfusion/casdoor-bootstrap/connection-public.json`。

正确的全局 JWKS 地址是 `http://127.0.0.1:8000/.well-known/jwks`；`/api/certs` 不是本版本的 JWKS 地址。Issuer 为 `http://127.0.0.1:8000`，Audience 使用公开配置中的 clientId。回调暂登记 `http://127.0.0.1:8081/admin/`，目前该网页尚未部署，因此完成 OAuth 配置不代表正式 Finfusion 管理网页已经可用。

参考实现：[固定版本的 JWT 实现](https://github.com/casdoor/casdoor/blob/v3.143.0/object/token_jwt.go)、[官方 OIDC 说明](https://casdoor.org/docs/how-to-connect/oidc-client/)。

## 真实验收步骤与结果

验证脚本：`D:\Finfusion Client\admin-console\casdoor-init\verify_local.py`。该脚本只从 Linux root 受限文件读取凭据，HTTP 请求在本机完成，不输出密码、Client Secret、Cookie、授权码或令牌。

| 步骤 | 预期 | 实际 | 失败时停止条件 |
|---|---|---|---|
| 核验安装二进制哈希与现有数据库 | 哈希匹配，Casdoor DB 尚不存在 | 匹配；创建前 DB 不存在 | 不匹配或已有 DB 时不运行一次性初始化 |
| 两组账号分别 POST /api/login | 随机密码可以登录 | 两组均 PASS | 任一登录失败不宣称初始化完成 |
| 分别尝试默认密码 123 | 拒绝 | 两组均 PASS | 接受默认密码时停止交付并修复 |
| 授权码 + S256 PKCE，不提供 Client Secret | 可以换取令牌 | PASS | 失败则不连接正式服务 |
| 用现有 Finfusion CasdoorJwtVerifier 载入 JWKS 并验签 | 正确签名、issuer、audience、sub 和管理员角色 | PASS，密码字段未进入 JWT | 任一条件失败则不连接正式服务 |
| 重复兑换同一授权码 | 拒绝 | PASS | 接受重放时停止交付 |
| 用现有 CasdoorAdminClient 获取服务令牌并读取管理用户 | 返回稳定用户 ID | PASS | 失败则不能宣称管理服务身份接口就绪 |
| 获取 HTML 和其中所有 JS/CSS | HTTP 200，资源位于本机 | HTML 与 2 个资源均 PASS | 任一失败则修复网页 |
| Windows 浏览器打开中文登录页 | 页面完整、Logo 和输入框正常 | 已目视确认，截图见下方 | 页面异常不交付入口 |
| 重启 Casdoor 后重复以上协议测试 | 数据持久，功能一致 | 全部 PASS | 失败时检查服务日志，保留 DB 不重置 |
| 检查 systemd / 监听 / 文件权限 | 启用且 active、仅 loopback、0600/0700 | 符合 | 发现外部监听或秘密权限异常先停止 Casdoor |
| 生成受限 pg_dump 并检查目录清单 | 有效备份，root 0600 | PASS | 失败不报告备份完成 |

![本机中文登录页](D:/Finfusion%20Client/admin-console/casdoor-init/casdoor-login.png)

## 受限文件与恢复边界

Linux root 目录 `/var/lib/finfusion/casdoor-bootstrap` 为 0700；其中秘密文件为 0600。它包含初始凭据、数据源、原 systemd 单元快照和数据库备份。不要将其复制到 Git 或公共目录。

已验证数据库备份：`/var/lib/finfusion/casdoor-bootstrap/casdoor-initialized-20261009-163507.dump`。本轮只检查备份清单，没有执行数据库恢复。

本轮新建的 systemd 覆盖配置：`/etc/systemd/system/casdoor.service.d/20-local-bootstrap.conf`。Casdoor 当前使用独立本机受限配置，不依赖尚未初始化的完整交易 Vault。原 service 的 systemd 沙箱限制仍在；此次没有启动正式 `finfusion.service` 或修改 Vault、券商凭据与 Tunnel。

若需要临时停用，只运行 `sudo systemctl disable --now casdoor.service`，数据和配置保留。将来切换完整加密 Vault 时，需先备份，再把本机身份配置与 Client Secret 正式纳入 Vault，设置确认后的域名/JWKS/回调并移除此覆盖配置。不要直接运行全节点配置器填入假券商凭据。

`initialize_local.py` 是本轮一次性初始化脚本，拒绝已有数据库；不要重跑来修改密码。`finalize_local.py` 是本轮导入收尾脚本，也不用于日常管理。日常操作使用网页或受控的正式后台。

## 原项目与尚未完成的部分

服务器代码基线 `/home/<LINUX_USER>/workspace/fastorder` 的 HEAD 为 `f581d3b7fc7ad42dbe07c234b48771c0fda778d8`。本轮没有改服务器源码、没有提交或 push。已有用户修改 `tests/test_server_infrastructure.py` 原样保留，工作区不是 clean。

既有 finfusion-connectivity、Nginx、PostgreSQL 均保持 active。正式 `finfusion.service` 仍未启动；`http://127.0.0.1:8765/admin/` 仍是预览界面，不能因 Casdoor 已启动而当成真实管理页面。后续还需要正式管理服务配置和 UI 部署、身份接入与 API 权限闭环。本轮没有券商连接、行情验收或实盘订单。
