import asyncio
import sqlite3
import uuid

import pytest
from finfusion_client.engine import Engine, order_payload, order_from
from finfusion_client.storage import Journal, ConfigStore, BusyError
from finfusion_client.transport import ApiFailure


@pytest.mark.asyncio
@pytest.mark.parametrize('count', [0, 1, 2])
async def test_account_selection_cardinality(server, tmp_path, count):
    server.refs = server.refs[:count]
    engine = Engine(Journal(tmp_path / 'journal.db'))
    await engine.connect(server.transport(), start_events=False)
    assert engine.selected == (server.refs[0] if count == 1 else None)
    with pytest.raises(ValueError):
        engine.choose('not-authorized')
    await engine.stop()


@pytest.mark.asyncio
async def test_revocation_removes_account_selection(server, tmp_path):
    messages = []
    engine = Engine(Journal(tmp_path / 'journal.db'), lambda *v: messages.append(v))
    await engine.connect(server.transport(), start_events=False)
    engine.choose(server.refs[0])
    server.refs = [server.refs[1]]
    await engine.refresh_accounts()
    assert engine.selected == server.refs[0]
    assert messages[-1][0] == 'accounts'
    await engine.stop()


def test_restore_matching_configuration_when_file_was_lost(tmp_path):
    journal = Journal(tmp_path / 'journal.db')
    client = str(uuid.uuid4())
    journal.reserve('https://example.com', client, 'A', 'submit', 'POST', '/v1/orders', {'accountRef': 'A'})
    config = ConfigStore(tmp_path, journal)
    config.save('https://example.com', client)
    assert config.load()['client_id'] == client
    with pytest.raises(BusyError):
        config.save('https://wrong.example', client)


@pytest.mark.asyncio
async def test_unexpected_order_payload_stays_uncertain(server, tmp_path, monkeypatch):
    journal = Journal(tmp_path / 'journal.db')
    engine = Engine(journal)
    await engine.connect(server.transport(), start_events=False)
    engine.choose(server.refs[0])
    intent = engine.prepare('submit', order_payload(server.refs[0], 'AAPL', 'BUY', 'MARKET', '1', ''))
    original = engine.transport.request
    async def malformed(method, path, **kwargs):
        data = await original(method, path, **kwargs)
        if method == 'POST':
            data['order']['accountRef'] = 'wrong-account'
        return data
    monkeypatch.setattr(engine.transport, 'request', malformed)
    with pytest.raises(ApiFailure):
        await engine.dispatch(intent)
    assert len(server.mutations) == 1
    assert journal.get(intent['request_id'])['phase'] == 'UNCERTAIN'
    await engine.stop()


@pytest.mark.asyncio
async def test_missing_route_does_not_fake_balance(server, tmp_path):
    client = server.transport()
    with pytest.raises(ApiFailure) as failed:
        await client.request('GET', '/v1/no-such-interface')
    assert failed.value.status == 404


@pytest.mark.asyncio
async def test_disconnect_during_authentication_cannot_mark_connected(server, tmp_path, monkeypatch):
    engine = Engine(Journal(tmp_path / 'journal.db'))
    transport = server.transport()
    original = transport.request
    entered = asyncio.Event()
    release = asyncio.Event()
    async def delayed(method, path, **kwargs):
        data = await original(method, path, **kwargs)
        if path == '/v1/accounts':
            entered.set()
            await release.wait()
        return data
    monkeypatch.setattr(transport, 'request', delayed)
    task = asyncio.create_task(engine.connect(transport, start_events=False))
    await entered.wait()
    await engine.stop()
    release.set()
    with pytest.raises(ApiFailure):
        await task
    assert not engine.connected


@pytest.mark.parametrize('bad_status', [None, {}, 'NON_CONTRACT_STATUS'])
def test_noncontract_order_cannot_be_marked_resolved(bad_status):
    with pytest.raises(ApiFailure):
        order_from(dict(accountRef='A', clientOrderId='FO1', status=bad_status, version=1))


@pytest.mark.asyncio
async def test_recovery_poll_cannot_steal_live_dispatch(server, tmp_path):
    journal = Journal(tmp_path / 'journal.db')
    engine = Engine(journal)
    await engine.connect(server.transport(), start_events=False)
    engine.choose(server.refs[0])
    intent = engine.prepare('submit', order_payload(server.refs[0], 'AAPL', 'BUY', 'MARKET', '1', ''))
    await engine.reconcile()
    assert journal.get(intent['request_id'])['phase'] == 'PREPARED'
    assert server.lookups == []
    server.mode = 'timeout'
    task = asyncio.create_task(engine.dispatch(intent))
    await asyncio.sleep(.06)
    assert journal.get(intent['request_id'])['phase'] == 'SENDING'
    await engine.reconcile()
    assert journal.get(intent['request_id'])['phase'] == 'SENDING'
    assert server.lookups == []
    await task
    assert journal.get(intent['request_id'])['phase'] == 'RESOLVED'
    assert len(server.mutations) == 1
    await engine.stop()
