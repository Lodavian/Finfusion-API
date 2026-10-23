# LIVE 正式环境验收

2026-10-09 后续更新：五个行情/UI 接口及美元现金字段已部署，真实 Windows 界面联调通过。完整当前状态见 D:\Finfusion Client\docs\CLIENT-UI-SERVER-HANDOFF-2026-10-09.md；以下为此前仅账户读取阶段的记录。

2026-10-09。用户已选择 Webull HK LIVE，范围为管理和只读账户查询。

1. 正式 finfusion.service 已启动。独立 finfusion_live 数据库、角色和密钥；Sandbox 数据库保留。
2. http://127.0.0.1:8081/admin/ 已通过浏览器真实 Casdoor PKCE S256 登录，显示 1 个用户、1 个只读客户端、2 个绑定账户。Nginx 同源 /admin/oauth/token 转发解决浏览器令牌交换失败，仅 POST/OPTIONS，不向浏览器提供 client secret。
3. 创建 <READ_ONLY_TEST_USER> 用户、登记实际 Windows 公钥、待批准时拒绝、批准只读、分配真实账户完成。停用用户及撤销客户端各令 Windows 请求立即 403；恢复只读后连接成功。
4. Windows 实际 DPAPI/P-256 私钥通过公网 HTTPS 查询两个账户的账户列表、持仓、余额；实际 Engine.connect 成功。默认客户端配置已保存，旧配置备份 settings.before-live.json，私钥未改。未验证桌面 GUI 点击或行情扩展。

全局、用户、账户交易开关全关闭，客户端仅 canRead。服务器附加只读边界阻断订单写入与开启交易权限。1 个测试覆盖 8 类阻断/4 类允许场景，通过。实际管理 API 开启全局、交易或撤单权限返回 READ_ONLY_DEPLOYMENT。未发送真实订单形状请求，没有下单、改单或撤单；交易 readiness 未就绪，行情扩展未部署。

Webull LIVE Token NORMAL，账户发现 HTTP 200。Linux 凭据 root 受限 age 加密，Windows 当前用户 DPAPI。此前错误标注的 Sandbox 加密凭据已改为 live-broker.json / LIVE；密钥未变，Sandbox 解密拒绝误用正式凭据。

正式服务已重启，再次验证 Windows Engine 连接成功。Casdoor、finfusion、nginx、finfusion-api-tunnel 均 active。finfusion 随 Ubuntu 启动，旧 connectivity 服务禁用以避免冲突；尚未设置 Windows 无人登录自动启动 WSL。LIVE 和 Casdoor 备份位于 /var/lib/finfusion/formal-deployment/live/backups，root 0700/0600，pg_restore --list 验证通过。配置回退材料位于 live/rollback。

Open-Finfusion-Admin.cmd 启动 Ubuntu 服务并打开 Windows 浏览器。Open-Finfusion-Client.cmd 打开已配置的客户端。Open-Casdoor.cmd 查看受保护的管理员密码；管理网页使用 finfusion/admin。8765 是示例预览，8081 是真实入口。

服务器业务基线 f581d3b7fc7ad42dbe07c234b48771c0fda778d8。业务源码未改、未提交或 push，用户 tests/test_server_infrastructure.py 修改保留。验收截图：live-admin-verified.png。
