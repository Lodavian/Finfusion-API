"""Inspect broker field names, never print financial values or account identifiers."""
import asyncio,contextlib,io,json,logging,sys
from pathlib import Path
logging.disable(logging.CRITICAL)
sys.path.insert(0,'/home/finfusion_tech/worktrees/finfusion-client-market')
from finfusion.gateway import GatewayConfig,InstitutionalWebullGateway
from finfusion_common.utils import response_json,response_ok

def schema(value,depth=0):
    if depth>4:return type(value).__name__
    if isinstance(value,dict):return {k:schema(v,depth+1) for k,v in value.items()}
    if isinstance(value,list):return [schema(value[0],depth+1)] if value else []
    return type(value).__name__

async def main():
    p=Path('/run/finfusion/secrets/live')
    g=InstitutionalWebullGateway(GatewayConfig((p/'webull_app_key').read_text(),(p/'webull_app_secret').read_text(),Path('/var/lib/finfusion/webull_tokens/live')))
    try:
        with contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):await g._call(g._build_clients)
        ctx=json.loads(Path('/var/lib/finfusion/formal-deployment/live/acceptance.json').read_text())
        # Actual account identities are discovered privately; only schemas leave this process.
        from finfusion_common.utils import rows_from
        r=await g._call(g.trade_client.account_v2.get_account_list)
        ids=[str(x.get('account_id') or x.get('accountId') or x.get('id')) for x in rows_from(r)]
        for n,account in enumerate(ids,1):
            r=await g._call(g.trade_client.account_v2.get_account_balance,account)
            print('balance',n,'ok',response_ok(r),'schema',json.dumps(schema(response_json(r))))
        for name,fn,args in [('symbols',g.data_client.instrument.get_instrument,(['AAPL'],g.CATEGORY)),('snapshot',g.data_client.market_data.get_snapshot,(['AAPL'],g.CATEGORY,False,False)),('quotes',g.data_client.market_data.get_quotes,('AAPL',g.CATEGORY,1,False)),('ticks',g.data_client.market_data.get_tick,('AAPL',g.CATEGORY,'200'))]:
            try:
                r=await g._call(fn,*args)
                print(name,'ok',response_ok(r),'schema',json.dumps(schema(response_json(r))))
                if name=='symbols':print('public instrument categories',[(x.get('symbol'),x.get('sub_category'),x.get('category')) for x in rows_from(r)])
            except Exception as e:
                print(name,'exception',type(e).__name__,'status',getattr(e,'http_status',None),'code',getattr(e,'error_code',None))
    finally:await g.close()

asyncio.run(main())
