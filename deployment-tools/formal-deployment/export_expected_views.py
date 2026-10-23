"""Private pipe output for comparison: never display or save its output in the workspace."""
import asyncio,contextlib,io,json,logging,sys
from pathlib import Path
logging.disable(logging.CRITICAL)
sys.path.insert(0,'/opt/finfusion/current')
from finfusion.gateway import GatewayConfig,InstitutionalWebullGateway
from finfusion.account_view import usd_cash_fields
from finfusion_common.utils import rows_from,response_json,response_ok
async def main():
    p=Path('/run/finfusion/secrets/live')
    g=InstitutionalWebullGateway(GatewayConfig((p/'webull_app_key').read_text(),(p/'webull_app_secret').read_text(),Path('/var/lib/finfusion/webull_tokens/live')))
    try:
        with contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
            await g._call(g._build_clients)
            response=await g._call(g.trade_client.account_v2.get_account_list)
            assert response_ok(response)
            ids=[str(x.get('account_id') or x.get('accountId') or x.get('id')) for x in rows_from(response)]
            refs=json.loads(Path('/var/lib/finfusion/formal-deployment/live/acceptance.json').read_text())['accountRefs']
            assert len(ids)==len(refs)
            expected={}
            for ref,account in zip(refs,ids):
                balance=await g._call(g.trade_client.account_v2.get_account_balance,account)
                assert response_ok(balance)
                positions_response=await g._call(g.trade_client.account_v2.get_account_position,account)
                assert response_ok(positions_response)
                raw_positions=g._position_rows(response_json(positions_response))
                expected[ref]={'cash':usd_cash_fields(response_json(balance)),'positions':await g.get_positions(account),'rawPositionCount':len(raw_positions)}
        print(json.dumps(expected))
    finally:await g.close()
asyncio.run(main())
