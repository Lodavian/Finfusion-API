"""Actual Windows signed read-only acceptance; private comparison data arrives on stdin."""
import asyncio,json,subprocess,sys
from pathlib import Path
from finfusion_client.security import KeyStore,data_directory,private_pem
from finfusion_client.transport import SignedTransport,ApiFailure

def admin(action):
    r=subprocess.run(['wsl','-d','Ubuntu','-u','root','--cd','/','--','/opt/finfusion/venv/bin/python','/home/finfusion_tech/formal-deployment/manage_live_acceptance.py',action],capture_output=True)
    assert r.returncode==0,'Administrator test action failed'

async def main():
    expected=json.load(sys.stdin)
    directory=data_directory();config=json.loads((directory/'settings.json').read_text())
    transport=SignedTransport(config['origin'],config['client_id'],private_pem(KeyStore(directory).load()))
    try:
        accounts=(await transport.request('GET','/v1/accounts'))['accounts']
        assert len(accounts)==len(expected)
        for account in accounts:
            ref=account['accountRef'];prefix='/v1/accounts/'+ref
            balance=await transport.request('GET',prefix+'/balance')
            assert {k:balance[k] for k in expected[ref]['cash']}==expected[ref]['cash']
            positions=await transport.request('GET',prefix+'/positions')
            assert sorted((p['symbol'],p['quantity']) for p in positions['positions'])==sorted((p['symbol'],p['quantity']) for p in expected[ref]['positions'])
            context=await transport.request('GET',prefix+'/ui-context')
            assert context['environment']=='LIVE' and not context['tradeEnabled'] and not context['tradeAuthorized'] and not context['cancelEnabled']
        print('PASS: both accounts cash fields and position quantities match broker reads; LIVE UI permissions read-only.')
        ref=accounts[0]['accountRef']
        for symbol in ['AAPL','MSFT','AAPL']:
            query={'accountRef':ref,'symbol':symbol}
            symbols=await transport.request('GET','/v1/market/symbols',query={'accountRef':ref,'q':symbol})
            assert any(s['symbol']==symbol for s in symbols['symbols'])
            snapshot=await transport.request('GET','/v1/market/snapshot',query=query)
            assert snapshot['symbol']==symbol and snapshot['accountRef']==ref and snapshot['lastPrice'] is not None and snapshot['asOf'] is not None
            events=transport.stream('/v1/market/events',query=query)
            try:
                assert (await asyncio.wait_for(anext(events),15))['type']=='connected'
                event=await asyncio.wait_for(anext(events),15)
                assert event['type']=='market.update' and event['snapshot']['symbol']==symbol and event['snapshot']['accountRef']==ref
            finally:await events.aclose()
        print('PASS: AAPL/MSFT/AAPL lookup, price snapshots and re-signed WebSocket streams preserve symbol and account.')
        for action,restore in [('disable-user','enable-user'),('revoke-client','restore-client')]:
            events=transport.stream('/v1/market/events',query={'accountRef':ref,'symbol':'AAPL'})
            try:
                await asyncio.wait_for(anext(events),15);await asyncio.wait_for(anext(events),15)
                admin(action)
                try:
                    await transport.request('GET','/v1/market/snapshot',query={'accountRef':ref,'symbol':'AAPL'})
                    raise AssertionError('Revoked market request accepted')
                except ApiFailure as e:assert e.status==403
                async def closed():
                    async for event in events:
                        # Frames already buffered before revocation may still arrive.
                        pass
                await asyncio.wait_for(closed(),10)
                print('PASS: '+action+' rejects new reads and closes active market stream.')
            finally:
                admin(restore);await events.aclose()
        admin('assert-readonly')
    finally:await transport.close()

asyncio.run(main())
