import asyncio
import base64
import json
import ssl
import time
import uuid
from pathlib import Path

import aiohttp
from aiohttp import web
import pytest
from cryptography.hazmat.primitives.asymmetric import ec

from finfusion_client.engine import Engine, order_payload, status_text
from finfusion_client.security import KeyStore, private_pem, dpapi, SecurityError, InstanceLock, restrict_directory
from finfusion_client.storage import Journal, ConfigStore, BusyError, encode_body
from finfusion_client.transport import SignedTransport, ApiFailure


async def connected(server, tmp_path, notify=lambda *_: None):
    journal = Journal(tmp_path / '请求记录.sqlite3')
    engine = Engine(journal, notify)
    await engine.connect(server.transport(), start_events=False)
    engine.choose(server.refs[0])
    return engine


@pytest.mark.asyncio
async def test_signing_encoding_and_all_routes(server, tmp_path):
    engine = await connected(server, tmp_path)
    server.refs.append('账户 A/+&')
    await engine.transport.request('GET', '/v1/orders', query={'accountRef': '账户 A/+&', 'cursor': 'x+/=', 'limit': 200})
    assert server.last_target == '/v1/orders?accountRef=%E8%B4%A6%E6%88%B7+A%2F%2B%26&cursor=x%2B%2F%3D&limit=200'
    await engine.refresh()
    payload = order_payload(server.refs[0], 'aapl', 'BUY', 'LIMIT', '2', '100.50')
    intent = engine.prepare('submit', payload)
    assert engine.journal.get(intent['request_id'])['body'] == encode_body(payload)
    await engine.dispatch(intent)
    assert server.mutations[0][3] == intent['body']
    order_id = next(iter(server.orders))
    await engine.detail(order_id)
    replace = engine.prepare('replace', {'accountRef': server.refs[0], 'limitPrice': '101.25'}, order_id)
    await engine.dispatch(replace)
    cancel = engine.prepare('cancel', {'accountRef': server.refs[0]}, order_id)
    await engine.dispatch(cancel)
    assert server.orders[order_id]['status'] == 'CANCEL_REQUESTED'
    assert engine.journal.get(cancel['request_id'])['phase'] == 'OPERATION_PENDING'
    await engine.reconcile()
    assert cancel['request_id'] in server.lookups
    async for event in engine.transport.events():
        assert event['type'] == 'connected'
        break
    assert len(server.mutations) == 3
    await engine.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize('mode', ['timeout', 'missing', '500', 'invalid', 'redirect', 'conflict'])
async def test_uncertain_never_resends_after_restart(server, tmp_path, mode):
    engine = await connected(server, tmp_path)
    engine.transport.timeout = 0.15
    # Session created during connect; update timeout for following commands.
    await engine.transport.close()
    server.mode = mode
    intent = engine.prepare('submit', order_payload(server.refs[0], 'AAPL', 'BUY', 'MARKET', '1', ''))
    with pytest.raises(ApiFailure):
        await engine.dispatch(intent)
    assert len(server.mutations) == 1
    assert engine.journal.get(intent['request_id'])['phase'] == 'UNCERTAIN'
    with pytest.raises(BusyError):
        await engine.dispatch(intent)
    await engine.stop()
    await asyncio.sleep(.42)
    restarted = await connected(server, tmp_path)
    await restarted.reconcile()
    await restarted.reconcile()
    assert len(server.mutations) == 1
    assert server.lookups[-1] == intent['request_id']
    if mode in {'missing', 'redirect', 'conflict'}:
        assert restarted.journal.get(intent['request_id'])['phase'] == 'UNCERTAIN'
    else:
        assert restarted.journal.get(intent['request_id'])['phase'] == 'RESOLVED'
    assert server.victim_count == 0
    await restarted.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize('phase', ['PREPARED', 'SENDING'])
