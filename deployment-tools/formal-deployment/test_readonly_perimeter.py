import importlib.util
from pathlib import Path
import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient,TestServer

spec=importlib.util.spec_from_file_location('perimeter',Path(__file__).with_name('live_readonly_server.py'))
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

@pytest.mark.asyncio
async def test_trade_perimeter_blocks_mutations_and_escalation():
    calls=[]
    async def handler(request):
        calls.append(request.path)
        return web.json_response({'ok':True})
    app=web.Application(middlewares=[module.readonly_perimeter]);app.router.add_route('*','/{path:.*}',handler)
    async with TestClient(TestServer(app)) as client:
        for method,path,body in [
            ('POST','/v1/orders',{}),('PATCH','/v1/orders/example',{}),
            ('POST','/v1/orders/example/cancel',{}),
            ('POST','/admin/v1/controls/global',{'enabled':True}),
            ('POST','/admin/v1/controls/user',{'enabled':True}),
            ('POST','/admin/v1/controls/account',{'enabled':True}),
            ('PATCH','/admin/v1/clients/example',{'canTrade':True}),
            ('PATCH','/admin/v1/clients/example',{'canCancel':True})]:
            response=await client.request(method,path,json=body)
            assert response.status==403
        assert calls==[]
        for method,path,body in [('GET','/v1/accounts',None),('POST','/admin/v1/users',{}),('PATCH','/admin/v1/clients/example',{'enabled':True,'canRead':True,'canTrade':False,'canCancel':False}),('POST','/admin/v1/controls/global',{'enabled':False})]:
            response=await client.request(method,path,json=body)
            assert response.status==200
        assert len(calls)==4
