"""Independent loopback mock: verifies canonical bytes without using client SDK."""
import asyncio
import base64
import hashlib
import json
import time
import uuid

from aiohttp import web
import pytest_asyncio
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec

from finfusion_client.security import private_pem
from finfusion_client.transport import SignedTransport


class MockServer:
    def __init__(self):
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.client_id = str(uuid.uuid4())
        self.enabled = True
        self.refs = ["account-A", "account-B"]
        self.nonces = set()
        self.mutations = []
        self.lookups = []
        self.requests = {}
        self.orders = {}
        self.mode = "normal"
        self.position_delay = 0
        self.websockets = []
        self.ws_count = 0
        self.victim_count = 0
        self.clients = []
        self.last_target = None
        self.last_body = None
        self.app = web.Application(middlewares=[self.verify])
        self.app.add_routes([
            web.get('/readyz', self.ready), web.get('/v1/accounts', self.accounts),
            web.get('/v1/accounts/{account}/positions', self.positions),
            web.get('/v1/accounts/{account}/ui-context', self.context),
            web.get('/v1/market/symbols', self.symbols),
            web.get('/v1/market/snapshot', self.snapshot),
            web.get('/v1/market/trades', self.trades),
            web.get('/v1/market/events', self.market_events),
            web.get('/v1/accounts/{account}/balance', self.balance),
            web.get('/v1/orders', self.list_orders), web.post('/v1/orders', self.mutate),
            web.get('/v1/orders/{order}', self.detail), web.patch('/v1/orders/{order}', self.mutate),
            web.post('/v1/orders/{order}/cancel', self.mutate),
            web.get('/v1/requests/{request}', self.lookup), web.get('/v1/events', self.events),
            web.get('/redirect', self.redirect), web.get('/victim', self.victim),
        ])

    def denied(self):
        return web.json_response({'error': {'code': 'ACCESS_DENIED', 'message': 'denied'}}, status=403)

    @web.middleware
    async def verify(self, request, handler):
        self.last_user_agent = request.headers.get('User-Agent','')
        if request.path == '/victim':
            return await handler(request)
        body = await request.read()
        headers = request.headers
        try:
            assert self.enabled and headers['X-Client-Id'] == self.client_id
            timestamp, nonce = headers['X-Timestamp'], headers['X-Nonce']
            assert abs(float(timestamp) - time.time()) < 30 and nonce not in self.nonces
            assert 16 <= len(nonce) <= 128
            request_id = headers.get('Idempotency-Key', '')
            if request.method in {'POST', 'PATCH'}:
                uuid.UUID(request_id)
            expected = ('FINFUSION-V1\n' + self.client_id + '\n' + request.method + '\n' +
                        request.raw_path + '\n' + hashlib.sha256(body).hexdigest() + '\n' +
                        timestamp + '\n' + nonce + '\n' + request_id).encode('utf-8')
            raw_signature = headers['X-Client-Signature']
            signature = base64.urlsafe_b64decode(raw_signature + '=' * (-len(raw_signature) % 4))
            self.key.public_key().verify(signature, expected, ec.ECDSA(hashes.SHA256()))
            account = request.match_info.get('account') or request.query.get('accountRef')
            if body:
                account = json.loads(body).get('accountRef', account)
            assert account is None or account in self.refs
            self.nonces.add(nonce)
            self.last_target, self.last_body = request.raw_path, body
        except Exception:
            return self.denied()
        return await handler(request)

    def transport(self, **kwargs):
        client = SignedTransport(self.origin, self.client_id, private_pem(self.key), test_http=True, **kwargs)
        self.clients.append(client)
        return client

    async def context(self, request):
        if self.mode == 'edge_block':
            return web.Response(text='error code: 1010',status=403,headers={'Server':'cloudflare'})
        return web.json_response({'accountRef': request.match_info['account'], 'environment': 'SANDBOX', 'tradeEnabled': True, 'cancelEnabled': True, 'riskRules': {'maxOrderQty': 1000}})

    async def symbols(self, request):
        if request.query.get('accountRef') not in self.refs:
            return self.denied()
        return web.json_response({'accountRef': request.query['accountRef'], 'symbols': [{'symbol': request.query['q'], 'name': 'Mock stock'}]})

    async def snapshot(self, request):
        self.market_reads = getattr(self, "market_reads", 0) + 1
        await asyncio.sleep(getattr(self, "market_delay", 0))
        if request.query.get('accountRef') not in self.refs:
            return self.denied()
        return web.json_response({'accountRef': request.query['accountRef'], 'symbol': request.query['symbol'], 'version': getattr(self, 'market_version', 1), 'status': 'READY', 'lastPrice': '100.25', 'asOf': time.time(), 'bid': None, 'ask': None})

    async def trades(self, request):
        return web.json_response({'accountRef': request.query['accountRef'], 'symbol': request.query['symbol'], 'trades': []})

    async def market_events(self, request):
        if request.query.get('accountRef') not in self.refs:
            return self.denied()
        socket = web.WebSocketResponse()
        await socket.prepare(request)
        self.market_sockets = getattr(self, 'market_sockets', [])
        self.market_sockets.append(socket)
        await socket.send_json({'type': 'connected'})
        async for _ in socket:
            pass
        return socket

    async def accounts(self, _request):
        return web.json_response({'accounts': [dict(accountRef=ref, alias=ref, accountMask='***1234', tradeEnabled=True) for ref in self.refs]})

    async def ready(self, _request):
        return web.json_response({'effectiveTradeEnabled': False, 'database': True}, status=503)

    async def positions(self, request):
        ref = request.match_info['account']
        await asyncio.sleep(self.position_delay)
        return web.json_response({'accountRef': ref, 'positions': [dict(symbol='AAPL', name=ref,
            quantity='3', lastPrice='100.00', unitCost='95.00', unrealizedPnl='15.00')]})

    async def balance(self, request):
        return web.json_response({'accountRef': request.match_info['account'], 'currency': 'USD', 'usdBuyingPower': None})

    async def list_orders(self, request):
        ref = request.query.get('accountRef')
        return web.json_response({'orders': [o for o in self.orders.values() if o['accountRef'] == ref], 'nextCursor': None})

    async def detail(self, request):
        order = self.orders.get(request.match_info['order'])
        if order is None:
            return web.json_response({'error': {'code': 'INVALID_REQUEST'}}, status=400)
        if order['accountRef'] != request.query.get('accountRef'):
            return self.denied()
        return web.json_response(order)

    def make_order(self, request_id, payload, order_id=None):
        order_id = order_id or 'FO' + request_id.replace('-', '')[:24]
        return dict(accountRef=payload['accountRef'], clientOrderId=order_id, requestId=request_id,
                    status='ACKNOWLEDGED', version=1, symbol=payload.get('symbol', 'AAPL'),
                    side=payload.get('side', 'BUY'), orderType=payload.get('orderType', 'LIMIT'),
                    quantity=payload.get('quantity', 1), limitPrice=payload.get('limitPrice'),
                    pendingAction=None, createdAt=time.time(), updatedAt=time.time())

    async def mutate(self, request):
        request_id = request.headers['Idempotency-Key']
        self.mutations.append((request.method, request.raw_path, request_id, await request.read()))
        if self.mode == 'readonly':
            return web.json_response({'error':{'code':'READ_ONLY_DEPLOYMENT'}},status=403)
        if self.mode == 'reject':
            return web.json_response({'error': {'code': 'INVALID_REQUEST'}}, status=400)
        if self.mode == 'conflict':
            return web.json_response({'error': {'code': 'IDEMPOTENCY_CONFLICT'}}, status=409)
        if self.mode == 'redirect':
            raise web.HTTPFound('/victim')
        payload = await request.json()
        target = request.match_info.get('order')
        if target and target in self.orders:
            order = dict(self.orders[target])
            order['version'] += 1
            if request.method == 'PATCH':
                order.update(status='REPLACED', limitPrice=payload['limitPrice'])
            else:
                order['status'] = 'CANCEL_REQUESTED'
                order['pendingAction'] = 'cancel'
        else:
            order = self.make_order(request_id, payload, target)
        if self.mode == 'pending_replace':
            order.update(status='UNKNOWN', pendingAction='replace')
        self.orders[order['clientOrderId']] = order
        if self.mode != 'missing':
            self.requests[request_id] = order['clientOrderId']
        if self.mode in {'timeout', 'missing'}:
            await asyncio.sleep(0.4)
        if self.mode == 'invalid':
            return web.Response(text='not-json')
        if self.mode == '500':
            return web.json_response({'error': {'code': 'INTERNAL_ERROR'}}, status=500)
        return web.json_response({'type': 'order.update', 'order': order, **order}, status=202)

    async def lookup(self, request):
        request_id = request.match_info['request']
        self.lookups.append(request_id)
        order_id = self.requests.get(request_id)
        if not order_id:
            return web.json_response({'error': {'code': 'INVALID_REQUEST'}}, status=400)
        return web.json_response({'type': 'order.update', 'order': self.orders[order_id]})

    async def events(self, request):
        if self.mode == 'ws_redirect':
            raise web.HTTPFound('/victim')
        socket = web.WebSocketResponse()
        await socket.prepare(request)
        self.ws_count += 1
        self.websockets.append(socket)
        self.market_sockets = getattr(self, 'market_sockets', [])
        self.market_sockets.append(socket)
        await socket.send_json({'type': 'connected'})
        async for _ in socket:
            pass
        return socket

    async def redirect(self, _request):
        raise web.HTTPFound('/victim')

    async def victim(self, _request):
        self.victim_count += 1
        return web.json_response({'ok': True})


@pytest_asyncio.fixture
async def server():
    mock = MockServer()
    runner = web.AppRunner(mock.app)
    await runner.setup()
    site = web.TCPSite(runner, '127.0.0.1', 0)
    await site.start()
    mock.origin = f'http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}'
    try:
        yield mock
    finally:
        for socket in mock.websockets:
            await socket.close()
        for client in mock.clients:
            await client.close()
        await runner.cleanup()
