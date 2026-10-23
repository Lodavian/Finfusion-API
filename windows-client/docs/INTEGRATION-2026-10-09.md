# 2026-10-09 用户端与正式 Webull HK 服务只读联调

目标服务器：`https://api.finfusion.asia`。沿用本 Windows 用户既有 clientId 和 DPAPI 密钥；没有更换密钥、注册权限、修改服务端、启用门禁或执行交易。

## 已验证

- HTTPS 与 FINFUSION-V1 签名账户查询通过，返回两个授权账户；保持多账户手动选择。
- 两个账户的持仓、美元购买力和订单列表查询通过；美元购买力字段为 `usdBuyingPower`。
- 订单 WebSocket 收到初始 connected 消息。未提交订单，不能据此宣称真实订单成交事件已验证。
- 使用实际桌面 Controller 依次选择两个账户，确认当前账户持仓、购买力返回归属正确；使用临时请求库，不改写用户已有未确认请求。
- 客户端自动化测试 55 passed，包含服务器缺少 UI 状态接口时保留鉴权、清除旧交易权限、拒绝交易，以及缺少行情接口时停止重连。
- WebView2 155.0.4283.45 实际窗口及桥接检查通过。首次检查各项结果为 true，但进程退出时出现无法格式化的 CLR 异常；复测各项为 true 且退出码 0。此瞬时退出异常需要继续观察，不能宣称所有启动/退出场景均稳定。

## 当前准确缺口

以下接口在当前正式服务返回 404；部署文件 `/opt/finfusion/current/finfusion/api.py` 亦未注册这些路由：

- `GET /v1/accounts/{accountRef}/ui-context`
- `GET /v1/market/symbols`
- `GET /v1/market/snapshot`
- `GET /v1/market/trades`
- `GET /v1/market/events`（WebSocket）

行情与 UI 状态在 0.2 隔离工作树已开发，但尚未合入本次正式部署。已连接券商数据源不等于这些用户接口已开放。客户端没有直接访问券商、伪造行情或推断 LIVE 权限的回退。

`/readyz` 返回 503，但签名鉴权与只读查询成功。当前布尔状态：database、brokerEvents、market、reconciliation 为 true；tunnel、nodeActive、globalTradeEnabled、effectiveTradeEnabled 为 false。`tunnel=false` 是服务器内部就绪判定，本次公网查询确实可达；未擅自改变其判断或启用交易。

订单列表在本次读取为空，订单详情及真实状态流转待有合法可读订单时再验证。原 requestId 查询及交易恢复本次仅有模拟回归证据，不制造真实请求用于验收。

## 用户端修正

- 明确显示 UI 状态接口未部署，保持交易禁用；不把配置保存或服务器 503 当作鉴权失败。
- 连接区显示服务器布尔门禁缺口。
- 行情 404 显示接口未部署并停止无意义自动重连；403 显示无权限；保留真正网络故障的退避恢复。
- 保留券商行情拒绝与不可用的安全错误码，不泄露原始错误或凭据。

## 重复只读检查

在项目根目录运行：

```powershell
& .\.venv\Scripts\python.exe -m tools.check_readonly_connection
```

脚本只调用 GET/只读 WebSocket，读取现有用户配置和 DPAPI 密钥。结果位于 `build/readonly-integration.json`；只记录字段名、计数和状态，账户路径已脱敏。readiness 检查 PASS 表示响应格式可读取，是否交易就绪见其中的 readiness 布尔值。

## 下一步

服务器维护线需核对并整合五个只读接口后再安排部署；客户端本轮不修改或部署服务器。部署后补查股票候选、快照、成交及行情事件，对照真实 Webull HK 数据及权限核验字段。内部候选仍仅允许服务器明确标记 SANDBOX 的交易，真实 LIVE 交易没有授权也没有执行。安装器生命周期验收仍需干净测试机。
