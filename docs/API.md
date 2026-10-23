# Finfusion API v1

基础地址是管理员提供的 HTTPS origin。完整 HTTP 路由和字段见 `openapi.json`。管理员 `/admin/v1/*` 使用 Casdoor Bearer JWT；用户 `/v1/*` 只使用签名客户端身份。

## 签名协议

必需请求头：`X-Client-Id`、`X-Timestamp`（Unix 秒）、`X-Nonce`（16–128 字符）、`X-Client-Signature`。交易 POST/PATCH 还必须提供 UUID 格式的 `Idempotency-Key`。重复签名头、重复查询参数被拒绝。

以下八行按 UTF-8 编码，以单个 LF 分隔，末尾没有 LF：

```text
FINFUSION-V1
clientId
大写 HTTP 方法
原始请求路径与查询字符串
原始请求体字节的 SHA-256 小写十六进制
X-Timestamp 原文
X-Nonce 原文
Idempotency-Key 原文，没有时为空串
```

使用 P-256 ECDSA + SHA-256 签名，签名为 ASN.1 DER 字节的 Base64URL 编码，去掉末尾 `=`。服务端允许 30 秒时钟偏差；nonce 保留 120 秒，生产环境同时写入 PostgreSQL，重启不会重置这段时间内的重放保护。查询串顺序及转义必须与线上实际发送字节一致。

`client_sdk` 使用相同协议但独立实现签名，默认只接受 HTTPS；测试时可显式允许 loopback HTTP。不会跟随重定向转发签名请求。用户私钥不会传到服务器。

## 下单、改单、撤单

```json
{"accountRef":"授权账户引用","symbol":"AAPL","side":"BUY","orderType":"LIMIT","quantity":1,"limitPrice":"100.00"}
```

MARKET 不提供限价。数量必须为正整数，价格用十进制字符串。真实账户号、时段及券商额外字段不允许由用户指定。

- `POST /v1/orders` 下单；`PATCH /v1/orders/{clientOrderId}` 只修改限价，body 是 `accountRef`、`limitPrice`。
- `POST /v1/orders/{clientOrderId}/cancel` 的 body 只有 `accountRef`。
- 三类操作均返回 HTTP 202 和 `order.update` 对象。202 表示接口已处理请求，不保证成交。
- 在发送前保存 UUID 请求编号。同一账户、同一编号、相同请求内容只调用一次券商；同编号不同内容返回 409。下单幂等摘要不包含实时行情价格。
- 重复请求返回订单当前状态，`requestId` 是原始下单编号；改单/撤单各自的请求编号也可通过 requests 接口查询同一订单。
- 网络超时后，先调用 `GET /v1/requests/{requestId}?accountRef=...`。不得生成新编号自动重下原订单。
- 如果原请求从未到达服务器，查询可能找不到；调用方应让操作者确认，不自动推断订单失败。

订单状态包含 `RECEIVED`、`PREPARED`、`SENDING`、`ACKNOWLEDGED`、`SUBMITTED`、`OPEN`、`PARTIAL_FILLED`、`REPLACE_REQUESTED`、`REPLACED`、`CANCEL_REQUESTED`、`UNKNOWN`、`REJECTED`、`CANCELLED`、`FILLED`。`ACKNOWLEDGED` 不等于成交，`CANCEL_REQUESTED` 不等于已撤单。

UNKNOWN 会阻止该账户继续新单和改单。启动及后台每 10 秒对账；对于结果不确定的改单/撤单，仅看到 OPEN 不足以判断操作结果，因此保留 `pendingAction` 并等待明确事件或终态。

## 查询和订阅

- `GET /v1/accounts` 只返回已授权账户及脱敏尾号。
- `GET /v1/accounts/{accountRef}/positions` 返回 USD 股票/ETF 的白名单字段，不返回原始券商对象。
- `GET /v1/accounts/{accountRef}/balance` 返回 `currency=USD`、`usdBuyingPower`；无可用数据时购买力为 null，不能当作零。
- `GET /v1/orders` 支持 `accountRef`、`limit`（1–200）、`cursor`；单笔订单查询和请求查询必须带 `accountRef`。
- `GET /v1/events` 是带签名请求头的 WebSocket 握手。连接先发送 `connected`，随后发送可见账户的 `order.update`。相同订单按 `version` 去重。
- WebSocket 最长五分钟后要求重签连接；客户端权限撤销会断开。账户解绑后不再推送该账户事件。事件流不保证离线重放，重连先查询订单，再继续订阅。

## 管理客户端

管理员登记 `userId`、`label`、`publicKeyPem`，新客户端默认禁用、只具有查询权限。PATCH 客户端可更新 `enabled`、`canRead`、`canTrade`、`canCancel`。提交 `publicKeyPem` 即轮换，旧公钥立即失效，客户端再次进入禁用状态；必须随后单独批准。

普通用户无须 Casdoor 登录。管理员网页仍可创建/禁用用户、注册/分配账户、修改交易开关和管理客户端。

## 错误与限流

响应结构：`{"error":{"code":"...","message":"..."}}`。

| code | HTTP | 意义 |
|---|---:|---|
| INVALID_REQUEST | 400 | 字段、风险限制或交易条件不满足 |
| ACCESS_DENIED | 403 | 签名、重放、用户、客户端或账户权限失败 |
| IDEMPOTENCY_CONFLICT | 409 | 同一请求编号对应不同操作或内容 |
| RATE_LIMITED | 429 | 单客户端超过 60 请求/秒、突发 120 的本地保护额度 |
| MARKET_NOT_READY | 503 | 尚无新鲜行情，没有发送订单 |
| NODE_NOT_READY | 503 | 节点或 Tunnel 未就绪 |
| BROKER_NOT_READY | 503 | 发送前券商链路检查未通过 |
| INTERNAL_ERROR | 500 | 内部失败；交易操作须查询原请求，不能据此认定未成交 |
| HTTP_ERROR | 对应 HTTP 状态 | 路由、方法或请求大小错误 |

券商调用共享 15 次/秒令牌桶，这是项目的初始本地限制，生产上线前须根据机构权限及实测确认，不能视为券商额度保证。错误返回和订单对象不包含 Webull 凭据。

## Client 0.2 market extension
See [MARKET.md](MARKET.md). All five new GET routes use the unchanged FINFUSION-V1 signature, including encoded query string. No order route or event schema changed.

Balance adds usdCashBalance, usdSettledCash, usdUnsettledCash from USD currency assets only; decimals are strings, missing values null. Existing usdBuyingPower and trading gateway balance semantics remain unchanged.

## Server 1.0
Signed GET /v1/info returns product, version, apiProtocol, deploymentMode and capabilities. ui-context adds serverVersion, deploymentMode, tradeDeploymentAllowed; READ_ONLY always denies trading and permission escalation. FINFUSION-V1 signing and order semantics are unchanged.
