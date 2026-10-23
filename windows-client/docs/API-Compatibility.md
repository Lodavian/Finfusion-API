# 服务端接口核对

核查基线：Lodavian/Finfusion-API `f581d3b7fc7ad42dbe07c234b48771c0fda778d8`。实际 ServerApi 路由、docs/API.md 和 docs/openapi.json 已只读核对。完整服务器具有本客户端需要的接口，无需新增服务端接口。

| 功能 | 路由 | 处理 |
|---|---|---|
| 账户 / 鉴权 | GET /v1/accounts | 返回授权账户，单账户自动选择 |
| 持仓 | GET /v1/accounts/{accountRef}/positions | symbol/name/lastPrice/quantity/unitCost/unrealizedPnl |
| 购买力 | GET /v1/accounts/{accountRef}/balance | USD，usdBuyingPower 可为 null |
| 下单 | POST /v1/orders | accountRef/symbol/side/orderType/quantity；LIMIT 才发送 limitPrice |
| 改单 | PATCH /v1/orders/{clientOrderId} | 仅 accountRef/limitPrice |
| 撤单 | POST /v1/orders/{clientOrderId}/cancel | 仅 accountRef |
| 订单列表 | GET /v1/orders | accountRef、limit=200、cursor 分页 |
| 详情 | GET /v1/orders/{clientOrderId} | query 必须带 accountRef |
| 原请求 | GET /v1/requests/{requestId} | query 必须带 accountRef；原请求编号不变 |
| 事件 | GET /v1/events | 签名 WebSocket 握手，order.update.order |
| 就绪 | GET /readyz | 503 不能等同鉴权失败；显示服务器报告的开关状态 |

接口对接注意：

- 签名八行包含 FINFUSION-V1、clientId、HTTP 方法、原始路径和查询、原始 body SHA-256、时间戳、nonce、Idempotency-Key，末尾无换行。
- SDK 签名实现原样复制。发送与持久化使用相同紧凑 UTF-8 JSON，ensure_ascii=False、allow_nan=False；查询由 urlencode 生成，yarl URL(encoded=True) 避免二次转义。
- POST/PATCH 交易的 UUID 在持久化成功后才发送；每次查询使用新 nonce，不重放原交易签名。
- 三种修改均返回 202 的 order.update 对象；requestId 字段通常是原下单编号，不能拿它替代本地保存的改单/撤单请求编号。
- 正式源码保留 /v1/symbols/select，OpenAPI 也列为可选预热；API.md 没有逐项展开该路由。本版不依赖它，服务器下单会自行准备行情。
- 查询没找到原请求返回 INVALID_REQUEST / HTTP 400，不是“确认交易失败”。客户端保持待确认。
- 普通用户签名认证无需 Bearer JWT；Casdoor 仅用于管理员。这与旧 Android 的 X-Device-Id 协议不同。
- 旧极速下单界面的可卖数量、市值、实时行情等并不都存在于当前服务端白名单；本版只显示实际字段，不虚构数据。

当前部署缺口（部署模式，非正式源码缺口）：连接验证服务只开放 livez、readyz、connection、accounts、orders、events，未开放本表其他接口。联调前需管理员另行准备正式服务器及授权 Webull 账户。本次不改变该服务。
