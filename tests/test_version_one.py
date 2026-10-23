import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from finfusion.deployment import readonly_perimeter
from tests.test_program_api import stack


async def test_signed_server_info_matches_protocol_and_version(stack):
    result = await stack.sdk.request('GET','/v1/info')
    assert result['version'] == '1.0.0-rc1'
    assert result['apiProtocol'] == 'FINFUSION-V1'
    assert 'market-events' in result['capabilities']
    assert (await stack.http.get('/v1/info')).status == 403


@pytest.mark.parametrize('method,path,payload',[
    ('POST','/v1/orders',{}), ('PATCH','/v1/orders/o',{}),
    ('POST','/v1/orders/o/cancel',{}),
    ('PATCH','/admin/v1/clients/c',{'canTrade':True}),
    ('PATCH','/admin/v1/clients/c',{'canCancel':True}),
    ('POST','/admin/v1/controls/global',{'enabled':True})])
async def test_readonly_perimeter_rejects_every_mutation_without_broker_calls(method,path,payload):
    calls=[]
    async def handler(request): calls.append(request.path); return web.json_response({'ok':True})
    app=web.Application(middlewares=[readonly_perimeter]); app.router.add_route('*','/{tail:.*}',handler)
    async with TestClient(TestServer(app)) as client:
        response=await client.request(method,path,json=payload)
        assert response.status==403
        assert (await response.json())['error']['code']=='READ_ONLY_DEPLOYMENT'
        assert not calls
