import pytest
from finfusion_client.transport import ApiFailure
from finfusion_client.desktop import Controller
from finfusion_client.storage import Journal, BusyError


@pytest.mark.asyncio
async def test_server_readonly_vetoes_stale_client_permission_without_resubmit(server,tmp_path):
    c=Controller(tmp_path,Journal(tmp_path/'journal.db'))
    try:
        await c.engine.connect(server.transport(),start_events=False); c.engine.choose('account-A')
        c.state['context']={'environment':'LIVE','tradeDeploymentAllowed':True,'tradeEnabled':True}
        server.mode='readonly'
        with pytest.raises(ApiFailure) as failure:
            await c.action('submit',{'accountRef':'account-A','symbol':'NVDA','side':'BUY','orderType':'LIMIT','quantity':'1','limitPrice':'5.00'})
        assert failure.value.code=='READ_ONLY_DEPLOYMENT'
        assert len(server.mutations)==1
        await c.engine.reconcile()
        assert len(server.mutations)==1
        with c.journal.connection() as db:
            assert db.execute('SELECT phase FROM intents').fetchone()[0]=='REFUSED'
        assert not c.journal.pending()
    finally:
        await c.engine.stop(); c.close()


@pytest.mark.asyncio
async def test_own_application_identity_and_edge_rejection_not_account_denial(server):
    transport=server.transport()
    await transport.request('GET','/v1/accounts')
    assert server.last_user_agent == 'FinfusionClient/1.0.0-rc1'
    server.mode='edge_block'
    with pytest.raises(ApiFailure) as failure:
        await transport.request('GET','/v1/accounts/account-A/ui-context')
    assert failure.value.code=='EDGE_BLOCKED' and failure.value.status==403
    assert not server.mutations


@pytest.mark.asyncio
async def test_live_requires_deployment_support_not_only_account_permission(server, tmp_path):
    c = Controller(tmp_path, Journal(tmp_path/'journal.db'))
    try:
        await c.engine.connect(server.transport(), start_events=False)
        c.engine.choose('account-A')
        c.state['context'] = {'environment':'LIVE', 'tradeEnabled':True, 'cancelEnabled':True}
        with pytest.raises(BusyError, match='当前只读'):
            await c.action('submit', {'accountRef':'account-A','symbol':'NVDA','side':'BUY','orderType':'LIMIT','quantity':'1','limitPrice':'5.00'})
        assert not server.mutations and not c.journal.pending()
        c.state['context']['tradeDeploymentAllowed'] = True
        await c.action('submit', {'accountRef':'account-A','symbol':'NVDA','side':'BUY','orderType':'LIMIT','quantity':'1','limitPrice':'5.00'})
        assert len(server.mutations) == 1
    finally:
        await c.engine.stop(); c.close()


@pytest.mark.asyncio
async def test_cancel_separate_from_new_order_gate_and_not_marked_cancelled(server,tmp_path):
    c=Controller(tmp_path,Journal(tmp_path/'journal.db'))
    try:
        await c.engine.connect(server.transport(),start_events=False); c.engine.choose('account-A')
        c.state['context']={'environment':'LIVE','tradeDeploymentAllowed':True,'tradeEnabled':True,'cancelEnabled':True}
        await c.action('submit',{'accountRef':'account-A','symbol':'NVDA','side':'BUY','orderType':'LIMIT','quantity':'1','limitPrice':'5.00'})
        oid=next(iter(server.orders))
        c.state['context']['tradeEnabled']=False
        await c.action('cancel',{'accountRef':'account-A','orderId':oid})
        assert c.engine.orders[('account-A',oid)]['status']=='CANCEL_REQUESTED'
        assert c.journal.pending()[0]['phase']=='OPERATION_PENDING'
        assert len(server.mutations)==2
    finally:
        await c.engine.stop(); c.close()
