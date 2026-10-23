"""Deploy the unchanged institutional API with an additional read-only perimeter.

The perimeter rejects all order mutations and attempts to grant trading/cancel
permissions or enable trade controls. Original authorization and health gates
remain in place. No broker, risk, or trading service behavior is replaced.
"""
import asyncio
import json
import os
import signal
import sys
from aiohttp import web
sys.path.insert(0,'/opt/finfusion/current')
from finfusion.main import build_application

@web.middleware
async def readonly_perimeter(request,handler):
    if request.method not in {'GET','HEAD','OPTIONS'}:
        deny=request.path.startswith('/v1/orders')
        if request.path.startswith('/admin/v1/'):
            try:
                payload=json.loads(await request.read())
            except (ValueError,UnicodeError):
                payload={}
            if isinstance(payload,dict):
                if request.path.startswith('/admin/v1/controls/'):
                    deny=deny or payload.get('enabled') is True
                if request.path.startswith('/admin/v1/clients/'):
                    deny=deny or payload.get('canTrade') is True or payload.get('canCancel') is True
        if deny:
            return web.json_response({'error':{'code':'READ_ONLY_DEPLOYMENT','message':'当前正式环境仅允许管理与只读查询，交易操作及交易权限开启已禁用'}},status=403)
    return await handler(request)

async def serve():
    os.umask(0o077)
    assert os.environ.get('FINFUSION_ENVIRONMENT')=='LIVE'
    app,gateway,store=await build_application()
    app.middlewares.insert(0,readonly_perimeter)
    runner=web.AppRunner(app,access_log=None)
    try:
        await runner.setup()
        await web.TCPSite(runner,'127.0.0.1',int(os.environ.get('FINFUSION_PORT','8080'))).start()
        stop=asyncio.Event();loop=asyncio.get_running_loop()
        for sig in [signal.SIGTERM,signal.SIGINT]:loop.add_signal_handler(sig,stop.set)
        await stop.wait()
    finally:
        await runner.cleanup();await gateway.close();await store.close()

if __name__=='__main__':
    try:asyncio.run(serve())
    except Exception as exc:
        # Broker exceptions can contain application identifiers: do not echo them.
        print('Finfusion LIVE read-only startup failed: '+type(exc).__name__,file=sys.stderr,flush=True)
        sys.exit(1)
