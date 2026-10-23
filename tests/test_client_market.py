import asyncio
import time
from types import SimpleNamespace
import pytest
import pytest_asyncio
from aiohttp.test_utils import TestClient, TestServer
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from finfusion.api import ServerApi
from finfusion.controls import ControlPlane, ControlSnapshot
from finfusion.models import AccountGrant, ClientGrant, RiskLimits, UserGrant
from finfusion.security import RequestAuthenticator, StaticTokenVerifier
from finfusion.service import InstitutionalTradingService
from finfusion.store import MemoryOrderStore
from finfusion.market import normalize_snapshot, normalize_trades, MarketData
from tests.test_server_api import signed_headers, ApiGateway

class MarketGateway(ApiGateway):
    CATEGORY = 'US_STOCK'
    market_healthy = True
    market_observers = None
    def __init__(self):
        self.refs = {}; self.calls = 0
        self.data_client = SimpleNamespace(instrument=SimpleNamespace(get_instrument=self.instruments), market_data=self)
    async def _call(self, fn, *args):
        self.calls += 1
        return fn(*args)
    def instruments(self,*args):
        return [{'symbol':'AAPL','name':'Apple','sub_category':'STOCK','secret':'NEVER'}]
    def get_snapshot(self,*args):
        return [{'symbol':'AAPL','close':'100.25','open':'99','high':'102','low':'98','volume':'1234','trade_time':time.time(),'secret':'NEVER'}]
    def get_quotes(self,*args):
        return {'symbol':'AAPL','bids':[{'price':'100.24','size':'5'}],'asks':[{'price':'100.26','size':'8'}]}
    def get_tick(self,*args):
        return {'symbol':'AAPL','ticks':[{'trade_id':'1','price':'100.25','volume':'1','trade_time':time.time(),'side':'BUY'}]}
    async def select_symbol(self, ref, symbol):
        self.refs[ref] = symbol
    async def release_symbol(self, ref):
        self.refs.pop(ref,None)

@pytest_asyncio.fixture
async def market_api():
    key = ec.generate_private_key(ec.SECP256R1())
    public = key.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    controls = ControlPlane(ControlSnapshot.frozen(global_trade_enabled=True,version=1,users={'u':UserGrant('u')},clients={'d':ClientGrant('d','u',public)},accounts={'a':AccountGrant('a','u','SECRET','Alias','***')}))
    gateway = MarketGateway()
    service = InstitutionalTradingService(controls,MemoryOrderStore(),gateway,limits=RiskLimits())
    tokens = StaticTokenVerifier({'good':'u'})
    api = ServerApi(service,controls,RequestAuthenticator(tokens,controls),tokens,environment_name='SANDBOX')
    client = TestClient(TestServer(api.application())); await client.start_server()
    try:
        yield client,key,gateway,controls
    finally:
        await client.close()

@pytest.mark.asyncio
async def test_signed_routes_and_shared_cache(market_api):
    client,key,gateway,_ = market_api
    for route in ('/v1/market/symbols?accountRef=a&q=AAPL','/v1/market/snapshot?accountRef=a&symbol=AAPL','/v1/market/trades?accountRef=a&symbol=AAPL','/v1/accounts/a/ui-context'):
        response = await client.get(route,headers=signed_headers(key,'GET',route))
        assert response.status == 200
        raw = await response.text(); assert 'NEVER' not in raw and 'SECRET' not in raw
    assert gateway.calls == 4
    route='/v1/market/trades?accountRef=a&symbol=AAPL&limit=201'
    assert (await client.get(route,headers=signed_headers(key,'GET',route))).status == 400

