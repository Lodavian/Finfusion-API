# 行情接口契约 0.2.0-rc1

五个接口沿用现有 FINFUSION-V1 八行签名。路径含原始编码后的查询串，空请求体；HTTP/WS 均签名。不增加 Casdoor 或券商认证入口。

| GET 路由 | 输入 | 返回 |
|---|---|---|
| /v1/market/symbols | accountRef、q（完整美股代码） | accountRef、symbols[]：symbol/name/exchange/subCategory |
| /v1/market/snapshot | accountRef、symbol | MarketSnapshot |
| /v1/market/trades | accountRef、symbol、limit=50（1–200） | accountRef、symbol、status、trades[] |
| /v1/market/events | accountRef、symbol | 签名 WebSocket connected、market.update |
| /v1/accounts/{accountRef}/ui-context | 路径授权账户 | environment、tradeEnabled、tradeAuthorized、serverReady、cancelEnabled、controlVersion、riskRules |

所有接口校验当前客户端读取权限、用户启用状态与账户归属。未知/禁用账户返回 ACCESS_DENIED/403。券商 HTTP 401/403 返回 MARKET_DATA_DENIED/403，其他源不可用返回 MARKET_DATA_UNAVAILABLE/503。查询失败不启动任何交易，也不改变服务器订单风控。

MarketSnapshot：accountRef、symbol、version（非负整数）、currency=USD、lastPrice、change、changePercent、open/high/low/volume、bid/ask（各 null 或 {price,size}）、spread、asOf、receivedAt、可选 bookAsOf、status。

价格、数量、涨跌采用十进制字符串；缺失 null。时间戳为 UTC Unix 秒。change_ratio 乘 100 后输出 changePercent；只输出常规交易时段数据，不用盘前/盘后字段补造。没有有效来源时间戳不能标记 READY。READY=有效价格、共享数据连接健康、来源时间在 quoteStaleSeconds 内；STALE=已有价格但过期/失去连接/没有时间戳；UNAVAILABLE=无有效价格。DENIED 经安全错误响应或客户端断线状态显示。

最近成交：id、time、price、size、side（BUY/SELL 或 null），最多 200 条，按时间倒序去重。不把方向未知推断为买/卖。WS 的 market.update 包含 snapshot 与 trades 两个同账户同股票对象；行情 version 在服务器重启后可重置，客户端每次重新连接以 REST 快照重新建立版本基准。

行情服务复用现有 DataClient、MQTT 流、_call 限流器、订阅引用计数。服务器共享 2 秒 REST 快照/盘口/成交缓存，并接收现有 MQTT 的白名单更新，每个 socket 独立推送与两秒发送超时；同股票用户共享缓存，慢 socket 不在其他用户推送路径中。缓存最多 256 股票，成交最多 200 条。这里只读行情，不改变 gateway.fresh_price 或交易价格缓存的既有计算。

每个 WS 独立 market:UUID 引用；换股、断开、失败、撤权均释放。最长 300 秒后重新签名。订阅只读，非法客户端消息关闭。推送前重新校验账户权限。现有 /v1/events 继续仅处理订单，协议不变。

ui-context 的 tradeAuthorized 是管理员权限组合；tradeEnabled 还需数据库、券商事件、行情、订单对账、节点与 Tunnel 就绪。仅显示公开风险规则：maxOrderQty/maxOrderValue/maxMarketQty/maxMarketEstimatedValue/maxDailyGrossNotional/maxOpenOrders/quoteStaleSeconds/DAY/CORE。最终是否接受订单仍由交易路由决定。

隔离实现没有部署，实际 Webull HK 2.0.18 行情返回格式及数据许可需要真实权限联调。已有 SDK protobuf Snapshot/Quote 已用真实消息类型构造测试。文档与实际路由、OpenAPI 自动匹配。
