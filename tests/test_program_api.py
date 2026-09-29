import asyncio
import base64
import json
import time
import uuid
from dataclasses import replace
from decimal import Decimal
from types import SimpleNamespace

import pytest
import pytest_asyncio
from aiohttp.test_utils import TestClient, TestServer
from cryptography.hazmat.primitives import serialization

from client_sdk import FinfusionClient
from finfusion.api import ServerApi
from finfusion.controls import ControlPlane, ControlSnapshot, AccessDenied
from finfusion.environment import Environment
from finfusion.errors import ApiError, IdempotencyConflict
from finfusion.infrastructure import InfrastructureGate, InfrastructureSnapshot
from finfusion.models import AccountGrant, ClientGrant, Principal, RiskLimits, UserGrant
from finfusion.security import RequestAuthenticator, StaticTokenVerifier
from finfusion.service import InstitutionalTradingService
from finfusion.store import MemoryOrderStore
from tests.test_server_controls import make_controls, FakeInstitutionalGateway, order_payload


class Gateway(FakeInstitutionalGateway):
    market_healthy = True
    price = Decimal("100")
    selected = None

    async def fresh_price(self, symbol, age):
        return self.price

    async def select_symbol(self, ref, symbol):
        self.selected = symbol

    async def get_positions(self, account_id):
        return [{"symbol": "AAPL", "quantity": "3"}]

    async def get_balance(self, account_id):
        return {"currency": "USD", "usdBuyingPower": "123.45"}


@pytest_asyncio.fixture
async def stack():
    controls, private = make_controls()
    gateway, store = Gateway(), MemoryOrderStore()
    gate = InfrastructureGate(InfrastructureSnapshot(node_active=True, tunnel_healthy=True))
    service = InstitutionalTradingService(controls, store, gateway, limits=RiskLimits(max_open_orders=20), infrastructure=gate)
    tokens = StaticTokenVerifier({})
    api = ServerApi(service, controls, RequestAuthenticator(tokens, controls), tokens, infrastructure=gate)
    client = TestClient(TestServer(api.application()))
    await client.start_server()
    pem = private.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    sdk = FinfusionClient(str(client.make_url("/")).rstrip("/"), "client-1", pem, allow_local_http=True)
    try:
        yield SimpleNamespace(controls=controls, gateway=gateway, store=store, gate=gate, service=service, api=api, http=client, sdk=sdk)
    finally:
        await client.close()


def change(stack, *, client=None, user=None, accounts=None):
    old = stack.controls.snapshot
    stack.controls.replace(ControlSnapshot.frozen(global_trade_enabled=old.global_trade_enabled, version=old.version+1,
        users={"user-1": user} if user else old.users,
        clients={"client-1": client} if client else old.clients,
        accounts=accounts if accounts is not None else old.accounts))


async def test_sdk_has_no_bearer_and_reads_positions_balance(stack):
    assert "Authorization" not in stack.sdk.headers("GET", "/v1/accounts")
    for path, key in [("/v1/accounts", "accounts"), ("/v1/accounts/account-ref/positions", "positions"), ("/v1/accounts/account-ref/balance", "usdBuyingPower")]:
        result = await stack.sdk.request("GET", path)
        assert key in result
        assert "REAL-ACCOUNT" not in json.dumps(result)


@pytest.mark.parametrize("tamper", ["query", "body", "signature", "client", "replay", "timestamp", "nan"])
async def test_signature_rejects_tampering_and_replay(stack, tamper):
    path = "/v1/orders?accountRef=account-ref"
    headers = stack.sdk.headers("GET", path)
    body = b""
    if tamper == "query": path += "&limit=1"
    if tamper == "body": body = b"{}"
    if tamper == "signature": headers["X-Client-Signature"] = "invalid"
    if tamper == "client": headers["X-Client-Id"] = "unknown"
    if tamper == "timestamp": headers["X-Timestamp"] = "1"
    if tamper == "nan": headers["X-Timestamp"] = "nan"
    if tamper == "replay":
        assert (await stack.http.get(path, headers=headers)).status == 200
    assert (await stack.http.get(path, headers=headers, data=body)).status == 403


async def test_permissions_and_cross_account(stack):
    client = stack.controls.snapshot.clients["client-1"]
    change(stack, client=replace(client, can_trade=False))
    body=json.dumps(order_payload()).encode();path="/v1/orders"
    response=await stack.http.post(path,data=body,headers=stack.sdk.headers("POST",path,body,str(uuid.uuid4())))
    assert response.status == 403
    assert not stack.gateway.calls
    path="/v1/accounts/other/positions"
    assert (await stack.http.get(path,headers=stack.sdk.headers("GET",path))).status == 403
    change(stack, client=replace(client, enabled=False))
    assert (await stack.http.get("/v1/accounts",headers=stack.sdk.headers("GET","/v1/accounts"))).status == 403


