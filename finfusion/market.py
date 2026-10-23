"""Public market DTOs over the existing, shared broker data connection."""
import asyncio
import hashlib
import json
import time
from datetime import datetime
from decimal import Decimal, InvalidOperation
from finfusion_common.utils import response_json, response_ok, normalize_symbol
from .errors import ApiError


def decimal(value):
    try:
        number = Decimal(str(value))
        return str(number) if number.is_finite() else None
    except (InvalidOperation, TypeError, ValueError):
        return None


def timestamp(value):
    try:
        number = float(value)
        if number > 1e11:
            number /= 1000
        return number if 0 < number <= time.time() + 60 else None
    except (ValueError, TypeError):
        try:
            parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
            return timestamp(parsed.timestamp()) if parsed.tzinfo else None
        except ValueError:
            return None


def objects(data, inherited=None):
    if isinstance(data, dict):
        basic = data.get("basic") if isinstance(data.get("basic"), dict) else {}
        inherited = data.get("symbol") or basic.get("symbol") or inherited
        yield {**data, **({"symbol": inherited} if inherited else {})}
        for value in data.values():
            yield from objects(value, inherited)
    elif isinstance(data, list):
        for value in data:
            yield from objects(value, inherited)


def first(data, *names):
    for name in names:
        if name in data and data[name] is not None:
            return data[name]
    return None


def normalize_snapshot(symbol, data, quotes, version, healthy, stale_seconds=8):
    source = next((r for r in objects(data) if r.get('symbol') == symbol and any(k in r for k in ('close', 'last_price', 'lastPrice', 'price'))), {})
    if isinstance(source.get('snapshot'), dict):
        source = source['snapshot']
    as_of = timestamp(first(source, 'last_trade_time', 'trade_time', 'timestamp', 'time', 'update_time', 'asOf'))
    result = {'symbol': symbol, 'version': version, 'currency': 'USD', 'asOf': as_of,
              'receivedAt': time.time(), 'status': 'UNAVAILABLE', 'bid': None, 'ask': None, 'spread': None}
    fields = {'lastPrice': ('price','last_price','lastPrice','close'), 'change': ('change',),
              'changePercent': ('change_ratio','change_percent','changePercent'),
              'open': ('open',), 'high': ('high',), 'low': ('low',), 'volume': ('volume',)}
    for name, aliases in fields.items():
        result[name] = decimal(first(source, *aliases))
        if name in ('lastPrice','open','high','low','volume') and result[name] is not None and Decimal(result[name]) < (0 if name == 'volume' else Decimal('0.000000000001')):
            result[name] = None
    if 'change_ratio' in source and result['changePercent'] is not None:
        result['changePercent'] = str(Decimal(result['changePercent']) * 100)
    for r in objects(quotes):
        if r.get('symbol') not in (None, symbol):
            continue
        for side in ('bid', 'ask'):
            rows = first(r, side + 's', side + '_list', side)
            if isinstance(rows, list) and rows:
                rows = rows[0]
            if isinstance(rows, dict):
                price, size = decimal(rows.get('price')), decimal(first(rows, 'size', 'volume', 'quantity'))
                if price is not None and size is not None:
                    result[side] = {'price': price, 'size': size}
    if result['bid'] and result['ask']:
        result['spread'] = str(Decimal(result['ask']['price']) - Decimal(result['bid']['price']))
    if result['lastPrice'] is not None:
        result['status'] = 'READY' if healthy and as_of is not None and 0 <= time.time() - as_of <= stale_seconds else 'STALE'
    return result


def normalize_trades(symbol, data):
    trades = {}
    for r in objects(data):
        if r.get('symbol') not in (None, symbol):
            continue
        price, size = decimal(r.get('price')), decimal(first(r, 'volume', 'size', 'quantity'))
        moment = timestamp(first(r, 'trade_time', 'timestamp', 'time'))
        if price is None or size is None or moment is None:
            continue
        key = str(first(r, 'trade_id', 'sequence', 'id') or hashlib.sha256(f'{moment}|{price}|{size}'.encode()).hexdigest()[:24])
        side = str(first(r, 'side', 'direction') or '').upper()
        trades[key] = {'id': key, 'time': moment, 'price': price, 'size': size, 'side': side if side in ('BUY','SELL') else None}
    return sorted(trades.values(), key=lambda t: t['time'], reverse=True)[:200]


