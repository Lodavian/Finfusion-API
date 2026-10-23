from __future__ import annotations

import json
import base64
import asyncio
import logging
import math
import binascii
import re
import time
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Any, Awaitable, Callable, Mapping

from aiohttp import WSMsgType, web

from finfusion_common.utils import normalize_symbol, redact_text

from .controls import AccessDenied, ControlPlane
from .models import Principal
from .security import RequestAuthenticator, RequestProof, TokenVerifier
from .service import InstitutionalTradingService
from .admin import AdminService
from .infrastructure import InfrastructureGate
from .errors import ApiError, IdempotencyConflict
from .market import MarketData
from .account_view import read_cash_fields
from . import __version__
from .deployment import readonly_perimeter


DEVICE_LABEL_RE = re.compile(r"^[\w .()\-]{1,80}$", re.UNICODE)
IDEMPOTENCY_KEY = web.RequestKey("idempotency_key", str)


class EventHub:
    def __init__(self, controls: ControlPlane):
        self.controls = controls
        self._sockets: dict[tuple[str, str], set[web.WebSocketResponse]] = defaultdict(set)

    async def publish(self, event: dict[str, Any]) -> None:
        user_id = str(event.get("_userId") or "")
        public = {key: value for key, value in event.items() if not key.startswith("_")}
        stale: list[web.WebSocketResponse] = []
        sockets = []
        account_ref = str(public.get("order", {}).get("accountRef") or "")
        for (owner, client_id), group in tuple(self._sockets.items()):
            if owner != user_id:
                continue
            try:
                self.controls.resolve(Principal(owner, client_id), account_ref, mutation="read")
            except AccessDenied:
                continue
            sockets.extend(tuple(group))
        for socket in sockets:
            try:
                await asyncio.wait_for(socket.send_json(public), timeout=2)
            except Exception:
                stale.append(socket)
        for socket in stale:
                for key in tuple(self._sockets):
                    self._sockets[key].discard(socket)

    def add(self, principal: Principal, socket: web.WebSocketResponse) -> None:
        self._sockets[(principal.user_id, principal.client_id)].add(socket)

    def discard(self, principal: Principal, socket: web.WebSocketResponse) -> None:
        self._sockets[(principal.user_id, principal.client_id)].discard(socket)

    async def revoke_user(self, user_id: str) -> None:
        for key in [item for item in self._sockets if item[0] == user_id]:
            for socket in tuple(self._sockets.pop(key, ())):
                await socket.close(code=1008, message=b"authorization revoked")

    async def revoke_client(self, client_id: str) -> None:
        for key in [item for item in self._sockets if item[1] == client_id]:
            for socket in tuple(self._sockets.pop(key, ())):
                await socket.close(code=1008, message=b"client revoked")


