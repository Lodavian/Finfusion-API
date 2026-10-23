"""Signed transport using the vendored server SDK; no write retries."""
import asyncio
import json
import ssl
from urllib.parse import urlencode

import aiohttp
from yarl import URL
from client_sdk.client import FinfusionClient
from .storage import encode_body
from . import __version__

ERRORS = {
    "ACCESS_DENIED": "服务器拒绝访问：请检查公钥登记、客户端批准及账户权限",
    "INVALID_REQUEST": "服务器拒绝请求：请核对输入和服务器交易条件",
    "IDEMPOTENCY_CONFLICT": "幂等编号冲突；只能查询原请求，不会重发",
    "RATE_LIMITED": "服务器限流，请稍后手动操作",
    "MARKET_NOT_READY": "服务器行情未就绪，未发送订单",
    "MARKET_DATA_DENIED": "服务器或券商未授予行情读取权限",
    "MARKET_DATA_UNAVAILABLE": "服务器行情源暂不可用",
    "NODE_NOT_READY": "服务器节点或 Tunnel 未就绪",
    "BROKER_NOT_READY": "服务器券商连接未就绪",
    "INTERNAL_ERROR": "服务器内部错误；交易结果待确认",
    "NETWORK_UNCERTAIN": "网络结果不确定；不会自动重发交易命令",
    "INVALID_RESPONSE": "服务器响应不符合接口契约；交易结果待确认",
    "REDIRECT_BLOCKED": "服务器返回重定向，客户端已拒绝跟随",
    "TLS_ERROR": "TLS 证书验证失败，请检查服务器证书和系统时间",
    "HTTP_ERROR": "接口不可用或请求被拒绝，请检查服务器版本",
    "EDGE_BLOCKED": "公网入口拒绝程序访问（Cloudflare），请检查 API 入口规则",
    "READ_ONLY_DEPLOYMENT": "服务器当前为只读部署，交易及交易权限提升已关闭",
}


class ApiFailure(RuntimeError):
    def __init__(self, code, status=0):
        self.code = code if code in ERRORS else "HTTP_ERROR"
        self.status = status
        super().__init__(ERRORS[self.code])


class SignedTransport:
    def __init__(self, origin, client_id, private_key, *, timeout=30, test_http=False, ssl_context=None):
        self.sdk = FinfusionClient(origin, client_id, private_key, allow_local_http=test_http)
        self.origin, self.client_id = self.sdk.base_url, client_id
        self.timeout = timeout
        self.ssl = ssl_context or ssl.create_default_context()
        self.session = None

    async def _session(self):
        if self.session is None or self.session.closed:
            trace = aiohttp.TraceConfig()
            async def no_redirect(*_args):
                raise ApiFailure("REDIRECT_BLOCKED")
            trace.on_request_redirect.append(no_redirect)
            self.session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.timeout), trace_configs=[trace],
                headers={"User-Agent": "FinfusionClient/" + __version__})
        return self.session

    async def request(self, method, path, *, payload=None, body=None, query=None,
                      request_id="", allowed_statuses=()):
        if not path.startswith("/") or "?" in path or "#" in path:
            raise ValueError("请求路径与查询参数必须分开")
        if method in {"POST", "PATCH"} and "/orders" in path:
            import uuid
            uuid.UUID(request_id)
        target = path + ("?" + urlencode(query) if query else "")
        raw = body if body is not None else encode_body(payload) if payload is not None else b""
        headers = self.sdk.headers(method, target, raw, request_id)
        try:
            session = await self._session()
            async with session.request(method, URL(self.origin + target, encoded=True), data=raw,
                                       headers=headers, ssl=self.ssl, allow_redirects=False) as response:
                if 300 <= response.status < 400:
                    raise ApiFailure("REDIRECT_BLOCKED", response.status)
                try:
                    data = await response.json()
                except Exception:
                    if response.status == 403 and response.headers.get('Server','').lower() == 'cloudflare':
                        raise ApiFailure("EDGE_BLOCKED", response.status) from None
                    if response.status >= 300:
                        raise ApiFailure("HTTP_ERROR", response.status) from None
                    raise ApiFailure("INVALID_RESPONSE") from None
                if not isinstance(data, dict):
                    raise ApiFailure("INVALID_RESPONSE")
                if response.status >= 300 and response.status not in allowed_statuses:
                    error = data.get("error", {})
                    code = error.get("code", "HTTP_ERROR") if isinstance(error, dict) else "HTTP_ERROR"
                    raise ApiFailure(code, response.status)
                return data
        except ApiFailure:
            raise
        except (aiohttp.ClientSSLError, ssl.SSLError):
            raise ApiFailure("TLS_ERROR") from None
        except (aiohttp.ClientError, OSError, asyncio.TimeoutError):
            raise ApiFailure("NETWORK_UNCERTAIN") from None

    def events(self):
        return self.stream("/v1/events")

    async def stream(self, path, *, query=None):
        if not path.startswith("/") or "?" in path or "#" in path:
            raise ValueError("请求路径非法")
        target = path + ("?" + urlencode(query) if query else "")
        try:
            session = await self._session()
            async with session.ws_connect(URL(self.origin + target, encoded=True), ssl=self.ssl,
                                          headers=self.sdk.headers("GET", target), heartbeat=20) as socket:
                async for message in socket:
                    if message.type == aiohttp.WSMsgType.TEXT:
                        try:
                            event = json.loads(message.data)
                            if not isinstance(event, dict):
                                raise ValueError()
                        except Exception:
                            raise ApiFailure("INVALID_RESPONSE") from None
                        yield event
                    elif message.type == aiohttp.WSMsgType.ERROR:
                        raise ApiFailure("NETWORK_UNCERTAIN")
        except ApiFailure:
            raise
        except aiohttp.WSServerHandshakeError as exc:
            edge = exc.status == 403 and exc.headers.get('Server','').lower() == 'cloudflare' and 'application/json' not in exc.headers.get('Content-Type','')
            raise ApiFailure("EDGE_BLOCKED" if edge else "ACCESS_DENIED" if exc.status == 403 else "HTTP_ERROR", exc.status) from None
        except (aiohttp.ClientSSLError, ssl.SSLError):
            raise ApiFailure("TLS_ERROR") from None
        except (aiohttp.ClientError, OSError, asyncio.TimeoutError):
            raise ApiFailure("NETWORK_UNCERTAIN") from None

    async def close(self):
        if self.session:
            await self.session.close()
