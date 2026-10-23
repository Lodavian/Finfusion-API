import asyncio
from contextlib import suppress
from decimal import Decimal, InvalidOperation
import json
from urllib.parse import quote

from .storage import BusyError, OPEN
from .transport import ApiFailure

STATUS = {
    "RECEIVED": "服务器收到", "PREPARED": "准备中", "SENDING": "发送中",
    "ACKNOWLEDGED": "券商接受（未成交）", "SUBMITTED": "已提交（未成交）",
    "OPEN": "挂单", "PARTIAL_FILLED": "部分成交", "FILLED": "已成交",
    "REPLACE_REQUESTED": "改单请求中", "REPLACED": "已修改（未成交）",
    "CANCEL_REQUESTED": "撤单请求中", "CANCELLED": "已撤销",
    "REJECTED": "拒绝", "UNKNOWN": "待确认",
}


def status_text(status):
    return f"{STATUS.get(status, '未知状态')} [{status}]"


def order_from(data, account_ref=None, target=None):
    order = data.get("order", data)
    if (not isinstance(order, dict) or not isinstance(order.get("clientOrderId"), str) or
            not order["clientOrderId"] or not isinstance(order.get("accountRef"), str) or
            not isinstance(order.get("status"), str) or order["status"] not in STATUS or type(order.get("version")) is not int or
            order["version"] < 1 or (account_ref and order["accountRef"] != account_ref) or
            (target and order["clientOrderId"] != target)):
        raise ApiFailure("INVALID_RESPONSE")
    return dict(order)


def request_phase(order):
    return "OPERATION_PENDING" if order["status"] in {
        "UNKNOWN", "RECEIVED", "PREPARED", "SENDING", "CANCEL_REQUESTED", "REPLACE_REQUESTED"
    } or order.get("pendingAction") else "RESOLVED"


def order_payload(account, symbol, side, kind, quantity, price):
    symbol = symbol.strip().upper()
    if not symbol or len(symbol) > 32 or any(char.isspace() for char in symbol):
        raise ValueError("请输入股票代码")
    if side not in {"BUY", "SELL"} or kind not in {"MARKET", "LIMIT"}:
        raise ValueError("请选择买卖方向及订单类型")
    if not str(quantity).isascii() or not str(quantity).isdigit() or int(quantity) < 1:
        raise ValueError("数量必须是正整数股数")
    result = {"accountRef": account, "symbol": symbol, "side": side,
              "orderType": kind, "quantity": int(quantity)}
    if kind == "LIMIT":
        result["limitPrice"] = price_text(price)
    return result


def price_text(value):
    try:
        price = Decimal(str(value).strip())
        if not price.is_finite() or price <= 0:
            raise ValueError()
        return format(price, "f")
    except (InvalidOperation, ValueError):
        raise ValueError("限价必须是正数") from None


