import argparse,asyncio,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2] / 'windows-client'))
from finfusion_client.security import data_directory,KeyStore,private_pem
from finfusion_client.storage import Journal,ConfigStore
from finfusion_client.transport import SignedTransport,ApiFailure
from finfusion_client.engine import Engine
parser=argparse.ArgumentParser();parser.add_argument('mode',choices=['denied','allowed','configure','connect']);args=parser.parse_args()
directory=data_directory();ctx=json.loads((directory.parent/'Admin'/'live-client-connection.json').read_text())
async def main():
    key=KeyStore(directory).load()
    transport=SignedTransport('https://api.finfusion.asia',ctx['clientId'],private_pem(key))
    if args.mode=='configure':
        journal=Journal(directory/'requests.sqlite3');assert not journal.pending()
        old=directory/'settings.json'
        if old.exists() and not (directory/'settings.before-live.json').exists():(directory/'settings.before-live.json').write_bytes(old.read_bytes())
        ConfigStore(directory,journal).save('https://api.finfusion.asia',ctx['clientId'])
        print('PASS: actual client configured; previous settings backed up; private key unchanged.')
        await transport.close();return
    if args.mode=='connect':
        journal=Journal(directory/'requests.sqlite3');engine=Engine(journal)
        try:
            await engine.connect(transport,start_events=False)
            assert engine.connected and len(engine.accounts)>0
            print('PASS: Windows client Engine connected over public HTTPS using its DPAPI-protected P-256 key. Accounts:',len(engine.accounts))
        finally:await engine.stop()
        return
    try:
        try:r=await transport.request('GET','/v1/accounts')
        except ApiFailure as exc:
            assert args.mode=='denied' and exc.status==403
            print('PASS: Windows signed request denied immediately.');return
        assert args.mode=='allowed','Revoked credentials unexpectedly accepted'
        accounts=r['accounts'];assert accounts
        assert all(a.get('tradeEnabled') is False for a in accounts)
        for a in accounts:
            ref=a['accountRef']
            positions=await transport.request('GET',f'/v1/accounts/{ref}/positions')
            balance=await transport.request('GET',f'/v1/accounts/{ref}/balance')
            assert positions['accountRef']==ref and balance['accountRef']==ref
        print('PASS: actual Windows signed HTTPS account, positions and balance reads. Accounts:',len(accounts))
    finally:await transport.close()
asyncio.run(main())
