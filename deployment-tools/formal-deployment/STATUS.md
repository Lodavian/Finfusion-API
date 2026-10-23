# 历史准备记录（已被 LIVE 验收替代）

2026-10-09 最终状态请参阅同目录 LIVE-ACCEPTANCE.md。以下为选择 LIVE 前的历史记录，不能作为当前状态。

2026-10-09，本机 Ubuntu 26.04.1 LTS。当前请求：按顺序完成正式服务、管理网页、管理闭环和 Windows 客户端联调。

## 已实际完成的准备

1. 新建真正的 PostgreSQL `finfusion_sandbox` 数据库，独立 `finfusion_sandbox_service` 登录角色，无超级用户/建库/建角色权限。已执行原项目迁移并绑定 SANDBOX 环境。全局交易开关为 false，未登记或伪造券商账户。
2. 用户已选择的管理网页部署文件已复制到 `/opt/finfusion/admin-ui`，完整 SHA256 清单存放 `/var/lib/finfusion/formal-deployment/admin-ui-manifest.json`。目前尚未启用正式 HTTP 管理入口。
3. Casdoor 的 issuer、正确 JWKS 路径、管理员应用和本机回调已写入待启用服务配置 `/var/lib/finfusion/formal-deployment/server.env.pending`。尚未把它安装成 `/etc/finfusion/server.env`，避免未就绪服务替换现有 API。
4. 为新数据库生成了受限密钥，存于 Linux root 0700 目录下的 0600 文件 `/var/lib/finfusion/formal-deployment/prepared-secrets.json`。其中没有假 Webull 密钥或假 Tunnel 凭据。交易限制暂准备为每单 1 股/100、每日 100、最多 1 个未结订单，交易开关仍关闭；它们尚未启用，也不是交易授权。
5. 本机私密填写入口 `D:\Finfusion Client\Configure-Sandbox.cmd` 已准备。输入的 Sandbox App Key/Secret 只按当前 Windows 用户 DPAPI 加密到 `C:\Users\<WINDOWS_USER>\AppData\Local\Finfusion\Admin\sandbox-broker.json`，不会写到源码或聊天，不会启动服务或打开交易。

## 当前必要前置条件

后续真实校验更新：用户已通过本机入口保存凭据，并说明它们属于香港站 **LIVE 正式环境**。已用项目配置的香港 Sandbox 接口做一次只读账户请求，返回 `401 / UNAUTHORIZED`，错误说明为凭据或环境不匹配。没有在正式环境发出请求。

这不证明 Key 无效，而是正式 Key 与测试接口不能混用。为避免误注入，已从 `/run/finfusion/secrets/sandbox` 移除此次解密的凭据文件，保留 root 受限的 age 加密存储；Sandbox 解密脚本增加了环境分类检查。

当前等待用户选择：使用独立 LIVE 环境仅做管理和账户只读查询、保持交易权限与交易开关关闭；或另行提供真实 Sandbox 凭据。此选择前不会启用 FINFUSION_LIVE_ALLOWED，也不会把现有 Sandbox 数据库改为 LIVE。

原有 `/opt/finfusion/current/finfusion/main.py` 的正式启动流程先读取 Sandbox App Key/Secret，再调用 `gateway.initialize()` 发现机构账户，随后才建立管理服务。因此在没有有效凭据时，不能真实启动正式服务。没有用测试 Gateway、伪造账户或忽略初始化检查来将其标记为成功。

用户需说明是否已有 Sandbox 凭据；若有，请通过上面的本机私密入口填写，再回复“Sandbox 凭据已保存”。不要把密钥粘贴到聊天。

## 四步的实际状态

| 步骤 | 实际状态 |
|---|---|
| 正式管理服务 | 数据库和连接配置已准备，启动等待真实 Sandbox 凭据及安全注入配置 |
| 正式管理网页 | 部署文件已准备，尚未接通真实 HTTP 管理服务 |
| 用户、公钥、批准、停用、撤销闭环 | 待正式服务启动后通过真实管理 API 验证，尚未声称通过 |
| Windows 客户端只读联调 | 待上述闭环和真实 API；当前客户端使用已登记的 P-256 密钥鉴权，不把 Casdoor 管理员令牌放入客户端 |

## 已执行检查与停止条件

- 建库前确认数据库和角色不存在；存在时停止，不覆盖已有数据。实际：均不存在，已新建。
- 原项目迁移及 environment 绑定。预期：SANDBOX、全局关闭；实际：SANDBOX / false。
- 管理网页资产复制和哈希清单。实际：已生成。
- Windows 私密输入脚本语法检查。实际：通过；凭据存在性检查结果“尚未填写”。没有自动打开窗口、填写或提交任何密钥。
- 检查 Casdoor、现有 finfusion-connectivity 服务。预期：继续 active；实际：两者 active。
- 缺少券商凭据时停止正式服务启用，不停现有 API，不伪造账户。

代码基线 `/home/<LINUX_USER>/workspace/fastorder` 的 SHA：`f581d3b7fc7ad42dbe07c234b48771c0fda778d8`，main。未修改服务器源码、未提交或 push；用户已有 `tests/test_server_infrastructure.py` 修改保留，工作区不是 clean。

本轮没有券商连接、订单发送、LIVE 操作或全局交易开关开启。
