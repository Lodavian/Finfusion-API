"""Read-only signed GETs with altered request timestamps, never changes OS time."""
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import time
from unittest.mock import patch

from finfusion_client.security import KeyStore, data_directory, private_pem
from finfusion_client.transport import SignedTransport


async def main():
    directory=data_directory()
    settings=json.loads((directory/'settings.json').read_text(encoding='utf-8'))
    client=SignedTransport(settings['origin'],settings['client_id'],private_pem(KeyStore(directory).load()),timeout=15)
    evidence={'at':datetime.now(timezone.utc).isoformat(),'method':'GET','path':'/v1/accounts',
              'osClockChanged':False,'mutations':0,'checks':[],'status':'PASS'}
    try:
        session=await client._session()
        for offset in [0,20,-20,45,-45]:
            now=time.time()
            # Only request signing is inside this context; network timers and TLS use normal time.
            with patch('client_sdk.client.time.time',return_value=now+offset):
                headers=client.sdk.headers('GET','/v1/accounts')
            async with session.get(client.origin+'/v1/accounts',headers=headers,ssl=client.ssl,allow_redirects=False) as response:
                data=await response.json()
                expected=200 if abs(offset)==0 or abs(offset)==20 else 403
                matched=response.status==expected
                if response.status==403 and data.get('error',{}).get('code')!='ACCESS_DENIED': matched=False
                evidence['checks'].append({'signedOffsetSeconds':offset,'httpStatus':response.status,
                    'errorCode':data.get('error',{}).get('code'),'result':'PASS' if matched else 'FAIL'})
                if not matched: evidence['status']='FAIL'
    except Exception as error:
        evidence.update(status='FAIL',reason=type(error).__name__)
    finally:
        await client.close()
    output=Path('build/host-acceptance/signature-clock.json'); output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'status':evidence['status'],'checks':len(evidence['checks']),'orders':0}))
    return 0 if evidence['status']=='PASS' else 1


if __name__=='__main__':raise SystemExit(asyncio.run(main()))
