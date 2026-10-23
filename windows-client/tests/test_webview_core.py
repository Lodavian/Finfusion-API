import asyncio
import pytest
from finfusion_client.market import Market
from finfusion_client.engine import Engine
from finfusion_client.storage import Journal
from finfusion_client.desktop import Controller, Bridge

@pytest.mark.asyncio
async def test_signed_market_search_reconnect_switch_and_order_independence(server,tmp_path):
    events=[]
    engine=Engine(Journal(tmp_path/'journal.db'))
    await engine.connect(server.transport(),start_events=False)
    engine.choose('account-A')
    market=Market(engine,lambda k,v: events.append((k,v)))
    assert (await market.search('aapl'))['symbols'][0]['symbol']=='AAPL'
    await market.select('AAPL')
    await asyncio.sleep(.1)
    assert any(k=='market' and v['lastPrice']=='100.25' for k,v in events)
    await market.select('MSFT'); await asyncio.sleep(.1)
    assert [v['symbol'] for k,v in events if k=='market'][-1]=='MSFT'
    await market.stop(); engine.choose('account-B')
    await market.select('AAPL'); await asyncio.sleep(.1)
    assert [v['accountRef'] for k,v in events if k=='market'][-1]=='account-B'
    assert not server.mutations
    await market.stop(); await engine.stop()

@pytest.mark.asyncio
async def test_market_ignores_old_versions_and_cross_account(server,tmp_path):
    output=[];engine=Engine(Journal(tmp_path/'journal.db'));market=Market(engine,lambda *args: output.append(args))
    good={'accountRef':'account-A','symbol':'AAPL','version':3}
    market._accept('market',good,'account-A','AAPL')
    market._accept('market',{**good,'version':2},'account-A','AAPL')
    assert len(output)==1
    with pytest.raises(Exception): market._accept('market',{**good,'accountRef':'account-B'},'account-A','AAPL')

def test_bridge_whitelist_and_save_not_authentication(tmp_path):
    controller=Controller(tmp_path,Journal(tmp_path/'journal.db'))
    bridge=Bridge(controller)
    try:
        assert {n for n in dir(bridge) if not n.startswith('_')}=={'get_state','action','save_config','key_operation'}
        assert 'error' in bridge.action('arbitrary-http',{})
        result=bridge.save_config('https://example.invalid','00000000-0000-4000-8000-000000000001')
        assert '尚未连接' in result['message']
        assert not bridge.get_state()['connected']
        assert 'private' not in str(bridge.get_state())
    finally: controller.close()
@pytest.mark.asyncio
async def test_market_disconnect_resnapshots_and_accepts_restart_version(server,tmp_path):
    events=[];engine=Engine(Journal(tmp_path/'journal.db'))
    await engine.connect(server.transport(),start_events=False);engine.choose('account-A')
    server.market_version=9
    market=Market(engine,lambda k,v: events.append((k,v)));await market.select('AAPL');await asyncio.sleep(.1)
    assert market.version==9
    before=server.market_reads;server.market_version=1
    await server.market_sockets[-1].close()
    await asyncio.sleep(1.2)
    assert server.market_reads > before and market.version==1
    assert not server.mutations
    await market.stop();await engine.stop()

@pytest.mark.asyncio
async def test_delayed_old_stock_cannot_update_new_subscription(server,tmp_path):
    events=[];engine=Engine(Journal(tmp_path/'journal.db'))
    await engine.connect(server.transport(),start_events=False);engine.choose('account-A')
    server.market_delay=.15
    market=Market(engine,lambda k,v: events.append((k,v)));await market.select('AAPL');await asyncio.sleep(.03)
    await market.select('MSFT');await asyncio.sleep(.35)
    assert all(v['symbol']=='MSFT' for k,v in events if k=='market')
    assert not server.mutations
    await market.stop();await engine.stop()