class MarketData:
    def __init__(self, gateway, stale_seconds=8):
        self.gateway = gateway
        self.stale_seconds = stale_seconds
        self.cache = {}
        self.version = 0
        self.lock = asyncio.Lock()
        self.search_cache = {}
        self.loop = None
        observers = getattr(gateway, "market_observers", None)
        if observers is not None:
            observers.append(self.observe)

    def observe(self, payload):
        if self.loop is not None:
            self.loop.call_soon_threadsafe(self.feed, payload)

    def feed(self, payload):
        for symbol, cached in tuple(self.cache.items()):
            relevant = [r for r in objects(payload) if r.get("symbol") == symbol]
            if not relevant:
                continue
            old = cached[1]
            normalized = normalize_snapshot(symbol, relevant, relevant, self.version + 1, self.gateway.market_healthy, self.stale_seconds)
            if normalized['asOf'] is None:
                if normalized['bid'] is None and normalized['ask'] is None:
                    continue
                self.version += 1
                merged = dict(old)
                for side in ('bid', 'ask', 'spread'):
                    if normalized[side] is not None:
                        merged[side] = normalized[side]
                quote_times = [timestamp(first(r, 'quote_time', 'timestamp', 'time') or first(r.get('basic', {}), 'timestamp')) for r in relevant]
                quote_times = [t for t in quote_times if t is not None]
                quote_time = max(quote_times) if quote_times else None
                if quote_time is None or quote_time < old.get('bookAsOf', 0):
                    continue
                merged['bookAsOf'] = quote_time
                merged['version'] = self.version
                self.cache[symbol] = (cached[0], merged, cached[2])
                continue
            if old['asOf'] is not None and normalized['asOf'] < old['asOf']:
                continue
            self.version += 1
            merged = {**old, **{k: v for k, v in normalized.items() if v is not None}}
            merged['version'] = self.version
            trades = {t['id']: t for t in cached[2]}
            trades.update({t['id']: t for t in normalize_trades(symbol, relevant)})
            self.cache[symbol] = (cached[0], merged, sorted(trades.values(), key=lambda t: t['time'], reverse=True)[:200])

    async def call(self, function, *args):
        try:
            response = await self.gateway._call(function, *args)
        except Exception as exc:
            if getattr(exc, 'http_status', None) in (401, 403):
                raise ApiError('MARKET_DATA_DENIED', 'Broker market permission denied', 403) from None
            raise ApiError('MARKET_DATA_UNAVAILABLE', '行情暂不可用', 503) from None
        if int(getattr(response, 'status_code', 200)) in (401,403):
            raise ApiError('MARKET_DATA_DENIED', '券商行情权限不足', 403)
        if not response_ok(response):
            raise ApiError('MARKET_DATA_UNAVAILABLE', '行情暂不可用', 503)
        return response_json(response)

    async def symbols(self, code):
        code = normalize_symbol(code)
        async with self.lock:
            if code in self.search_cache and time.monotonic() - self.search_cache[code][0] < 30:
                return self.search_cache[code][1]
            client = getattr(self.gateway, 'data_client', None)
            if client is None:
                raise ApiError('MARKET_DATA_UNAVAILABLE', '行情连接未就绪', 503)
            raw = await self.call(client.instrument.get_instrument, [code], self.gateway.CATEGORY)
            rows = []
            for r in objects(raw):
                if r.get('symbol') != code:
                    continue
                category = str(first(r,'sub_category','subCategory') or '').upper()
                if category not in ('STOCK','COMMON_STOCK','ETF','EQUITY','', 'US_STOCK'):
                    continue
                item = {'symbol': code, 'name': str(first(r,'name','instrument_name') or '')[:160],
                        'exchange': str(first(r,'exchange_code','exchange') or '')[:30], 'subCategory': category}
                if item not in rows:
                    rows.append(item)
            self.search_cache[code] = (time.monotonic(), rows[:12])
            # Bounded cache, never retains broker credentials or raw responses.
            if len(self.search_cache) > 256:
                self.search_cache.pop(next(iter(self.search_cache)))
            return rows[:12]

    async def read(self, symbol):
        self.loop = asyncio.get_running_loop()
        symbol = normalize_symbol(symbol)
        async with self.lock:
            cached = self.cache.get(symbol)
            if cached and time.monotonic() - cached[0] < 2:
                snap = dict(cached[1])
                if snap['status'] == 'READY' and (not self.gateway.market_healthy or time.time() - snap['asOf'] > self.stale_seconds):
                    snap['status'] = 'STALE'
                return snap, cached[2]
            client = getattr(self.gateway, 'data_client', None)
            if client is None:
                raise ApiError('MARKET_DATA_UNAVAILABLE', '行情连接未就绪', 503)
            market = client.market_data
            snapshot = await self.call(market.get_snapshot, [symbol], self.gateway.CATEGORY, False, False)
            quotes = await self.call(market.get_quotes, symbol, self.gateway.CATEGORY, 1, False)
            ticks = await self.call(market.get_tick, symbol, self.gateway.CATEGORY, '200')
            self.version += 1
            normalized = normalize_snapshot(symbol, snapshot, quotes, self.version, self.gateway.market_healthy, self.stale_seconds)
            trades = normalize_trades(symbol, ticks)
            if cached:
                previous = cached[1]
                if previous['asOf'] is not None and (normalized['asOf'] is None or previous['asOf'] > normalized['asOf']):
                    normalized = {**previous, 'version': self.version, 'receivedAt': time.time()}
                    normalized['status'] = 'READY' if self.gateway.market_healthy and 0 <= time.time() - normalized['asOf'] <= self.stale_seconds else 'STALE'
                combined = {t['id']: t for t in trades}
                combined.update({t['id']: t for t in cached[2]})
                trades = sorted(combined.values(), key=lambda t: t['time'], reverse=True)[:200]
            self.cache[symbol] = (time.monotonic(), normalized, trades)
            if len(self.cache) > 256:
                self.cache.pop(next(iter(self.cache)))
            return dict(normalized), trades
