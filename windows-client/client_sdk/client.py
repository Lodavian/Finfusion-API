"""Small signed HTTP client. Trading requests are NEVER automatically retried."""
import base64
import hashlib
import json
import time
import uuid
from urllib.parse import urlencode, urlsplit

import aiohttp
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from yarl import URL


class ApiResponseError(RuntimeError):
    def __init__(self, status, payload):
        self.status, self.payload = status, payload
        super().__init__(f"HTTP {status}: {payload.get('error', {}).get('code', 'HTTP_ERROR')}")


class FinfusionClient:
    def __init__(self, base_url: str, client_id: str, private_key_pem: bytes, *, allow_local_http=False):
        parsed = urlsplit(base_url)
        if parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
            raise ValueError("base_url must be an origin without credentials or path")
        if parsed.scheme != "https" and not (allow_local_http and parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost", "::1"}):
            raise ValueError("HTTPS is required except explicitly enabled loopback tests")
        self.base_url, self.client_id = base_url.rstrip("/"), client_id
        self.key = serialization.load_pem_private_key(private_key_pem, password=None)
        if not isinstance(self.key, ec.EllipticCurvePrivateKey) or not isinstance(self.key.curve, ec.SECP256R1):
            raise ValueError("P-256 private key required")

    def headers(self, method: str, target: str, body: bytes = b"", request_id: str = "") -> dict[str, str]:
        timestamp, nonce = str(time.time()), uuid.uuid4().hex
        message = "\n".join(("FINFUSION-V1", self.client_id, method.upper(), target, hashlib.sha256(body).hexdigest(), timestamp, nonce, request_id)).encode()
        signature = self.key.sign(message, ec.ECDSA(hashes.SHA256()))
        result = {"X-Client-Id": self.client_id, "X-Timestamp": timestamp, "X-Nonce": nonce,
                  "X-Client-Signature": base64.urlsafe_b64encode(signature).rstrip(b"=").decode(), "Content-Type": "application/json"}
        if request_id:
            result["Idempotency-Key"] = request_id
        return result

    async def request(self, method: str, path: str, *, payload=None, query=None, request_id=""):
        if not path.startswith("/v1/") or "?" in path or "#" in path:
            raise ValueError("Pass a /v1/ path and query separately")
        if method.upper() in {"POST", "PATCH"} and "/orders" in path:
            uuid.UUID(request_id)  # caller must save the ID BEFORE sending
        target = path + ("?" + urlencode(query) if query else "")
        body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode() if payload is not None else b""
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
            async with session.request(method, URL(self.base_url + target, encoded=True), data=body,
                                       headers=self.headers(method, target, body, request_id), allow_redirects=False) as response:
                result = await response.json()
                if response.status >= 300:
                    raise ApiResponseError(response.status, result)
                return result

    async def events(self):
        """After disconnect, query orders before opening a new subscription."""
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(self.base_url + "/v1/events", headers=self.headers("GET", "/v1/events"), heartbeat=20) as socket:
                async for message in socket:
                    if message.type == aiohttp.WSMsgType.TEXT:
                        yield json.loads(message.data)
