from __future__ import annotations

import base64
import json
import time
import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from aiohttp.test_utils import TestClient, TestServer
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

from finfusion.api import ServerApi
from finfusion.controls import ControlPlane, ControlSnapshot
from finfusion.models import AccountGrant, ClientGrant, RiskLimits, UserGrant
from finfusion.security import RequestAuthenticator, StaticTokenVerifier, canonical_request
from finfusion.service import InstitutionalTradingService
from finfusion.store import MemoryOrderStore


class ApiGateway:
    events_healthy = True

    async def select_symbol(self, reference_id, symbol):
        return None

    async def fresh_price(self, symbol, max_age):
        return Decimal("50")

    async def get_available_position(self, account_id, symbol):
        return Decimal("100")

    async def place_order(self, account_id, order):
        assert account_id == "SECRET-ACCOUNT"
        return {"accepted": True}

    async def replace_order(self, account_id, order):
        return {"replaced": True}

    async def cancel_order(self, account_id, client_order_id):
        return {"cancelled": True}

    async def get_order_detail(self, account_id, client_order_id):
        return None


@pytest_asyncio.fixture
async def server_api():
    private = ec.generate_private_key(ec.SECP256R1())
    public = private.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    ).decode("ascii")
    snapshot = ControlSnapshot.frozen(
        global_trade_enabled=True,
        version=1,
        users={"u": UserGrant("u", True, True)},
        clients={"d": ClientGrant("d", "u", public, True)},
        accounts={"a": AccountGrant("a", "u", "SECRET-ACCOUNT", "账户", "••••0001", True, True)},
    )
    controls = ControlPlane(snapshot)
    tokens = StaticTokenVerifier({"good": "u", "admin": "admin"})
    service = InstitutionalTradingService(
        controls, MemoryOrderStore(), ApiGateway(), limits=RiskLimits(max_open_orders=10)
    )
    api = ServerApi(service, controls, RequestAuthenticator(tokens, controls), tokens)
    client = TestClient(TestServer(api.application()))
    await client.start_server()
    try:
        yield client, private
    finally:
        await client.close()


def signed_headers(private, method, path, body=b"", idem=""):
    timestamp = str(time.time())
    nonce = uuid.uuid4().hex
    signature = private.sign(
        canonical_request(method, path, body, timestamp, nonce, idem, "d"), ec.ECDSA(hashes.SHA256())
    )
    result = {
        "Authorization": "Bearer good", "X-Client-Id": "d", "X-Timestamp": timestamp,
        "X-Nonce": nonce, "X-Client-Signature": base64.urlsafe_b64encode(signature).rstrip(b"=").decode(),
        "Content-Type": "application/json",
    }
    if idem:
        result["Idempotency-Key"] = idem
    return result


@pytest.mark.asyncio
async def test_api_never_exposes_broker_account_id_and_accepts_signed_order(server_api):
    client, private = server_api
    response = await client.get("/v1/accounts", headers=signed_headers(private, "GET", "/v1/accounts"))
    assert response.status == 200
    text = await response.text()
    assert "SECRET-ACCOUNT" not in text

    payload = {"accountRef": "a", "symbol": "AAPL", "side": "BUY", "orderType": "LIMIT", "quantity": 1, "limitPrice": "50"}
    body = json.dumps(payload, separators=(",", ":")).encode()
    idem = str(uuid.uuid4())
    response = await client.post("/v1/orders", data=body, headers=signed_headers(private, "POST", "/v1/orders", body, idem))
    assert response.status == 202
    result = await response.json()
    assert result["order"]["status"] == "ACKNOWLEDGED"
    assert "SECRET-ACCOUNT" not in json.dumps(result)

    lookup_path = f"/v1/requests/{idem}"
    response = await client.get(
        lookup_path + "?accountRef=a",
        headers=signed_headers(private, "GET", lookup_path + "?accountRef=a"),
    )
    assert response.status == 200
    assert (await response.json())["order"]["clientOrderId"] == result["order"]["clientOrderId"]


@pytest.mark.asyncio
async def test_api_rejects_missing_proof_and_non_uuid_idempotency(server_api):
    client, private = server_api
    assert (await client.get("/v1/accounts", headers={"Authorization": "Bearer good"})).status == 403
    payload = {"accountRef": "a", "symbol": "AAPL", "side": "BUY", "orderType": "LIMIT", "quantity": 1, "limitPrice": "50"}
    body = json.dumps(payload, separators=(",", ":")).encode()
    response = await client.post("/v1/orders", data=body, headers=signed_headers(private, "POST", "/v1/orders", body, "bad"))
    assert response.status == 400


@pytest.mark.asyncio
async def test_readyz_reports_node_tunnel_and_effective_trade_state(server_api):
    client, _private = server_api
    response = await client.get("/readyz")
    assert response.status == 503
    state = await response.json()
    assert state["nodeActive"] is False
    assert state["tunnel"] is False
    assert state["globalTradeEnabled"] is True
    assert state["effectiveTradeEnabled"] is False