@pytest.mark.asyncio
async def test_denial_and_revoke_release(market_api):
    client,key,gateway,controls = market_api
    route='/v1/market/snapshot?accountRef=other&symbol=AAPL'
    assert (await client.get(route,headers=signed_headers(key,'GET',route))).status == 403
    route='/v1/market/events?accountRef=a&symbol=AAPL'
    socket=await client.ws_connect(route,headers=signed_headers(key,'GET',route))
    assert (await socket.receive_json())['type']=='connected'
    assert (await socket.receive_json())['snapshot']['lastPrice']=='100.25'
    assert len(gateway.refs)==1
    old=controls.snapshot
    controls.replace(ControlSnapshot.frozen(global_trade_enabled=True,version=2,users={'u':UserGrant('u',False)},clients=old.clients,accounts=old.accounts))
    await asyncio.wait_for(socket.receive(),3)
    await socket.close(); await asyncio.sleep(.1)
    assert not gateway.refs

def test_missing_stale_whitelist_and_tick_dedup():
    snap=normalize_snapshot('AAPL',[{'symbol':'AAPL','close':'NaN','app_secret':'NEVER'}],{},1,True)
    assert snap['status']=='UNAVAILABLE' and snap['lastPrice'] is None
    snap=normalize_snapshot('AAPL',[{'symbol':'AAPL','close':'1','time':time.time()-60}],{},1,True)
    assert snap['status']=='STALE' and snap['bid'] is None
    tick={'price':'1.1','size':'2','time':time.time(),'id':'same'}
    assert len(normalize_trades('AAPL',[tick,tick]))==1

@pytest.mark.asyncio
async def test_market_feed_ignores_old_timestamps(market_api):
    _,_,gateway,_=market_api
    market=MarketData(gateway); snap,_=await market.read('AAPL')
    market.feed({'symbol':'AAPL','close':'2','time':snap['asOf']-10})
    assert (await market.read('AAPL'))[0]['lastPrice']=='100.25'


@pytest.mark.asyncio
async def test_real_sdk_protobuf_snapshot_tick_and_book(market_api):
    from webull.data.quotes.subscribe import message_pb2
    from finfusion_common.utils import protobuf_to_dict
    _,_,gateway,_ = market_api
    market = MarketData(gateway)
    old, _ = await market.read('AAPL')
    message = message_pb2.Snapshot()
    message.basic.symbol = 'AAPL'
    message.trade_time = str(int((old['asOf']+1)*1000))
    message.price = '101.75'
    message.open = '99.00'
    market.feed(protobuf_to_dict(message))
    snap, _ = await market.read('AAPL')
    assert snap['lastPrice'] == '101.75'
    assert snap['high'] == '102'
    message = message_pb2.Quote()
    message.basic.symbol = 'AAPL'
    message.basic.timestamp = str(int(time.time()*1000))
    message.bids.add(price='101.74',size='4')
    market.feed(protobuf_to_dict(message))
    snap, _ = await market.read('AAPL')
    assert snap['bid'] == {'price':'101.74','size':'4'}
@pytest.mark.asyncio
async def test_slow_market_socket_does_not_block_other_client(market_api, monkeypatch):
    from aiohttp import web
    client,key,gateway,_ = market_api
    original = web.WebSocketResponse.send_json
    sockets=[]
    async def send(socket, data, **kwargs):
        if data.get('type') == 'connected':
            sockets.append(socket)
        if sockets and socket is sockets[0] and data.get('type') == 'market.update':
            await asyncio.sleep(3)
        return await original(socket,data,**kwargs)
    monkeypatch.setattr(web.WebSocketResponse,'send_json',send)
    route='/v1/market/events?accountRef=a&symbol=AAPL'
    first=await client.ws_connect(route,headers=signed_headers(key,'GET',route))
    await first.receive_json()
    second=await client.ws_connect(route,headers=signed_headers(key,'GET',route))
    await second.receive_json()
    assert (await asyncio.wait_for(second.receive_json(),1))['type']=='market.update'
    await asyncio.sleep(2.1)
    assert (await asyncio.wait_for(second.receive_json(),1))['type']=='market.update'
    await first.close(); await second.close(); await asyncio.sleep(.1)
    assert not gateway.refs