async def test_market_idempotency_survives_changed_price_and_concurrency(stack):
    principal=Principal("user-1","client-1"); payload=order_payload(orderType="MARKET",limitPrice=None); rid=str(uuid.uuid4())
    first=await stack.service.submit(principal,payload,rid)
    stack.gateway.price=Decimal("105")
    results=await asyncio.gather(*(stack.service.submit(principal,payload,rid) for _ in range(8)))
    assert all(r["clientOrderId"]==first["clientOrderId"] for r in results)
    assert len(stack.gateway.calls)==1
    assert stack.gateway.selected=="AAPL"
    with pytest.raises(IdempotencyConflict): await stack.service.submit(principal,{**payload,"quantity":2},rid)


async def test_unknown_blocks_new_order_and_restart_reconciles(stack):
    async def timeout(*args): raise TimeoutError()
    stack.gateway.place_order=timeout
    principal=Principal("user-1","client-1")
    result=await stack.service.submit(principal,order_payload(),str(uuid.uuid4()))
    assert result["status"]=="UNKNOWN"
    assert not stack.service.reconciliation_ready
    with pytest.raises(RuntimeError,match="对账"):
        await stack.service.submit(principal,order_payload(),str(uuid.uuid4()))
    restored=InstitutionalTradingService(stack.controls,stack.store,stack.gateway)
    await restored.reconcile_unresolved()
    assert not restored.reconciliation_ready
    async def filled(*args): return {"status":"FILLED"}
    stack.gateway.get_order_detail=filled
    await restored.reconcile_unresolved()
    assert restored.reconciliation_ready
    assert (await restored.get_order(principal,"account-ref",result["clientOrderId"]))["status"]=="FILLED"


async def test_no_market_no_order_even_limit(stack):
    stack.gateway.price=None
    with pytest.raises(ApiError,match="行情"):
        await stack.service.submit(Principal("user-1","client-1"),order_payload(),str(uuid.uuid4()))
    assert not stack.gateway.calls


async def test_signed_sdk_order_query_replace_cancel(stack):
    rid=str(uuid.uuid4()); result=await stack.sdk.request("POST","/v1/orders",payload=order_payload(),request_id=rid)
    oid=result["clientOrderId"]
    lookup=await stack.sdk.request("GET",f"/v1/requests/{rid}",query={"accountRef":"account-ref"})
    assert lookup["clientOrderId"]==oid
    for method,path,payload in [("PATCH",f"/v1/orders/{oid}",{"accountRef":"account-ref","limitPrice":"101"}), ("POST",f"/v1/orders/{oid}/cancel",{"accountRef":"account-ref"})]:
        request_id=str(uuid.uuid4())
        await stack.sdk.request(method,path,payload=payload,request_id=request_id)
        await stack.sdk.request(method,path,payload=payload,request_id=request_id)
    assert [c[0] for c in stack.gateway.calls]==["place","replace","cancel"]


async def test_event_visibility_and_permission_revoke(stack):
    socket=await stack.http.ws_connect("/v1/events",headers=stack.sdk.headers("GET","/v1/events"))
    assert (await socket.receive_json())["type"]=="connected"
    result=await stack.service.submit(Principal("user-1","client-1"),order_payload(),str(uuid.uuid4()))
    for _ in range(4): assert (await socket.receive_json())["order"]["accountRef"]=="account-ref"
    change(stack,client=replace(stack.controls.snapshot.clients["client-1"],can_read=False))
    await stack.api.events.publish({"_userId":"user-1","order":result["order"]})
    message=await asyncio.wait_for(socket.receive(),2)
    assert message.type.name in {"CLOSE","CLOSED"}


async def test_unbound_orders_not_listed(stack):
    await stack.service.submit(Principal("user-1","client-1"),order_payload(),str(uuid.uuid4()))
    change(stack,accounts={})
    rows,_=await stack.service.list_orders(Principal("user-1","client-1"))
    assert rows==[]


@pytest.mark.parametrize("name", ["SANDBOX","LIVE"])
def test_environment_all_endpoints_and_storage(name):
    env=Environment.load({"FINFUSION_ENVIRONMENT":name,"FINFUSION_LIVE_ALLOWED":"true"})
    assert all(("sandbox" in host)==(name=="SANDBOX") for host in [env.api_host,env.data_host,env.events_host])
    env.validate_dsn(f"postgresql://localhost/finfusion_{name.lower()}")
    with pytest.raises(ValueError): env.validate_dsn("postgresql://localhost/shared")
    assert name.lower() in env.token_dir.parts and name.lower() in env.secret_dir.parts