class ServerApi:
    def __init__(
        self,
        service: InstitutionalTradingService,
        controls: ControlPlane,
        authenticator: RequestAuthenticator,
        tokens: TokenVerifier,
        *,
        register_client: Callable[[str, str, str], Awaitable[tuple[str, Any]]] | None = None,
        set_control: Callable[[str, str | None, bool, str, str], Awaitable[Any]] | None = None,
        set_client_enabled: Callable[[str, bool, str], Awaitable[Any]] | None = None,
        admin_role: str = "finfusion-admin",
        admin_service: AdminService | None = None,
        admin_static_dir: Path | None = None,
        admin_oidc_config: Mapping[str, str] | None = None,
        database_healthy: Callable[[], Awaitable[bool]] | None = None,
        record_login: Callable[[str, str], Awaitable[None]] | None = None,
        record_rejection: Callable[[str, str, str], Awaitable[None]] | None = None,
        infrastructure: InfrastructureGate | None = None,
        environment_name: str = "UNKNOWN",
        market_data: MarketData | None = None,
        consume_nonce: Callable[[str, str], Awaitable[None]] | None = None,
        deployment_mode: str = "STANDARD",
    ):
        if deployment_mode not in {"STANDARD", "READ_ONLY"}:
            raise ValueError("Unknown deployment mode")
        self.deployment_mode = deployment_mode
        self.market_data = market_data or MarketData(service.gateway, service.limits.quote_stale_seconds)
        self.environment_name = environment_name
        self.service = service
        self.controls = controls
        self.authenticator = authenticator
        self.tokens = tokens
        self.register_client_callback = register_client
        self.set_control_callback = set_control
        self.set_client_callback = set_client_enabled
        self.admin_role = admin_role
        self.admin_service = admin_service
        self.admin_static_dir = admin_static_dir
        self.admin_oidc_config = dict(admin_oidc_config or {})
        self.database_healthy = database_healthy
        self.record_login = record_login
        self.record_rejection = record_rejection
        self.infrastructure = infrastructure or InfrastructureGate()
        self.consume_nonce = consume_nonce
        self._admin_lock = asyncio.Lock()
        self._recorded_sessions: set[tuple[str, str]] = set()
        self.events = EventHub(controls)
        self.started_at = time.time()
        self.service.publisher = self.events.publish

    def application(self) -> web.Application:
        middlewares = [self.error_middleware]
        if self.deployment_mode == "READ_ONLY": middlewares.insert(0, readonly_perimeter)
        app = web.Application(client_max_size=16 * 1024, middlewares=middlewares)
        app.add_routes(
            [
                web.get("/livez", self.livez),
                web.get("/readyz", self.readyz),
                web.get("/v1/info", self.info),
                web.post("/admin/v1/clients", self.register_client),
                web.patch("/admin/v1/clients/{client_id}", self.configure_client),
                web.get("/v1/accounts", self.accounts),
                web.get("/v1/accounts/{account_ref}/ui-context", self.ui_context),
                web.get("/v1/market/symbols", self.market_symbols),
                web.get("/v1/market/snapshot", self.market_snapshot),
                web.get("/v1/market/trades", self.market_trades),
                web.get("/v1/market/events", self.market_events),
                web.get("/v1/accounts/{account_ref}/positions", self.positions),
                web.get("/v1/accounts/{account_ref}/balance", self.balance),
                web.post("/v1/symbols/select", self.select_symbol),
                web.post("/v1/orders", self.submit_order),
                web.patch("/v1/orders/{client_order_id}", self.replace_order),
                web.post("/v1/orders/{client_order_id}/cancel", self.cancel_order),
                web.get("/v1/orders", self.orders),
                web.get("/v1/orders/{client_order_id}", self.order_detail),
                web.get("/v1/requests/{request_id}", self.request_result),
                web.get("/v1/events", self.websocket),
                web.post("/admin/v1/controls/{scope}", self.admin_control),
                web.post("/admin/v1/clients/{client_id}", self.admin_client),
                web.get("/admin/v1/state", self.admin_state),
                web.post("/admin/v1/users", self.admin_create_user),
                web.post("/admin/v1/users/{user_id}/status", self.admin_user_status),
                web.post("/admin/v1/users/{user_id}/password", self.admin_reset_password),
                web.post("/admin/v1/accounts", self.admin_add_account),
                web.post("/admin/v1/bindings", self.admin_bind),
                web.post("/admin/v1/bindings/{account_ref}/remove", self.admin_unbind),
                web.get("/admin/config", self.admin_config),
            ]
        )
        if self.admin_static_dir is not None:
            app.router.add_get("/admin/", self.admin_index)
            app.router.add_static("/admin/", self.admin_static_dir, show_index=False)
        return app

    @web.middleware
    async def error_middleware(self, request: web.Request, handler: Callable[..., Awaitable[web.StreamResponse]]) -> web.StreamResponse:
        try:
            if request.path.startswith("/admin/v1/") and request.method != "GET":
                async with self._admin_lock:
                    response = await handler(request)
            else:
                response = await handler(request)
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["Cache-Control"] = "no-store"
            response.headers["Referrer-Policy"] = "no-referrer"
            response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
            if request.path.startswith("/admin"):
                response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self' https:; frame-ancestors 'none'; base-uri 'none'; form-action 'self' https:"
            return response
        except ApiError as exc:
            return self._error(str(exc), exc.status, exc.code)
        except IdempotencyConflict as exc:
            return self._error(str(exc), 409, "IDEMPOTENCY_CONFLICT")
        except AccessDenied as exc:
            if self.record_rejection is not None:
                try:
                    await self.record_rejection(request.headers.get("X-Client-Id", ""), request.path, redact_text(exc, 200))
                except Exception:
                    logging.getLogger("finfusion.audit").warning("拒绝事件审计写入失败")
            return self._error(str(exc), 403, "ACCESS_DENIED")
        except (ValueError, RuntimeError) as exc:
            logging.getLogger("finfusion").warning("Request rejected: %s", type(exc).__name__)
            return self._error(str(exc), 400)
        except web.HTTPException as exc:
            return self._error(exc.reason, exc.status, "HTTP_ERROR")
        except Exception:
            logging.getLogger("finfusion").exception("Unhandled API failure")
            return self._error("操作失败，请按 Idempotency-Key 查询原请求状态", 500, "INTERNAL_ERROR")

    async def info(self, request: web.Request) -> web.Response:
        principal = await self._principal(request)
        if not self.controls.authorize(principal).can_read:
            raise AccessDenied("客户端无读取权限")
        operations = {"status":"UNKNOWN", "issues":[]}
        try:
            value = json.loads(Path("/var/lib/finfusion/ops/health.json").read_text())
            if value.get("status") in {"OK","WARNING","ALERT"} and isinstance(value.get("issues"),list):
                operations = {"status":value["status"], "issues":[x for x in value["issues"] if isinstance(x,str) and re.fullmatch(r"[A-Z_]{1,48}",x)],
                    "checkedAt":value.get("checkedAt"), "backupStatus":value.get("backupStatus")}
        except (OSError,ValueError,TypeError):
            pass
        return web.json_response({"product":"Finfusion Server 1.0", "version":__version__,
            "apiProtocol":"FINFUSION-V1", "deploymentMode":self.deployment_mode,
            "operations":operations,
            "capabilities":["accounts","positions","usd-cash","orders","order-events","market-events","durable-idempotency"]})

    async def livez(self, _request: web.Request) -> web.Response:
        return web.json_response({"ok": True, "uptimeSeconds": int(time.time() - self.started_at)})

    async def readyz(self, _request: web.Request) -> web.Response:
        database_ready = await self.database_healthy() if self.database_healthy is not None else True
        events_ready = bool(getattr(self.service.gateway, "events_healthy", False))
        reconciliation_ready = self.service.reconciliation_ready
        infrastructure = self.infrastructure.snapshot
        market_ready = bool(getattr(self.service.gateway, "market_healthy", False))
        ready = database_ready and events_ready and market_ready and reconciliation_ready and infrastructure.mutation_ready
        effective = ready and self.controls.snapshot.global_trade_enabled
        return web.json_response(
            {
                "ok": ready,
                "database": database_ready,
                "brokerEvents": events_ready,
                "market": market_ready,
                "reconciliation": reconciliation_ready,
                "tunnel": infrastructure.tunnel_healthy,
                "nodeActive": infrastructure.node_active,
                "globalTradeEnabled": self.controls.snapshot.global_trade_enabled,
                "effectiveTradeEnabled": effective,
                "infrastructureReason": infrastructure.reason,
            },
            status=200 if ready else 503,
        )

    async def register_client(self, request: web.Request) -> web.Response:
        if self.register_client_callback is None:
            raise RuntimeError("客户端登记服务未配置")
        claims = self._admin_claims(request)
        payload = await self._json(request)
        if set(payload) != {"userId", "label", "publicKeyPem"}:
            raise ValueError("客户端登记字段无效")
        user_id = str(payload["userId"])
        label = str(payload.get("label") or "").strip()
        public_key = str(payload.get("publicKeyPem") or "").strip()
        if not DEVICE_LABEL_RE.fullmatch(label):
            raise ValueError("客户端名称无效")
        self._validate_public_key(public_key)
        client_id, snapshot = await self.register_client_callback(user_id, label, public_key)
        self.controls.replace(snapshot)
        return web.json_response({"clientId": client_id, "status": "PENDING_ADMIN_APPROVAL"}, status=201)

    async def configure_client(self, request: web.Request) -> web.Response:
        claims = self._admin_claims(request)
        if self.admin_service is None:
            raise RuntimeError("管理服务未配置")
        payload = await self._json(request)
        if not payload or set(payload) - {"enabled", "publicKeyPem", "canRead", "canTrade", "canCancel"}:
            raise ValueError("客户端配置字段无效")
        for key in {"enabled", "canRead", "canTrade", "canCancel"} & payload.keys():
            if type(payload[key]) is not bool:
                raise ValueError("客户端权限必须是布尔值")
        if "publicKeyPem" in payload:
            self._validate_public_key(payload["publicKeyPem"])
        client_id = request.match_info["client_id"]
        snapshot = await self.admin_service.store.configure_client(client_id, payload, str(claims["sub"]))
        self.controls.replace(snapshot)
        await self.events.revoke_client(client_id)
        return web.json_response({"ok": True, "controlVersion": snapshot.version, "requiresApproval": "publicKeyPem" in payload})

    async def positions(self, request: web.Request) -> web.Response:
        principal = await self._principal(request)
        return web.json_response(await self.service.positions(principal, request.match_info["account_ref"]))

    async def balance(self, request: web.Request) -> web.Response:
        principal = await self._principal(request)
        ref = request.match_info["account_ref"]
        result = await self.service.balance(principal, ref)
        account = self.controls.resolve(principal, ref, mutation="read")
        cash = await read_cash_fields(self.service.gateway, account.broker_account_id)
        self.controls.resolve(principal, ref, mutation="read")
        return web.json_response({**result, **cash})

    async def accounts(self, request: web.Request) -> web.Response:
        principal = await self._principal(request)
        session_key = (principal.user_id, principal.client_id)
        if self.record_login is not None and session_key not in self._recorded_sessions:
            await self.record_login(principal.user_id, principal.client_id)
            self._recorded_sessions.add(session_key)
        return web.json_response({"accounts": await self.service.list_accounts(principal)})

    async def select_symbol(self, request: web.Request) -> web.Response:
        principal = await self._principal(request)
        payload = await self._json(request)
        account_ref = str(payload.get("accountRef") or "")
        self.controls.resolve(principal, account_ref, mutation="select")
        if set(payload) != {"accountRef", "symbol"}:
            raise ValueError("股票选择字段无效")
        symbol = normalize_symbol(payload.get("symbol"))
        selector = getattr(self.service.gateway, "select_symbol", None)
        if callable(selector):
            await selector(f"{principal.user_id}:{principal.client_id}:{account_ref}", symbol)
        price = await self.service.gateway.fresh_price(symbol, self.service.limits.quote_stale_seconds)
        return web.json_response({"accountRef": account_ref, "symbol": symbol, "status": "READY" if price is not None else "BLOCKED"})

    async def submit_order(self, request: web.Request) -> web.Response:
        principal = await self._principal(request, require_idempotency=True)
        event = await self.service.submit(principal, await self._json(request), request[IDEMPOTENCY_KEY])
        return web.json_response(event, status=202)

    async def replace_order(self, request: web.Request) -> web.Response:
        principal = await self._principal(request, require_idempotency=True)
        payload = await self._json(request)
        if set(payload) != {"accountRef", "limitPrice"}:
            raise ValueError("改单只接受 accountRef 和 limitPrice")
        event = await self.service.replace_limit(
            principal, str(payload["accountRef"]), request.match_info["client_order_id"], payload["limitPrice"], request[IDEMPOTENCY_KEY]
        )
        return web.json_response(event, status=202)

    async def cancel_order(self, request: web.Request) -> web.Response:
        principal = await self._principal(request, require_idempotency=True)
        payload = await self._json(request)
        if set(payload) != {"accountRef"}:
            raise ValueError("撤单只接受 accountRef")
        event = await self.service.cancel(
            principal, str(payload["accountRef"]), request.match_info["client_order_id"], request[IDEMPOTENCY_KEY]
        )
        return web.json_response(event, status=202)

    async def orders(self, request: web.Request) -> web.Response:
        principal = await self._principal(request)
        account_ref = request.query.get("accountRef")
        try:
            limit = int(request.query.get("limit", "50"))
            cursor = self._decode_cursor(request.query.get("cursor"))
        except (ValueError, TypeError, binascii.Error, UnicodeDecodeError):
            raise ValueError("订单游标或分页数量无效") from None
        orders, next_cursor = await self.service.list_orders(principal, account_ref, limit, cursor)
        return web.json_response({"orders": orders, "nextCursor": self._encode_cursor(next_cursor)})

    async def order_detail(self, request: web.Request) -> web.Response:
        principal = await self._principal(request)
        account_ref = str(request.query.get("accountRef") or "")
        return web.json_response(await self.service.get_order(principal, account_ref, request.match_info["client_order_id"]))

    async def request_result(self, request: web.Request) -> web.Response:
        principal = await self._principal(request)
        account_ref = str(request.query.get("accountRef") or "")
        try:
            uuid.UUID(request.match_info["request_id"])
        except ValueError:
            raise ValueError("请求ID无效") from None
        return web.json_response(await self.service.get_request(principal, account_ref, request.match_info["request_id"]))

    async def _market_access(self, request):
        principal = await self._principal(request)
        ref = str(request.query.get("accountRef") or request.match_info.get("account_ref") or "")
        self.controls.resolve(principal, ref, mutation="read")
        return principal, ref

    async def ui_context(self, request):
        principal, ref = await self._market_access(request)
        account = next(a for a in self.controls.public_accounts(principal) if a["accountRef"] == ref)
        database_ready = await self.database_healthy() if self.database_healthy is not None else True
        self.controls.resolve(principal, ref, mutation="read")
        ready = bool(database_ready and getattr(self.service.gateway, "events_healthy", False) and
            getattr(self.service.gateway, "market_healthy", False) and self.service.reconciliation_ready and
            self.infrastructure.snapshot.mutation_ready)
        account = next(a for a in self.controls.public_accounts(principal) if a["accountRef"] == ref)
        limits = self.service.limits
        rules = {"maxOrderQty": limits.max_order_qty, "maxOrderValue": str(limits.max_order_value),
                 "maxMarketQty": limits.max_market_qty, "maxMarketEstimatedValue": str(limits.max_market_estimated_value),
                 "maxDailyGrossNotional": str(limits.max_daily_gross_notional), "maxOpenOrders": limits.max_open_orders,
                 "quoteStaleSeconds": limits.quote_stale_seconds, "timeInForce": "DAY", "tradingSession": "CORE"}
        return web.json_response({"accountRef": ref, "environment": self.environment_name,
            "serverVersion":__version__, "deploymentMode":self.deployment_mode,
            "tradeDeploymentAllowed":self.deployment_mode == "STANDARD",
            "tradeEnabled": bool(account["tradeEnabled"] and ready and self.deployment_mode == "STANDARD"), "tradeAuthorized": account["tradeEnabled"], "serverReady": ready, "cancelEnabled": bool(self.controls.authorize(principal).can_cancel and self.deployment_mode == "STANDARD"),
            "controlVersion": account["controlVersion"], "riskRules": rules})

    async def market_symbols(self, request):
        principal, ref = await self._market_access(request)
        symbols = await self.market_data.symbols(request.query.get("q", ""))
        self.controls.resolve(principal, ref, mutation="read")
        return web.json_response({"accountRef": ref, "symbols": symbols})

    async def market_snapshot(self, request):
        principal, ref = await self._market_access(request)
        symbol = normalize_symbol(request.query.get("symbol"))
        snapshot, _trades = await self.market_data.read(symbol)
        self.controls.resolve(principal, ref, mutation="read")
        return web.json_response({**snapshot, "accountRef": ref})

    async def market_trades(self, request):
        principal, ref = await self._market_access(request)
        symbol = normalize_symbol(request.query.get("symbol"))
        count = int(request.query.get("limit", "50"))
        if not 1 <= count <= 200:
            raise ValueError("成交条数必须在 1 到 200 之间")
        snapshot, trades = await self.market_data.read(symbol)
        self.controls.resolve(principal, ref, mutation="read")
        return web.json_response({"accountRef": ref, "symbol": symbol, "status": snapshot["status"], "trades": trades[:count]})

    async def market_events(self, request):
        principal, ref = await self._market_access(request)
        symbol = normalize_symbol(request.query.get("symbol"))
        # Refuse unavailable/denied data before upgrading to WebSocket.
        await self.market_data.read(symbol)
        reference = "market:" + uuid.uuid4().hex
        gateway = self.service.gateway
        socket = web.WebSocketResponse(heartbeat=20, max_msg_size=4096)
        acquired = False
        producer = None
        async def release():
            nonlocal acquired
            if acquired:
                acquired = False
                try:
                    await gateway.release_symbol(reference)
                except Exception:
                    logging.getLogger("finfusion").warning("Market reference release failed; local reference removed")
        try:
            acquired = True
            try:
                await gateway.select_symbol(reference, symbol)
            except Exception as exc:
                if getattr(exc, 'http_status', None) in (401,403):
                    raise ApiError('MARKET_DATA_DENIED','券商行情订阅权限不足',403) from None
                raise ApiError('MARKET_DATA_UNAVAILABLE','券商行情订阅暂不可用',503) from None
            await socket.prepare(request)
            async def publish():
                expiry = time.monotonic() + 300
                while not socket.closed and time.monotonic() < expiry:
                    try:
                        self.controls.resolve(principal, ref, mutation="read")
                    except AccessDenied:
                        await release()
                        await socket.close(code=1008, message=b"authorization revoked")
                        return
                    snapshot, trades = await self.market_data.read(symbol)
                    self.controls.resolve(principal, ref, mutation="read")
                    await asyncio.wait_for(socket.send_json({"type": "market.update", "snapshot": {**snapshot, "accountRef": ref},
                        "trades": {"accountRef": ref, "symbol": symbol, "status": snapshot["status"], "trades": trades[:50]}}), timeout=2)
                    await asyncio.sleep(1)
                await release()
                await socket.close(code=1000, message=b"reauthenticate")
            async def supervise():
                try:
                    await publish()
                except asyncio.CancelledError:
                    raise
                except Exception:
                    await release()
                    await socket.close(code=1011, message=b"market unavailable")
            await socket.send_json({"type": "connected", "accountRef": ref, "symbol": symbol})
            producer = asyncio.create_task(supervise())
            async for message in socket:
                if message.type == WSMsgType.TEXT and message.data != "ping":
                    await socket.close(code=1008, message=b"read-only stream")
                elif message.type == WSMsgType.ERROR:
                    break
        finally:
            await asyncio.shield(release())
            if producer:
                producer.cancel()
                await asyncio.gather(producer, return_exceptions=True)
        return socket

    async def websocket(self, request: web.Request) -> web.StreamResponse:
        principal = await self._principal(request)
        socket = web.WebSocketResponse(heartbeat=20, max_msg_size=4096)
        await socket.prepare(request)
        self.events.add(principal, socket)
        async def expire_socket() -> None:
            for _ in range(300):
                await asyncio.sleep(1)
                try:
                    self.controls.authorize(principal)
                except AccessDenied:
                    await socket.close(code=1008, message=b"authorization revoked")
                    return
            await socket.close(code=1000, message=b"reauthenticate")
        expiry = asyncio.create_task(expire_socket(), name="finfusion-ws-reauth")
        try:
            await socket.send_json({"type": "connected", "controlVersion": self.controls.snapshot.version})
            async for message in socket:
                if message.type == WSMsgType.TEXT and message.data != "ping":
                    await socket.close(code=1008, message=b"read-only event stream")
                elif message.type == WSMsgType.ERROR:
                    break
        finally:
            expiry.cancel()
            self.events.discard(principal, socket)
        return socket

    async def admin_control(self, request: web.Request) -> web.Response:
        claims = self._admin_claims(request)
        if self.set_control_callback is None:
            raise RuntimeError("控制存储未配置")
        payload = await self._json(request)
        if set(payload) - {"key", "enabled", "reason"} or not isinstance(payload.get("enabled"), bool):
            raise ValueError("控制请求字段无效")
        scope = request.match_info["scope"]
        key = str(payload.get("key") or "") or None
        if scope == "global" and payload["enabled"]:
            if (not getattr(self.service.gateway, "events_healthy", False)
                    or not getattr(self.service.gateway, "market_healthy", False)
                    or (self.database_healthy is not None and not await self.database_healthy())
                    or not self.service.reconciliation_ready
                    or not self.infrastructure.snapshot.mutation_ready):
                raise RuntimeError("节点、Tunnel、订单事件或启动对账尚未就绪，不能开启交易总开关")
        snapshot = await self.set_control_callback(scope, key, payload["enabled"], str(claims["sub"]), redact_text(payload.get("reason") or "", 200))
        self.controls.replace(snapshot)
        return web.json_response({"ok": True, "controlVersion": snapshot.version})

    async def admin_client(self, request: web.Request) -> web.Response:
        claims = self._admin_claims(request)
        if self.set_client_callback is None:
            raise RuntimeError("客户端控制存储未配置")
        payload = await self._json(request)
        if set(payload) != {"enabled"} or not isinstance(payload.get("enabled"), bool):
            raise ValueError("客户端控制请求字段无效")
        snapshot = await self.set_client_callback(request.match_info["client_id"], payload["enabled"], str(claims["sub"]))
        self.controls.replace(snapshot)
        if not payload["enabled"]:
            await self.events.revoke_client(request.match_info["client_id"])
        return web.json_response({"ok": True, "controlVersion": snapshot.version})

    async def admin_state(self, request: web.Request) -> web.Response:
        self._admin_claims(request)
        if self.admin_service is None:
            raise RuntimeError("管理服务未配置")
        return web.json_response(await self.admin_service.snapshot())

    async def admin_create_user(self, request: web.Request) -> web.Response:
        claims = self._admin_claims(request)
        if self.admin_service is None:
            raise RuntimeError("管理服务未配置")
        return web.json_response(await self.admin_service.create_user(await self._json(request), str(claims["sub"])), status=201)

    async def admin_add_account(self, request: web.Request) -> web.Response:
        claims = self._admin_claims(request)
        if self.admin_service is None:
            raise RuntimeError("管理服务未配置")
        return web.json_response(await self.admin_service.add_account(await self._json(request), str(claims["sub"])), status=201)

    async def admin_user_status(self, request: web.Request) -> web.Response:
        claims = self._admin_claims(request)
        if self.admin_service is None:
            raise RuntimeError("管理服务未配置")
        payload = await self._json(request)
        if set(payload) != {"enabled"} or not isinstance(payload.get("enabled"), bool):
            raise ValueError("用户状态字段无效")
        result = await self.admin_service.set_user_enabled(
            request.match_info["user_id"], payload["enabled"], str(claims["sub"])
        )
        if not payload["enabled"]:
            await self.events.revoke_user(request.match_info["user_id"])
        return web.json_response(result)

    async def admin_reset_password(self, request: web.Request) -> web.Response:
        self._admin_claims(request)
        if self.admin_service is None:
            raise RuntimeError("管理服务未配置")
        payload = await self._json(request)
        if set(payload) != {"password"}:
            raise ValueError("密码重置字段无效")
        return web.json_response(await self.admin_service.reset_password(
            request.match_info["user_id"], str(payload["password"])
        ))

    async def admin_bind(self, request: web.Request) -> web.Response:
        claims = self._admin_claims(request)
        if self.admin_service is None:
            raise RuntimeError("管理服务未配置")
        return web.json_response(await self.admin_service.bind(await self._json(request), str(claims["sub"])), status=201)

    async def admin_unbind(self, request: web.Request) -> web.Response:
        claims = self._admin_claims(request)
        if self.admin_service is None:
            raise RuntimeError("管理服务未配置")
        return web.json_response(await self.admin_service.unbind(
            request.match_info["account_ref"], str(claims["sub"])
        ))

    async def admin_config(self, _request: web.Request) -> web.Response:
        return web.json_response(self.admin_oidc_config)

    async def admin_index(self, _request: web.Request) -> web.StreamResponse:
        if self.admin_static_dir is None:
            raise web.HTTPNotFound()
        return web.FileResponse(self.admin_static_dir / "index.html")

    async def _principal(self, request: web.Request, *, require_idempotency: bool = False) -> Principal:
        body = await request.read()
        idempotency_key = request.headers.get("Idempotency-Key", "")
        if require_idempotency:
            try:
                uuid.UUID(idempotency_key)
            except (ValueError, AttributeError):
                raise ValueError("Idempotency-Key 必须是 UUID") from None
        authorization = request.headers.get("Authorization", "")
        token = authorization[7:].strip() if authorization.startswith("Bearer ") else ""
        proof = RequestProof(
            token=token,
            client_id=request.headers.get("X-Client-Id", ""),
            timestamp=request.headers.get("X-Timestamp", ""),
            nonce=request.headers.get("X-Nonce", ""),
            signature=request.headers.get("X-Client-Signature", ""),
            idempotency_key=idempotency_key,
        )
        if any(len(request.headers.getall(name, [])) != 1 for name in ("X-Client-Id", "X-Timestamp", "X-Nonce", "X-Client-Signature")):
            raise AccessDenied("签名请求头缺失或重复")
        if require_idempotency and len(request.headers.getall("Idempotency-Key", [])) != 1:
            raise ValueError("Idempotency-Key 缺失或重复")
        if any(len(request.query.getall(key)) != 1 for key in request.query):
            raise ValueError("查询参数不能重复")
        principal = self.authenticator.authenticate(proof, request.method, request.raw_path, body)
        permission = "cancel" if request.path.endswith("/cancel") else "trade" if require_idempotency else "read"
        self.controls.authorize(principal, permission)
        if self.consume_nonce is not None:
            await self.consume_nonce(principal.client_id, proof.nonce)
        request[IDEMPOTENCY_KEY] = idempotency_key
        return principal

    def _bearer_claims(self, request: web.Request) -> Mapping[str, Any]:
        authorization = request.headers.get("Authorization", "")
        if not authorization.startswith("Bearer "):
            raise AccessDenied("缺少登录令牌")
        return self.tokens.verify(authorization[7:].strip())

    def _admin_claims(self, request: web.Request) -> Mapping[str, Any]:
        claims = self._bearer_claims(request)
        roles = claims.get("roles") or claims.get("role") or []
        if isinstance(roles, str):
            roles = [roles]
        names = {
            str(item.get("name") or item.get("displayName") or "") if isinstance(item, Mapping) else str(item)
            for item in roles
        }
        if self.admin_role not in names:
            raise AccessDenied("需要管理员权限")
        return claims

    @staticmethod
    async def _json(request: web.Request) -> dict[str, Any]:
        try:
            def reject_constant(value):
                raise ValueError("JSON 不允许 NaN 或 Infinity")
            payload = json.loads((await request.read()).decode("utf-8") or "{}", parse_constant=reject_constant)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ValueError("请求JSON无效") from None
        if not isinstance(payload, dict):
            raise ValueError("请求必须是JSON对象")
        return payload

    @staticmethod
    def _validate_public_key(value: str) -> None:
        try:
            from cryptography.hazmat.primitives import serialization
            from cryptography.hazmat.primitives.asymmetric import ec
            key = serialization.load_pem_public_key(value.encode("ascii"))
            if not isinstance(key, ec.EllipticCurvePublicKey) or not isinstance(key.curve, ec.SECP256R1):
                raise ValueError
        except Exception:
            raise ValueError("客户端公钥必须是 P-256 PEM") from None

    @staticmethod
    def _error(message: str, status: int, code: str = "INVALID_REQUEST") -> web.Response:
        safe = message if message and len(message) <= 200 else "操作失败"
        return web.json_response({"error": {"code": code, "message": safe}}, status=status, headers={"Cache-Control": "no-store"})

    @staticmethod
    def _encode_cursor(cursor: tuple[float, str] | None) -> str | None:
        if cursor is None:
            return None
        raw = json.dumps([cursor[0], cursor[1]], separators=(",", ":")).encode("utf-8")
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")

    @staticmethod
    def _decode_cursor(value: str | None) -> tuple[float, str] | None:
        if not value:
            return None
        raw = base64.urlsafe_b64decode(value.encode("ascii") + b"=" * (-len(value) % 4))
        decoded = json.loads(raw)
        if not isinstance(decoded, list) or len(decoded) != 2 or not isinstance(decoded[1], str):
            raise ValueError
        timestamp = float(decoded[0])
        if not math.isfinite(timestamp):
            raise ValueError
        return timestamp, decoded[1]
