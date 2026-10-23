"""Actual Sandbox read-only account discovery, with credential-safe diagnostics."""
import asyncio,contextlib,io,json,logging,os,re,sys
from pathlib import Path
sys.path.insert(0,'/opt/finfusion/current')
from finfusion.gateway import GatewayConfig,InstitutionalWebullGateway
from finfusion_common.utils import response_ok,rows_from
logging.disable(logging.CRITICAL)
async def main():
    directory=Path('/run/finfusion/secrets/sandbox')
    config=GatewayConfig((directory/'webull_app_key').read_text(),(directory/'webull_app_secret').read_text(),Path('/var/lib/finfusion/webull_tokens/sandbox'),api_host='api.sandbox.webull.hk',data_host='data-api.sandbox.webull.hk',events_host='events-api.sandbox.webull.hk')
    gateway=InstitutionalWebullGateway(config)
    try:
        with contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
            gateway._validate_token_dir()
            await gateway._call(gateway._build_clients)
            response=await gateway._call(gateway.trade_client.account_v2.get_account_list)
        http=getattr(response,'status_code',None)
        count=sum(bool(row.get('account_id') or row.get('accountId') or row.get('id')) for row in rows_from(response))
        result={'httpStatus':http,'responseOk':response_ok(response),'accountCount':count}
        if not response_ok(response):
            try:
                payload=response.json()
                code=str(payload.get('error_code') or payload.get('errorCode') or payload.get('code') or '')
                if re.fullmatch(r'[A-Za-z0-9_.-]{1,80}',code): result['brokerErrorCode']=code
            except Exception: pass
        print(json.dumps(result))
        return 0 if result['responseOk'] and count else 2
    except Exception as exc:
        details={'preflight':'failed','exceptionType':type(exc).__name__}
        for attr in ['error_code','code','status_code','http_status']:
            value=getattr(exc,attr,None)
            if value is not None and re.fullmatch(r'[A-Za-z0-9_.-]{1,80}',str(value)):
                details[attr]=str(value)
        message=str(getattr(exc,'error_msg',''))
        for value in [config.app_key,config.app_secret]:
            message=message.replace(value,'[REDACTED]')
        message=re.sub(r'[A-Za-z0-9_./+=-]{16,}','[REDACTED]',message)
        if message: details['brokerMessage']=message[:180]
        print(json.dumps(details))
        return 3
    finally:
        with contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
            await gateway.close()
sys.exit(asyncio.run(main()))
