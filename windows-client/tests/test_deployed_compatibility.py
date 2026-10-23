"""Compatibility failures observed against the deployed read-only LIVE service."""
import asyncio
import pytest

from finfusion_client.desktop import Controller
from finfusion_client.engine import Engine
from finfusion_client.market import Market
from finfusion_client.storage import Journal
from finfusion_client.transport import ApiFailure


@pytest.mark.asyncio
async def test_absent_ui_context_does_not_erase_auth_or_invent_live_permissions(server, tmp_path):
    controller = Controller(tmp_path, Journal(tmp_path / 'journal.db'))
    transport = server.transport()
    original = transport.request

    async def old_server(method, path, **kwargs):
        if path.endswith('/ui-context'):
            raise ApiFailure('HTTP_ERROR', 404)
        return await original(method, path, **kwargs)

    transport.request = old_server
    try:
        await controller.engine.connect(transport, start_events=False)
        controller.engine.choose('account-A')
        controller.state['context'] = {'environment': 'SANDBOX', 'tradeEnabled': True}
        await controller.refresh()
        assert controller.engine.connected
        assert controller.state['context'] == {}
        assert controller.state['context_status'] == 'NOT_SUPPORTED'
        assert controller.state['positions']['accountRef'] == 'account-A'
        assert controller.state['balance']['accountRef'] == 'account-A'
        with pytest.raises(Exception, match='SANDBOX'):
            await controller.action('submit', {'accountRef': 'account-A'})
        assert not server.mutations
    finally:
        await controller.engine.stop()
        controller.close()


@pytest.mark.asyncio
async def test_missing_market_stops_reconnect_without_clearing_authenticated_accounts(server, tmp_path):
    engine = Engine(Journal(tmp_path / 'journal.db'))
    await engine.connect(server.transport(), start_events=False)
    engine.choose('account-A')
    calls = []
    notices = []

    async def missing(method, path, **kwargs):
        calls.append(path)
        raise ApiFailure('HTTP_ERROR', 404)

    engine.transport.request = missing
    market = Market(engine, lambda *args: notices.append(args))
    try:
        with pytest.raises(ValueError, match='尚未部署行情接口'):
            await market.search('AAPL')
        await market.select('AAPL')
        await asyncio.sleep(1.15)
        assert calls == ['/v1/market/symbols', '/v1/market/snapshot']
        assert notices[-1] == ('market_clear', {'status': 'NOT_SUPPORTED'})
        assert engine.connected
        assert not server.mutations
    finally:
        await market.stop()
        await engine.stop()


def test_market_permission_error_is_specific_and_sanitized():
    failure = ApiFailure('MARKET_DATA_DENIED', 403)
    assert failure.code == 'MARKET_DATA_DENIED'
    assert '行情' in str(failure)
