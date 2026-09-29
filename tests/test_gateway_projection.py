from pathlib import Path
from types import SimpleNamespace
import pytest
from finfusion.gateway import GatewayConfig, InstitutionalWebullGateway


class Response:
    status_code = 200
    def __init__(self, payload): self.payload=payload
    def json(self): return self.payload


async def test_gateway_projects_account_data_without_raw_secrets():
    gateway=InstitutionalWebullGateway(GatewayConfig("unused","unused",Path("unused")))
    row={"currency":"USD","instrument_type":"STOCK","symbol":"AAPL","qty":"2","last_price":"100","unit_cost":"90","unrealized_profit_loss":"20","account_id":"SECRET"}
    gateway.trade_client=SimpleNamespace(account_v2=SimpleNamespace(
        get_account_position=lambda account:Response({"positions":[row]}),
        get_account_balance=lambda account:Response({"account_currency_assets":[{"currency":"USD","buying_power":"500.25","account_id":"SECRET"}]})))
    positions=await gateway.get_positions("SECRET")
    assert positions and positions[0]["quantity"]=="2"
    assert "SECRET" not in str(positions)
    assert await gateway.get_balance("SECRET")=={"currency":"USD","usdBuyingPower":"500.25"}


async def test_disconnected_market_does_not_use_cached_quote():
    import time
    from decimal import Decimal
    gateway=InstitutionalWebullGateway(GatewayConfig("unused","unused",Path("unused")))
    gateway._market_cache["AAPL"]=(Decimal("100"),time.time())
    assert await gateway.fresh_price("AAPL",8) is None
