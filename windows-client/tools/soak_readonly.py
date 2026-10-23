"""Bounded live read-only observation and client-owned WS reconnect checks."""
import argparse
import asyncio
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import time

from finfusion_client.security import data_directory,KeyStore,private_pem
from finfusion_client.transport import SignedTransport,ApiFailure


async def run(seconds):
    directory=data_directory(); config=json.loads((directory/'settings.json').read_text())
    t=SignedTransport(config['origin'],config['client_id'],private_pem(KeyStore(directory).load()),timeout=15)
    report={'startedAt':datetime.now(timezone.utc).isoformat(),'mode':'LIVE_READ_ONLY','mutations':0,'samples':[],
            'connectionCycles':[],'requestedSeconds':seconds}
    try:
        accounts=(await t.request('GET','/v1/accounts'))['accounts']
        end=time.monotonic()+seconds
        iteration=0
        while time.monotonic()<end:
            for account in accounts:
                ref=account['accountRef']; symbol=('AAPL','MSFT','NVDA')[iteration%3]
                sample={'accountHash':hashlib.sha256(ref.encode()).hexdigest()[:8],'symbol':symbol}
                try:
                    query={'accountRef':ref,'symbol':symbol}
                    snapshot=await t.request('GET','/v1/market/snapshot',query=query)
                    assert snapshot['accountRef']==ref and snapshot['symbol']==symbol
                    sample.update(status=snapshot.get('status'),timestampPresent=snapshot.get('asOf') is not None,
                                  pricePresent=snapshot.get('lastPrice') is not None)
                    if iteration in {0,2}:
                        stream=t.stream('/v1/market/events',query=query)
                        try:
                            event=await asyncio.wait_for(anext(stream),10)
                            assert event['type']=='connected'
                            update=await asyncio.wait_for(anext(stream),10)
                            assert update.get('type')=='market.update' and update['snapshot']['accountRef']==ref and update['snapshot']['symbol']==symbol
                            report['connectionCycles'].append({'accountHash':sample['accountHash'],'symbol':symbol,'signedReconnect':iteration==2,'passed':True})
                        finally: await stream.aclose()
                    sample['result']='PASS'
                except (ApiFailure,AssertionError,asyncio.TimeoutError) as exc:
                    sample.update(result='FAIL',errorType=type(exc).__name__)
                    report['samples'].append(sample)
                    raise
                report['samples'].append(sample)
            iteration+=1
            await asyncio.sleep(min(30,max(0,end-time.monotonic())))
        report['status']='PASS'
    except Exception:
        report['status']='FAIL'
    finally:
        await t.close(); report['finishedAt']=datetime.now(timezone.utc).isoformat()
        path=Path('build/readonly-soak-1.0.json'); path.write_text(json.dumps(report,indent=2),encoding='utf-8')
        print(report['status'],len(report['samples']),'read-only samples')
    return report['status']=='PASS'


if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('--seconds',type=int,default=600); args=parser.parse_args()
    if not 90<=args.seconds<=1800: parser.error('duration must be 90–1800 seconds')
    raise SystemExit(0 if asyncio.run(run(args.seconds)) else 1)