async def test_crash_before_or_during_send_is_query_only(server, tmp_path, phase):
    engine = await connected(server, tmp_path)
    intent = engine.prepare('submit', order_payload(server.refs[0], 'AAPL', 'BUY', 'MARKET', '1', ''))
    if phase == 'SENDING':
        engine.journal.begin_send(intent['request_id'])
    recovered = Journal(engine.journal.path)
    assert recovered.get(intent['request_id'])['phase'] == 'UNCERTAIN'
    with pytest.raises(BusyError):
        await engine.dispatch(intent)
    await engine.reconcile()
    assert not server.mutations and server.lookups == [intent['request_id']]
    await engine.stop()


@pytest.mark.asyncio
async def test_double_command_locks_account_but_other_account_works(server, tmp_path):
    engine = await connected(server, tmp_path)
    intent = engine.prepare('submit', order_payload(server.refs[0], 'AAPL', 'BUY', 'MARKET', '1', ''))
    with pytest.raises(BusyError):
        engine.prepare('submit', order_payload(server.refs[0], 'AAPL', 'BUY', 'MARKET', '1', ''))
    engine.choose(server.refs[1])
    other = engine.prepare('submit', order_payload(server.refs[1], 'MSFT', 'SELL', 'LIMIT', '1', '200'))
    await engine.dispatch(other)
    await engine.dispatch(intent)
    assert len(server.mutations) == 2 and len({m[2] for m in server.mutations}) == 2
    await engine.stop()


@pytest.mark.asyncio
async def test_mutation_persistence_failure_sends_nothing(server, tmp_path, monkeypatch):
    engine = await connected(server, tmp_path)
    def broken(*_args):
        raise OSError('simulated disk failure')
    monkeypatch.setattr(engine.journal, 'reserve', broken)
    with pytest.raises(OSError):
        engine.prepare('submit', order_payload(server.refs[0], 'AAPL', 'BUY', 'MARKET', '1', ''))
    assert not server.mutations
    await engine.stop()


@pytest.mark.asyncio
async def test_permission_rejection_and_readiness(server, tmp_path):
    messages = []
    engine = await connected(server, tmp_path, lambda *v: messages.append(v))
    assert engine.connected
    assert any(k == 'readiness' and d['effectiveTradeEnabled'] is False for k, d, _ in messages)
    with pytest.raises(ApiFailure) as denied:
        await engine.transport.request('GET', '/v1/orders', query={'accountRef': 'unauthorized'})
    assert denied.value.status == 403
    server.enabled = False
    with pytest.raises(ApiFailure) as disabled:
        await engine.transport.request('GET', '/v1/accounts')
    assert disabled.value.status == 403
    await engine.stop()


@pytest.mark.asyncio
async def test_wrong_private_key_and_nonce_replay(server):
    wrong = SignedTransport(server.origin, server.client_id, private_pem(ec.generate_private_key(ec.SECP256R1())), test_http=True)
    try:
        with pytest.raises(ApiFailure) as rejected:
            await wrong.request('GET', '/v1/accounts')
        assert rejected.value.status == 403
    finally:
        await wrong.close()
    client = server.transport()
    headers = client.sdk.headers('GET', '/v1/accounts')
    async with aiohttp.ClientSession() as session:
        async with session.get(server.origin + '/v1/accounts', headers=headers) as response:
            assert response.status == 200
        async with session.get(server.origin + '/v1/accounts', headers=headers) as response:
            assert response.status == 403


@pytest.mark.asyncio
async def test_explicit_refusal_does_not_show_broker_rejection(server, tmp_path):
    engine = await connected(server, tmp_path)
    server.mode = 'reject'
    intent = engine.prepare('submit', order_payload(server.refs[0], 'AAPL', 'BUY', 'MARKET', '1', ''))
    with pytest.raises(ApiFailure):
        await engine.dispatch(intent)
    assert engine.journal.get(intent['request_id'])['phase'] == 'REFUSED'
    assert not engine.orders
    await engine.stop()