class Engine:
    def __init__(self, journal, notify=lambda *_: None):
        self.journal, self.notify = journal, notify
        self.transport = None
        self.connected = False
        self.accounts = []
        self.selected = None
        self.generation = 0
        self.session_generation = 0
        self.orders = {}
        self.event_task = None
        self.stopping = False
        self.backoff = (1, 2, 4, 8, 16, 30)

    def emit(self, kind, data, generation=None):
        self.notify(kind, data, generation)

    def choose(self, account_ref):
        if account_ref is not None and account_ref not in {a["accountRef"] for a in self.accounts}:
            raise ValueError("只能选择服务器返回的授权账户")
        self.selected = account_ref
        self.generation += 1
        return self.generation

    async def connect(self, transport, *, start_events=True):
        await self.stop()
        self.transport, self.stopping = transport, False
        token = self.session_generation
        self.orders.clear()
        self.emit("connection", "正在进行签名鉴权")
        try:
            await self.refresh_accounts()
            if token != self.session_generation:
                raise ApiFailure("NETWORK_UNCERTAIN")
        except Exception:
            if token == self.session_generation:
                self.connected = False
            await transport.close()
            raise
        self.connected = True
        self.emit("connection", "HTTPS 可达 · 签名鉴权成功")
        try:
            readiness = await transport.request("GET", "/readyz", allowed_statuses=(503,))
            if token == self.session_generation:
                self.emit("readiness", readiness)
        except ApiFailure:
            self.emit("readiness", {})
        if start_events and token == self.session_generation:
            self.event_task = asyncio.create_task(self.event_loop())

    async def refresh_accounts(self):
        token = self.session_generation
        data = await self.transport.request("GET", "/v1/accounts")
        if token != self.session_generation:
            raise ApiFailure("NETWORK_UNCERTAIN")
        accounts = data.get("accounts")
        if not isinstance(accounts, list) or any(not isinstance(a, dict) or
                not isinstance(a.get("accountRef"), str) or not a["accountRef"] for a in accounts):
            raise ApiFailure("INVALID_RESPONSE")
        self.accounts = accounts
        if self.selected not in {a["accountRef"] for a in accounts}:
            self.choose(accounts[0]["accountRef"] if len(accounts) == 1 else None)
        self.emit("accounts", accounts)

    def merge(self, order):
        order = order_from(order)
        if order["accountRef"] not in {a["accountRef"] for a in self.accounts}:
            return False
        key = (order["accountRef"], order["clientOrderId"])
        old = self.orders.get(key)
        if old and old["version"] >= order["version"]:
            return False
        self.orders[key] = order
        return True

    def publish_orders(self, generation=None):
        self.emit("orders", [dict(v) for (a, _), v in self.orders.items() if a == self.selected],
                  self.generation if generation is None else generation)

    async def refresh(self, cursor=None, *, recover=True):
        ref, generation = self.selected, self.generation
        if not ref or not self.connected:
            return
        escaped = quote(ref, safe="")
        queries = [
            ("positions", f"/v1/accounts/{escaped}/positions", None),
            ("balance", f"/v1/accounts/{escaped}/balance", None),
            ("order_page", "/v1/orders", {"accountRef": ref, "limit": 200, **({"cursor": cursor} if cursor else {})}),
        ]
        async def read(kind, path, query):
            try:
                data = await self.transport.request("GET", path, query=query)
                if generation != self.generation or ref != self.selected:
                    return
                if kind == "order_page":
                    if not isinstance(data.get("orders"), list):
                        raise ApiFailure("INVALID_RESPONSE")
                    for raw in data["orders"]:
                        self.merge(order_from(raw, ref))
                    self.publish_orders(generation)
                    self.emit("cursor", data.get("nextCursor"), generation)
                else:
                    if data.get("accountRef") != ref:
                        raise ApiFailure("INVALID_RESPONSE")
                    self.emit(kind, data, generation)
            except ApiFailure as exc:
                if generation == self.generation:
                    self.emit("read_error", {"kind": kind, "code": exc.code, "status": exc.status}, generation)
        await asyncio.gather(*(read(*q) for q in queries))
        if recover:
            await self.reconcile()
        # Orders outside the latest page still need updates after a disconnect.
        stale = [v for (a, _), v in list(self.orders.items()) if a == ref and
                 v["status"] not in {"FILLED", "CANCELLED", "REJECTED"}]
        for order in stale:
            if generation != self.generation:
                return
            try:
                await self.detail(order["clientOrderId"], emit=False)
            except ApiFailure:
                pass
        if generation == self.generation:
            self.publish_orders(generation)

    async def detail(self, order_id, *, emit=True):
        ref, generation = self.selected, self.generation
        data = await self.transport.request("GET", f"/v1/orders/{quote(order_id, safe='')}", query={"accountRef": ref})
        order = order_from(data, ref, order_id)
        if generation == self.generation and ref == self.selected:
            self.merge(order)
            self.publish_orders(generation)
            if emit:
                self.emit("detail", order, generation)
        return order

    def prepare(self, operation, payload, target=""):
        if not self.connected or not self.transport or not self.selected:
            raise BusyError("请先完成签名鉴权并选择授权账户")
        if payload.get("accountRef") != self.selected:
            raise BusyError("账户选择已改变，请重新操作")
        paths = {"submit": ("POST", "/v1/orders"),
                 "replace": ("PATCH", f"/v1/orders/{quote(target, safe='')}"),
                 "cancel": ("POST", f"/v1/orders/{quote(target, safe='')}/cancel")}
        method, path = paths[operation]
        return self.journal.reserve(self.transport.origin, self.transport.client_id,
                                    self.selected, operation, method, path, payload, target)

    async def dispatch(self, intent):
        request_id = intent["request_id"]
        if not self.journal.begin_send(request_id):
            raise BusyError("该请求已发送或进入恢复状态，不会再次提交")
        try:
            if not self.transport or (intent["origin"], intent["client_id"]) != (
                    self.transport.origin, self.transport.client_id) or not self.connected:
                raise ApiFailure("NETWORK_UNCERTAIN")
            data = await self.transport.request(intent["method"], intent["path"],
                                                body=intent["body"], request_id=request_id)
            order = order_from(data, intent["account_ref"], intent["target"] or None)
            self.journal.update(request_id, request_phase(order), order_id=order["clientOrderId"])
            self.merge(order)
            self.publish_orders()
        except ApiFailure as exc:
            # Only contract-shaped explicit refusals are definitive. 409 may refer to an existing request.
            phase = "REFUSED" if exc.code in {"ACCESS_DENIED", "INVALID_REQUEST", "RATE_LIMITED",
                    "MARKET_NOT_READY", "NODE_NOT_READY", "BROKER_NOT_READY", "READ_ONLY_DEPLOYMENT"} and exc.status in {400, 403, 429, 503} else "UNCERTAIN"
            self.journal.update(request_id, phase, exc.code)
            raise
        except BaseException:
            self.journal.update(request_id, "UNCERTAIN", "NETWORK_UNCERTAIN")
            raise
        finally:
            self.emit("pending", self.journal.pending())

    async def reconcile(self):
        if not self.transport:
            return
        for intent in self.journal.pending(self.transport.origin, self.transport.client_id):
            if intent['phase'] in {'PREPARED', 'SENDING'}:
                # A live dispatch owns this record. Startup converts abandoned records to UNCERTAIN.
                continue
            try:
                data = await self.transport.request("GET", f"/v1/requests/{intent['request_id']}",
                                                    query={"accountRef": intent["account_ref"]})
                order = order_from(data, intent["account_ref"], intent["target"] or None)
                self.journal.update(intent["request_id"], request_phase(order), order_id=order["clientOrderId"])
                self.merge(order)
            except ApiFailure as exc:
                # Not found / permission refusal does not prove the mutation failed.
                self.journal.update(intent["request_id"], "UNCERTAIN", exc.code)
        self.emit("pending", self.journal.pending())
        self.publish_orders()

    async def event_loop(self):
        attempts = 0
        while not self.stopping:
            try:
                await self.refresh_accounts()
                await self.refresh()
                async for event in self.transport.events():
                    if event.get("type") == "connected":
                        attempts = 0
                        self.emit("events", "订单事件已连接")
                        await self.refresh()
                    elif event.get("type") == "order.update":
                        if self.merge(order_from(event)):
                            self.publish_orders()
                        # Resolve command IDs using the authoritative request lookup, not unrelated events.
                        if self.journal.pending(self.transport.origin, self.transport.client_id):
                            await self.reconcile()
                if self.stopping:
                    break
                raise ApiFailure("NETWORK_UNCERTAIN")
            except asyncio.CancelledError:
                raise
            except ApiFailure as exc:
                if exc.status == 403:
                    self.connected = False
                    self.emit("connection", "公网入口拒绝程序访问，请检查入口规则" if exc.code == "EDGE_BLOCKED" else "鉴权/权限被拒绝，请重新连接")
                    self.emit("events", "事件连接已停止")
                    break
                self.emit("events", "事件断线 · 正在查询并重连")
            except Exception:
                self.emit("events", "事件暂不可用 · 正在查询并重连")
            await asyncio.sleep(self.backoff[min(attempts, len(self.backoff) - 1)])
            attempts += 1

    async def stop(self):
        self.stopping, self.connected = True, False
        self.session_generation += 1
        self.choose(None)
        if self.event_task:
            self.event_task.cancel()
            with suppress(asyncio.CancelledError):
                await self.event_task
            self.event_task = None
        if self.transport:
            await self.transport.close()
            self.transport = None
        self.emit("events", "订单事件未连接")
