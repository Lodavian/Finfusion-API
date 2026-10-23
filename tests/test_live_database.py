"""Real PostgreSQL, LIVE binding, entirely synthetic broker gateway."""
import asyncio
import os
import uuid
from decimal import Decimal

import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization
from finfusion.postgres import PostgresStore, AccountCipher
from finfusion.controls import AccessDenied, ControlPlane
from finfusion.models import Principal, RiskLimits
from finfusion.service import InstitutionalTradingService
from finfusion.errors import IdempotencyConflict
from finfusion.infrastructure import InfrastructureGate, InfrastructureSnapshot
from finfusion.environment import Environment


class SyntheticGateway:
    events_healthy = True
    market_healthy = True

    def __init__(self):
        self.calls = []
        self.uncertain = False

    async def fresh_price(self, *_): return Decimal('100')
    async def get_available_position(self, *_): return Decimal('100')
    async def select_symbol(self, *_): pass
    async def place_order(self, *args):
        self.calls.append('place')
        if self.uncertain: raise TimeoutError()
        return {'status': 'ACKNOWLEDGED'}
    async def replace_order(self, *args):
        self.calls.append('replace')
        return {'status': 'REPLACED'}
    async def cancel_order(self, *args):
        self.calls.append('cancel')
        return {'status': 'CANCELLED'}
    async def get_order_detail(self, *args):
        self.calls.append('query')
        return None


async def setup():
    dsn = os.environ['FINFUSION_LIVE_TEST_DSN']
    assert '/finfusion_test_live_' in dsn
    store = await PostgresStore.connect(dsn, AccountCipher(b'x' * 32))
    await store.migrate()
    await store.bind_environment('LIVE')
    uid = 'synthetic-' + uuid.uuid4().hex
    await store.upsert_user(uid, uid, 'acceptance')
    key = ec.generate_private_key(ec.SECP256R1())
    public = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    cid, _ = await store.register_client(uid, 'synthetic', public)
    await store.configure_client(cid, {'enabled': True, 'canRead': True, 'canTrade': True, 'canCancel': True}, 'acceptance')
    ref, _ = await store.add_broker_account('SYNTHETIC-' + uuid.uuid4().hex, 'synthetic', '***0000', 'acceptance')
    await store.bind_account(uid, ref, 'acceptance')
    await store.set_control('user', uid, True, 'acceptance', 'isolated')
    await store.set_control('account', ref, True, 'acceptance', 'isolated')
    controls = ControlPlane(await store.set_control('global', None, True, 'acceptance', 'isolated'))
    gateway = SyntheticGateway()
    service = InstitutionalTradingService(controls, store, gateway, limits=RiskLimits(max_open_orders=30),
        infrastructure=InfrastructureGate(InfrastructureSnapshot(node_active=True, tunnel_healthy=True)))
    payload = {'accountRef': ref, 'symbol': 'AAPL', 'side': 'BUY', 'orderType': 'LIMIT', 'quantity': 1, 'limitPrice': '100'}
    return store, controls, gateway, service, Principal(uid, cid), payload


async def test_live_binding_migration_cipher_permissions_and_leader():
    store, controls, gateway, service, principal, payload = await setup()
    second = None
    try:
        assert await store.pool.fetchval('SELECT environment FROM deployment_environment') == 'LIVE'
        with pytest.raises(RuntimeError): await store.bind_environment('SANDBOX')
        second = await PostgresStore.connect(os.environ['FINFUSION_LIVE_TEST_DSN'], store.cipher)
        with pytest.raises(RuntimeError, match='已有'): await second.migrate()
        await second.close(); second = None
        assert controls.snapshot.clients[principal.client_id].public_key_pem.startswith('-----BEGIN PUBLIC KEY-----')
        assert controls.snapshot.clients[principal.client_id].can_trade
        assert controls.snapshot.accounts[payload['accountRef']].owner_user_id == principal.user_id
        assert controls.snapshot.accounts[payload['accountRef']].broker_account_id.startswith('SYNTHETIC-')
        wrong = Environment.load({'FINFUSION_ENVIRONMENT': 'LIVE', 'FINFUSION_LIVE_ALLOWED': 'true'})
        wrong.validate_dsn('postgresql://isolated/finfusion_live')
        with pytest.raises(ValueError): wrong.validate_dsn('postgresql://isolated/finfusion_sandbox')
    finally:
        if second: await second.close()
        await store.close()


async def test_live_concurrent_idempotency_replace_cancel_and_restart():
    store, controls, gateway, service, principal, payload = await setup()
    try:
        rid = str(uuid.uuid4())
        results = await asyncio.gather(*(service.submit(principal, payload, rid) for _ in range(8)))
        oid = results[0]['clientOrderId']
        assert all(v['clientOrderId'] == oid for v in results)
        assert gateway.calls.count('place') == 1
        with pytest.raises(IdempotencyConflict): await service.submit(principal, {**payload, 'quantity': 2}, rid)
        replace_id = str(uuid.uuid4())
        await service.replace_limit(principal, payload['accountRef'], oid, '101', replace_id)
        cancel_id = str(uuid.uuid4())
        await service.cancel(principal, payload['accountRef'], oid, cancel_id)
        nonce = uuid.uuid4().hex
        await store.consume_nonce(principal.client_id, nonce)
        await store.close()
        store = await PostgresStore.connect(os.environ['FINFUSION_LIVE_TEST_DSN'], AccountCipher(b'x' * 32))
        await store.migrate(); await store.bind_environment('LIVE')
        for request in [rid, replace_id, cancel_id]:
            assert (await store.find_request(payload['accountRef'], request))[0].client_order_id == oid
        with pytest.raises(AccessDenied): await store.consume_nonce(principal.client_id, nonce)
        assert not (await store.load_controls(force_global_off=True)).global_trade_enabled
    finally: await store.close()


async def test_live_unknown_reopens_and_queries_without_resend():
    store, controls, gateway, service, principal, payload = await setup()
    try:
        gateway.uncertain = True
        rid = str(uuid.uuid4())
        result = await service.submit(principal, payload, rid)
        assert result['status'] == 'UNKNOWN'
        await store.close()
        store = await PostgresStore.connect(os.environ['FINFUSION_LIVE_TEST_DSN'], AccountCipher(b'x' * 32))
        await store.migrate(); await store.bind_environment('LIVE')
        restored_controls = ControlPlane(await store.load_controls(force_global_off=True))
        restored = InstitutionalTradingService(restored_controls, store, gateway)
        await restored.reconcile_unresolved()
        assert not restored.reconciliation_ready
        assert (await store.find_request(payload['accountRef'], rid))[0].status == 'UNKNOWN'
        assert gateway.calls.count('place') == 1
        assert 'query' in gateway.calls
    finally: await store.close()