@pytest.mark.asyncio
async def test_account_switch_discards_delayed_data_and_foreign_events(server, tmp_path):
    messages = []
    engine = await connected(server, tmp_path, lambda *v: messages.append(v))
    old_generation = engine.generation
    server.position_delay = .06
    task = asyncio.create_task(engine.refresh())
    await asyncio.sleep(.01)
    engine.choose(server.refs[1])
    messages.clear()
    await task
    assert not any(k == 'positions' and g == old_generation for k, _, g in messages)
    await engine.refresh()
    assert all(d['accountRef'] == server.refs[1] for k, d, _ in messages if k in {'positions', 'balance'})
    foreign = server.make_order(str(uuid.uuid4()), {'accountRef': 'foreign', 'symbol': 'BAD'})
    assert not engine.merge(foreign)
    await engine.stop()


@pytest.mark.asyncio
async def test_event_disconnect_queries_before_reconnect_and_rejects_old_versions(server, tmp_path):
    engine = await connected(server, tmp_path)
    initial = server.make_order(str(uuid.uuid4()), {'accountRef': server.refs[0]})
    server.orders[initial['clientOrderId']] = initial
    engine.backoff = (.01,)
    engine.event_task = asyncio.create_task(engine.event_loop())
    for _ in range(100):
        if server.ws_count:
            break
        await asyncio.sleep(.01)
    assert server.ws_count == 1
    newer = dict(initial, status='FILLED', version=3)
    server.orders[initial['clientOrderId']] = newer
    await server.websockets[0].close()
    for _ in range(100):
        if server.ws_count >= 2:
            break
        await asyncio.sleep(.01)
    assert server.ws_count >= 2
    key = (initial['accountRef'], initial['clientOrderId'])
    assert engine.orders[key]['status'] == 'FILLED'
    assert not engine.merge(dict(initial, status='OPEN', version=2))
    assert not engine.merge(newer)
    server.enabled = False
    await server.websockets[-1].close()
    for _ in range(100):
        if not engine.connected:
            break
        await asyncio.sleep(.01)
    assert not engine.connected
    await engine.stop()


@pytest.mark.asyncio
async def test_websocket_redirect_never_follows(server):
    server.mode = 'ws_redirect'
    with pytest.raises(ApiFailure) as blocked:
        async for _ in server.transport().events():
            pass
    assert blocked.value.code == 'REDIRECT_BLOCKED'
    assert server.victim_count == 0


@pytest.mark.asyncio
async def test_pending_replace_and_cancel_only_resolve_from_server(server, tmp_path):
    engine = await connected(server, tmp_path)
    first = engine.prepare('submit', order_payload(server.refs[0], 'AAPL', 'BUY', 'LIMIT', '1', '100'))
    await engine.dispatch(first)
    order_id = next(iter(server.orders))
    server.mode = 'pending_replace'
    replace = engine.prepare('replace', {'accountRef': server.refs[0], 'limitPrice': '101'}, order_id)
    await engine.dispatch(replace)
    await engine.reconcile()
    assert engine.journal.get(replace['request_id'])['phase'] == 'OPERATION_PENDING'
    with pytest.raises(BusyError):
        engine.prepare('replace', {'accountRef': server.refs[0], 'limitPrice': '102'}, order_id)
    server.orders[order_id].update(status='REPLACED', pendingAction=None, version=3)
    await engine.reconcile()
    assert engine.journal.get(replace['request_id'])['phase'] == 'RESOLVED'
    server.mode = 'normal'
    cancel = engine.prepare('cancel', {'accountRef': server.refs[0]}, order_id)
    await engine.dispatch(cancel)
    assert engine.journal.get(cancel['request_id'])['phase'] == 'OPERATION_PENDING'
    server.orders[order_id].update(status='CANCELLED', pendingAction=None, version=5)
    await engine.reconcile()
    assert engine.journal.get(cancel['request_id'])['phase'] == 'RESOLVED'
    assert len(server.mutations) == 3
    await engine.stop()