def test_live_and_shared_paths_rejected():
    with pytest.raises(ValueError): Environment.load({"FINFUSION_ENVIRONMENT":"LIVE"})
    with pytest.raises(ValueError): Environment.load({"FINFUSION_TOKEN_DIR":"/var/shared"})


async def test_admin_client_rotation_revokes_old_signature(stack):
    from unittest.mock import AsyncMock
    from cryptography.hazmat.primitives.asymmetric import ec
    new_key=ec.generate_private_key(ec.SECP256R1())
    pem=new_key.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    old=stack.controls.snapshot
    rotated=ControlSnapshot.frozen(global_trade_enabled=True,version=old.version+1,users=old.users,
        clients={"client-1":replace(old.clients["client-1"],public_key_pem=pem,enabled=False)},accounts=old.accounts)
    configure=AsyncMock(return_value=rotated)
    stack.api.admin_service=SimpleNamespace(store=SimpleNamespace(configure_client=configure))
    class AdminTokens:
        def verify(self,token):
            if token!="admin": raise AccessDenied("invalid")
            return {"sub":"administrator","roles":["finfusion-admin"]}
    stack.api.tokens=AdminTokens()
    path="/admin/v1/clients/client-1"
    assert (await stack.http.patch(path,json={"publicKeyPem":pem},headers={"Authorization":"Bearer ordinary"})).status==403
    response=await stack.http.patch(path,json={"publicKeyPem":pem,"enabled":True},headers={"Authorization":"Bearer admin"})
    assert response.status==200
    configure.assert_awaited_once_with("client-1",{"publicKeyPem":pem,"enabled":True},"administrator")
    assert (await response.json())["requiresApproval"]
    assert not stack.controls.snapshot.clients["client-1"].enabled
    assert (await stack.http.get("/v1/accounts",headers=stack.sdk.headers("GET","/v1/accounts"))).status==403


async def test_node_failure_blocks_new_but_allows_duplicate_and_cancel(stack):
    principal=Principal("user-1","client-1");rid=str(uuid.uuid4())
    result=await stack.service.submit(principal,order_payload(),rid)
    stack.gate.force_closed("test")
    assert (await stack.service.submit(principal,order_payload(),rid))["clientOrderId"]==result["clientOrderId"]
    with pytest.raises(ApiError): await stack.service.submit(principal,order_payload(),str(uuid.uuid4()))
    await stack.service.cancel(principal,"account-ref",result["clientOrderId"],str(uuid.uuid4()))
    assert [c[0] for c in stack.gateway.calls]==["place","cancel"]


async def test_terminal_order_does_not_regress_on_late_open_event(stack):
    p=Principal("user-1","client-1");result=await stack.service.submit(p,order_payload(),str(uuid.uuid4()))
    event={"account_id":"REAL-ACCOUNT-123","client_order_id":result["clientOrderId"],"status":"FILLED"}
    await stack.service.receive_broker_event(event)
    await stack.service.receive_broker_event({**event,"status":"OPEN"})
    assert (await stack.service.get_order(p,"account-ref",result["clientOrderId"]))["status"]=="FILLED"


async def test_uncertain_replace_survives_restart_until_explicit_failure(stack):
    p=Principal("user-1","client-1");result=await stack.service.submit(p,order_payload(),str(uuid.uuid4()))
    async def timeout(*args): raise TimeoutError()
    stack.gateway.replace_order=timeout
    async def opened(*args): return {"status":"OPEN"}
    stack.gateway.get_order_detail=opened
    replaced=await stack.service.replace_limit(p,"account-ref",result["clientOrderId"],"101",str(uuid.uuid4()))
    assert replaced["status"]=="UNKNOWN"
    await stack.service.reconcile_unresolved()
    assert not stack.service.reconciliation_ready
    await stack.service.receive_broker_event({"account_id":"REAL-ACCOUNT-123","client_order_id":result["clientOrderId"],"status":"OPEN","scene_type":"MODIFY_FAILED"})
    order=await stack.service.get_order(p,"account-ref",result["clientOrderId"])
    assert order["limitPrice"]=="100" and order["pendingAction"] is None
    assert stack.service.reconciliation_ready


async def test_database_failure_never_sends_broker_order(stack):
    async def failed(*args): raise OSError("database unavailable")
    stack.store.insert=failed
    with pytest.raises(OSError):
        await stack.service.submit(Principal("user-1","client-1"),order_payload(),str(uuid.uuid4()))
    assert not stack.gateway.calls


async def test_openapi_matches_http_routes(stack):
    from pathlib import Path
    spec=json.loads((Path(__file__).parents[1]/"docs/openapi.json").read_text())
    documented={(method.upper(),path) for path,ops in spec["paths"].items() for method in ops}
    actual={(route.method,route.resource.canonical) for route in stack.http.server.app.router.routes() if route.method!="HEAD"}
    assert documented==actual
