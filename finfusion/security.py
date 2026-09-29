from __future__ import annotations

import base64
import hashlib
import json
import math
import threading
import time
import urllib.request
from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

from .controls import AccessDenied, ControlPlane
from .models import Principal
from .errors import ApiError


class TokenVerifier(Protocol):
    def verify(self, token: str) -> Mapping[str, Any]: ...


class StaticTokenVerifier:
    """Test/local verifier. Production startup refuses to enable it."""

    def __init__(self, tokens: Mapping[str, str]):
        self._tokens = dict(tokens)

    def verify(self, token: str) -> Mapping[str, Any]:
        user_id = self._tokens.get(token)
        if not user_id:
            raise AccessDenied("登录令牌无效")
        return {"sub": user_id}


class CasdoorJwtVerifier:
    """Cached-JWKS verifier; normal requests perform no IAM network call."""

    def __init__(self, jwks_url: str, issuer: str, audience: str, *, refresh_seconds: int = 900):
        self.jwks_url = jwks_url
        self.issuer = issuer.rstrip("/")
        self.audience = audience
        self.refresh_seconds = max(60, refresh_seconds)
        self._keys: dict[str, Any] = {}
        self._loaded_at = 0.0
        self._lock = threading.Lock()

    def verify(self, token: str) -> Mapping[str, Any]:
        try:
            import jwt
        except ImportError as exc:  # pragma: no cover - deployment dependency
            raise RuntimeError("生产JWT验证依赖未安装") from exc
        try:
            header = jwt.get_unverified_header(token)
        except Exception as exc:
            raise AccessDenied("登录令牌无效") from exc
        kid = str(header.get("kid") or "")
        key = self._keys.get(kid)
        if not kid or key is None:
            # IAM is deliberately excluded from the request hot path. A newly
            # rotated key becomes usable after the background refresh.
            raise AccessDenied("身份系统签名密钥尚未同步")
        try:
            return jwt.decode(
                token,
                key=key,
                algorithms=["RS256"],
                audience=self.audience,
                issuer=self.issuer,
                options={"require": ["exp", "iat", "sub"]},
                leeway=5,
            )
        except Exception as exc:
            raise AccessDenied("登录令牌无效或已过期") from exc

    def refresh(self) -> None:
        try:
            import jwt
        except ImportError as exc:  # pragma: no cover - deployment dependency
            raise RuntimeError("生产JWT验证依赖未安装") from exc
        with self._lock:
            request = urllib.request.Request(self.jwks_url, headers={"Accept": "application/json"})
            with urllib.request.urlopen(request, timeout=5) as response:
                payload = json.loads(response.read(256 * 1024))
            keys: dict[str, Any] = {}
            for item in payload.get("keys", []) if isinstance(payload, dict) else []:
                if not isinstance(item, dict) or not item.get("kid"):
                    continue
                keys[str(item["kid"])] = jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(item))
            if not keys:
                raise AccessDenied("身份系统签名密钥不可用")
            self._keys = keys
            self._loaded_at = time.monotonic()


class NonceCache:
    def __init__(self, ttl_seconds: float = 120.0, max_entries: int = 100_000):
        self.ttl_seconds = ttl_seconds
        self.max_entries = max_entries
        self._values: dict[tuple[str, str], float] = {}
        self._lock = threading.Lock()

    def consume(self, client_id: str, nonce: str, now: float | None = None) -> None:
        current = now if now is not None else time.time()
        key = (client_id, nonce)
        with self._lock:
            if len(self._values) >= self.max_entries:
                cutoff = current - self.ttl_seconds
                self._values = {item: seen for item, seen in self._values.items() if seen >= cutoff}
            previous = self._values.get(key)
            if previous is not None and current - previous <= self.ttl_seconds:
                raise AccessDenied("请求已被重放")
            if len(self._values) >= self.max_entries:
                raise AccessDenied("请求验证容量已满")
            self._values[key] = current


def canonical_request(
    method: str,
    path: str,
    body: bytes,
    timestamp: str,
    nonce: str,
    idempotency_key: str,
    client_id: str = "",
) -> bytes:
    body_hash = hashlib.sha256(body).hexdigest()
    return "\n".join(
        ("FINFUSION-V1", client_id, method.upper(), path, body_hash, timestamp, nonce, idempotency_key)
    ).encode("utf-8")


def _b64url_decode(value: str) -> bytes:
    raw = value.encode("ascii")
    return base64.urlsafe_b64decode(raw + b"=" * (-len(raw) % 4))


@dataclass(slots=True)
class RequestProof:
    token: str
    client_id: str
    timestamp: str
    nonce: str
    signature: str
    idempotency_key: str = ""


class RequestAuthenticator:
    def __init__(
        self,
        tokens: TokenVerifier,
        controls: ControlPlane,
        *,
        allowed_skew_seconds: float = 30.0,
        nonce_cache: NonceCache | None = None,
        subject_claim: str = "sub",
    ):
        self.tokens = tokens
        self.controls = controls
        self.allowed_skew_seconds = allowed_skew_seconds
        self.nonces = nonce_cache or NonceCache()
        self.subject_claim = subject_claim
        self._request_rates: dict[str, tuple[float, float]] = {}

    def authenticate(self, proof: RequestProof, method: str, path: str, body: bytes) -> Principal:
        client = self.controls.snapshot.clients.get(proof.client_id)
        if client is None or not client.enabled:
            raise AccessDenied("客户端未获授权")
        user_id = client.user_id
        user = self.controls.snapshot.users.get(user_id)
        if user is None or not user.enabled:
            raise AccessDenied("用户已禁用")
        clock = time.monotonic()
        budget, previous = self._request_rates.get(proof.client_id, (120.0, clock))
        budget = min(120.0, budget + (clock - previous) * 60.0)
        if budget < 1:
            raise ApiError("RATE_LIMITED", "客户端请求过于频繁", 429)
        self._request_rates[proof.client_id] = (budget - 1, clock)
        try:
            sent_at = float(proof.timestamp)
        except (TypeError, ValueError):
            raise AccessDenied("请求时间戳无效") from None
        now = time.time()
        if not math.isfinite(sent_at) or abs(now - sent_at) > self.allowed_skew_seconds:
            raise AccessDenied("请求已过期")
        if not (16 <= len(proof.nonce) <= 128):
            raise AccessDenied("请求nonce无效")
        snapshot = self.controls.snapshot
        client = snapshot.clients.get(proof.client_id)
        if client is None or client.user_id != user_id or not client.enabled:
            raise AccessDenied("客户端未获授权")
        message = canonical_request(
            method, path, body, proof.timestamp, proof.nonce, proof.idempotency_key, proof.client_id
        )
        try:
            public_key = serialization.load_pem_public_key(client.public_key_pem.encode("ascii"))
            if not isinstance(public_key, ec.EllipticCurvePublicKey) or not isinstance(public_key.curve, ec.SECP256R1):
                raise AccessDenied("客户端密钥类型无效")
            public_key.verify(_b64url_decode(proof.signature), message, ec.ECDSA(hashes.SHA256()))
        except InvalidSignature as exc:
            raise AccessDenied("客户端请求签名无效") from exc
        except AccessDenied:
            raise
        except Exception as exc:
            raise AccessDenied("客户端请求签名无效") from exc
        self.nonces.consume(proof.client_id, proof.nonce, now)
        return Principal(user_id=user_id, client_id=proof.client_id)
