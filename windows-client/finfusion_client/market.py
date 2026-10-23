"""Read-only market subscription, isolated from the order journal."""
import asyncio
from contextlib import suppress
from .transport import ApiFailure


class Market:
    def __init__(self, engine, notify):
        self.engine, self.notify = engine, notify
        self.generation = 0
        self.task = None
        self.symbol = None
        self.version = -1

    async def stop(self):
        self.generation += 1
        self.symbol = None
        if self.task:
            self.task.cancel()
            with suppress(asyncio.CancelledError):
                await self.task
            self.task = None
        self.notify("market_clear", {})

    async def select(self, symbol):
        await self.stop()
        if not self.engine.connected or not self.engine.selected:
            raise ValueError("请先选择授权账户")
        if not isinstance(symbol, str) or not symbol or len(symbol) > 32 or not all(c.isalnum() or c in '.-' for c in symbol):
            raise ValueError("请输入完整股票代码")
        self.symbol, self.version = symbol.upper(), -1
        self.task = asyncio.create_task(self._run(self.generation, self.engine.selected, self.symbol))

    async def search(self, code):
        if not self.engine.selected:
            raise ValueError("请先选择授权账户")
        token = self.engine.generation
        try:
            result = await self.engine.transport.request("GET", "/v1/market/symbols", query={"accountRef": self.engine.selected, "q": code.strip().upper()})
        except ApiFailure as exc:
            if token == self.engine.generation and exc.status == 404:
                self.notify("market_clear", {"status": "NOT_SUPPORTED"})
                raise ValueError("服务器尚未部署行情接口，股票查询暂不可用") from None
            raise
        return result if token == self.engine.generation else {"symbols": []}

    async def _run(self, token, account, symbol):
        query = {"accountRef": account, "symbol": symbol}
        transport = self.engine.transport
        delay = 0
        def active():
            return token == self.generation and account == self.engine.selected and transport is self.engine.transport
        async def snapshot():
            for endpoint, kind in (("snapshot", "market"), ("trades", "trades")):
                result = await transport.request("GET", "/v1/market/" + endpoint, query=query)
                if active():
                    self._accept(kind, result, account, symbol)
        while active():
            try:
                self.version = -1
                await snapshot()
                async for event in transport.stream("/v1/market/events", query=query):
                    if not active():
                        return
                    if event.get("type") == "connected":
                        await snapshot()
                    elif event.get("type") == "market.update":
                        accepted = self._accept("market", event.get("snapshot", {}), account, symbol)
                        if accepted and "trades" in event:
                            self._accept("trades", event["trades"], account, symbol)
                    delay = 0
            except ApiFailure as exc:
                if active():
                    self.notify("market_clear", {"status": "EDGE_BLOCKED" if exc.code == "EDGE_BLOCKED" else "DENIED" if exc.status == 403 else "NOT_SUPPORTED" if exc.status == 404 else "UNAVAILABLE"})
                if exc.status in {403, 404}:
                    return
            except asyncio.CancelledError:
                raise
            except Exception:
                if active():
                    self.notify("market_clear", {"status": "UNAVAILABLE"})
            if active():
                self.notify("market_clear", {"status": "UNAVAILABLE"})
            await asyncio.sleep((1, 2, 4, 8, 16, 30)[min(delay, 5)])
            delay += 1

    def _accept(self, kind, data, account, symbol):
        if data.get("accountRef") != account or data.get("symbol") != symbol:
            raise ApiFailure("INVALID_RESPONSE")
        if kind == "market":
            version = data.get("version")
            if type(version) is not int or version < 0:
                raise ApiFailure("INVALID_RESPONSE")
            if version < self.version:
                return False
            self.version = version
        self.notify(kind, data)
        return True