@pytest.mark.asyncio
async def test_tls_self_signed_rejected(server, tmp_path):
    from cryptography import x509
    from cryptography.x509.oid import NameOID
    from cryptography.hazmat.primitives import hashes, serialization
    import datetime
    import ipaddress
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'localhost')])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(minutes=1))
            .not_valid_after(now + datetime.timedelta(days=1))
            .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]), False)
            .sign(key, hashes.SHA256()))
    cert_path, key_path = tmp_path / 'mock.pem', tmp_path / 'mock-key.pem'
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(private_pem(key))
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert_path, key_path)
    app = web.Application()
    async def tls_accounts(_request):
        return web.json_response({'accounts': []})
    app.router.add_get('/v1/accounts', tls_accounts)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '127.0.0.1', 0, ssl_context=context)
    await site.start()
    origin = f'https://127.0.0.1:{site._server.sockets[0].getsockname()[1]}'
    client = SignedTransport(origin, server.client_id, private_pem(server.key))
    try:
        with pytest.raises(ApiFailure) as invalid:
            await client.request('GET', '/v1/accounts')
        assert invalid.value.code == 'TLS_ERROR'
        assert client.ssl.verify_mode == ssl.CERT_REQUIRED and client.ssl.check_hostname
    finally:
        await client.close()
        await runner.cleanup()


def test_dpapi_key_generation_import_and_corruption(tmp_path):
    directory = tmp_path / '中文 用户数据'
    keys = KeyStore(directory)
    keys.generate()
    encrypted = keys.path.read_bytes()
    assert b'PRIVATE KEY' not in encrypted
    assert keys.load().curve.name == 'secp256r1'
    public = keys.public_pem()
    assert b'PUBLIC KEY' in public and b'PRIVATE KEY' not in public
    with pytest.raises(SecurityError):
        keys.generate()
    with pytest.raises(SecurityError):
        dpapi(b'corrupted', decrypt=True)
    invalid = tmp_path / 'invalid.pem'
    invalid.write_bytes(b'not a key')
    with pytest.raises(SecurityError):
        keys.import_file(invalid)
    assert keys.path.read_bytes() == encrypted
    source = tmp_path / 'import.pem'
    source.write_bytes(private_pem(ec.generate_private_key(ec.SECP256R1())))
    keys.import_file(source)
    assert keys.public_pem() != public


def test_config_namespace_and_pending_changes(tmp_path):
    journal = Journal(tmp_path / 'journal.db')
    config = ConfigStore(tmp_path, journal)
    client = str(uuid.uuid4())
    config.save('https://example.com/', client)
    assert config.load()['origin'] == 'https://example.com'
    journal.reserve('https://example.com', client, 'A', 'submit', 'POST', '/v1/orders', {'accountRef': 'A'})
    with pytest.raises(BusyError):
        config.save('https://other.example', client)
    with pytest.raises(BusyError):
        config.save('https://example.com', str(uuid.uuid4()))
    assert not journal.pending('https://other.example', client)
    config.save('https://example.com', client)
    with pytest.raises(ValueError):
        config.save('http://example.com', client)


def test_windows_instance_lock(tmp_path):
    restrict_directory(tmp_path)
    first, second = InstanceLock(tmp_path), InstanceLock(tmp_path)
    assert first.acquire()
    assert not second.acquire()
    first.release()
    assert second.acquire()
    second.release()


@pytest.mark.parametrize('status,expected', [('ACKNOWLEDGED', '未成交'), ('CANCEL_REQUESTED', '撤单请求中'),
    ('PARTIAL_FILLED', '部分成交'), ('FILLED', '已成交'), ('CANCELLED', '已撤销'), ('UNKNOWN', '待确认')])
def test_status_labels(status, expected):
    assert expected in status_text(status) and f'[{status}]' in status_text(status)


@pytest.mark.parametrize('quantity', ['0', '1.5', '-1', 'NaN', '１'])
def test_input_format_only(quantity):
    with pytest.raises(ValueError):
        order_payload('A', 'AAPL', 'BUY', 'MARKET', quantity, '')
