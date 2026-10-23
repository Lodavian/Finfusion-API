# 给“用户端的安装包”聊天的服务端联调交接

2026-10-09，Webull HK LIVE 正式环境，仅管理及只读查询。五个接口已部署并真实联调，不再是此前的 404 状态。

## 测试身份与打开方式

- 测试用户：<READ_ONLY_TEST_USER>。复用已有身份，没有新建用户、移动账户或轮换密钥。
- API：https://api.finfusion.asia
- clientId：<REGISTERED_CLIENT_ID>（客户端公有标识，不是密码）。
- 账户别名：Webull HK 账户 1、Webull HK 账户 2。实际 accountRef 从签名 GET /v1/accounts 获取，不使用券商原始账户 ID。
- 本机配置：C:\Users\<WINDOWS_USER>\AppData\Local\Finfusion\Client\settings.json；P-256 私钥已经按当前 Windows 用户 DPAPI 保存，不复制私钥，不需要 Casdoor 管理员密码。
- 当前源码客户端：D:\Finfusion Client\Open-Finfusion-Client.cmd，调用 D:\Finfusion Client\run.ps1。
- 管理网页：http://127.0.0.1:8081/admin/。示例预览 8765 不是本次验收入口。

## 已上线接口

五个 GET 接口沿用 FINFUSION-V1 签名、用户/客户端读取权限与账户归属校验：

1. /v1/market/symbols?accountRef=…&q=AAPL：完整代码候选，支持 Webull COMMON_STOCK。
2. /v1/market/snapshot?accountRef=…&symbol=AAPL：实际 price 优先于 close，last_trade_time 作为来源时间。
3. /v1/market/trades?accountRef=…&symbol=AAPL：最近成交。
4. /v1/market/events?accountRef=…&symbol=AAPL：签名 WebSocket，connected、market.update；重连重新签名。
5. /v1/accounts/{accountRef}/ui-context：LIVE、只读权限、实际门禁及公开风险规则。

既有 /v1/accounts/{accountRef}/balance 保留 usdBuyingPower，新增 usdCashBalance、usdSettledCash、usdUnsettledCash。仅提取 USD 币种资产；十进制字符串，缺失 null，零值仍显示 0。不能用购买力或 HKD 总余额填美元现金。既有持仓接口及交易服务语义保留。

客户端源码增加美元现金余额与购买力独立标签、完整来源日期时间、明确的空持仓/数据不可用显示；修复关闭窗口时轮询回调与 UI 线程等待的问题。HTML、JS 及 Python 入口已改变，旧安装包/便携包不会自动更新，客户端部署聊天需据当前源码重建并验收安装生命周期。

## 重复验收步骤、结果与停止条件

1. 在 D:\Finfusion Client 执行 .venv\Scripts\python.exe -m tools.check_readonly_connection。预期五个接口可读、两个账户归属一致；实际两账户 REST、行情 WebSocket、订单只读 WebSocket、实际 Controller 全部通过。报告：D:\Finfusion Client\build\readonly-integration.json。
2. 打开源码客户端，连接服务器，分别选两个账户。预期美元现金和购买力分开显示、持仓正确；实际券商现金字段与签名响应逐字段相等，持仓数量与券商读取一致。当前券商原始持仓均为空，界面显示“当前账户无美元股票 / ETF 持仓”，不是请求失败。
3. 查找并选择 AAPL，再切换 MSFT、AAPL。预期候选非空、价格和账户/股票对应；实际 REST 和重新签名 WS 验证通过。行情目前有有效价格及来源时间，常规时段数据为 STALE；不伪装成实时 READY。休市或过期时保留来源时间，许可不足显示 MARKET_DATA_DENIED。
4. 执行 .venv\Scripts\python.exe -m tools.check_live_webview。预期真实 WebView2 展示现金、购买力、持仓区域、AAPL 价格与时间，LIVE 交易按钮禁用；实际两个账户均通过，断开清除旧值、重连后 MSFT 数据归属通过。报告：D:\Finfusion Client\build\live-webview-acceptance.json。
5. 服务端已实际停用/恢复用户及撤销/恢复客户端：新行情读取立即 403，现有行情 WS 关闭。最终测试身份恢复启用及只读批准；无需客户端聊天重复修改管理员权限。
6. 全局、用户、账户交易关闭，canRead=true、canTrade=false、canCancel=false。服务端附加边界拒绝下单、改单、撤单及交易权限提升。订单阻断使用模拟边界测试验证；没有向真实服务器发送订单形状请求。

停止条件：任何账户归属不一致、旧行情混入、新接口 404、鉴权失败、现金被替换成购买力或 LIVE 交易按钮可用，立即停止该项测试并记录脱敏状态；不尝试交易、不改密钥、不重新绑定账户。503 readiness 表示交易未就绪，不能把它当作只读鉴权失败或伪造门禁修复。

## 发布与证据

- 服务端运行版本：/opt/finfusion/releases/f581d3b-market-20261009-2，由 /opt/finfusion/current 指向。
- Git 基线：f581d3b7fc7ad42dbe07c234b48771c0fda778d8；本次为已审查文件覆盖层，不是新 Git commit。
- 覆盖层清单：/var/lib/finfusion/formal-deployment/live/market-release-manifest.json；SHA256：099b04bfc92e9dc8e3274a34d37eefd161c3d4b70e356765433ccd0f3a93930e。
- 原源码版本、服务配置、数据库备份保留在 /var/lib/finfusion/formal-deployment/live/market-rollback；未恢复/重置数据库。首次切换因目录权限失败自动回滚，修正后切换及后续公网验收通过。
- 服务端测试 50 passed、1 skipped（未提供一次性 PostgreSQL 测试库）；另有只读边界测试 1 passed，覆盖 8 类阻断和 4 类允许场景。真实生产数据库上的只读查询及管理操作另有实际验证。
- 客户端测试 55 passed。真实 WebView2 两账户联调通过；标准 UI smoke 复测所有检查 true、进程退出码 0，报告 D:\Finfusion Client\build\live-change-smoke-retry.json。
- Casdoor、finfusion、nginx、finfusion-api-tunnel 均 active。交易 readiness 保持关闭，未开启节点/Tunnel门禁或交易开关。
- 原服务器仓库 /home/<LINUX_USER>/workspace/fastorder 的用户 tests/test_server_infrastructure.py 修改保留，工作区不是 clean。没有 commit/push、SDK 升级或锁文件重写。17 个其他核心 Python 文件与原运行版本逐字相同；Gateway 仅增加行情观察与订阅释放，原交易价格/下单/撤单方法不变。

日志、报告与此文档仅保留状态、字段名和计数，不记录实际金额、券商账户 ID 或密钥。真实余额比较经私密进程管道进行，未写入工作区。
