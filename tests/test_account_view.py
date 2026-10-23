import ast
from pathlib import Path
import pytest
from finfusion.account_view import usd_cash_fields
from finfusion.market import normalize_snapshot, MarketData
from finfusion.errors import ApiError
from types import SimpleNamespace
import time

@pytest.mark.parametrize('payload,expected', [
    ({'total_cash_balance':'999','account_currency_assets':[{'currency':'HKD','cash_balance':'888'},{'currency':'USD','cash_balance':'0','settled_cash':'12.50','unsettled_cash':'-12.50','buying_power':'999'}]}, {'usdCashBalance':'0','usdSettledCash':'12.50','usdUnsettledCash':'-12.50'}),
    ({'account_currency_assets':[{'currency':'HKD','cash_balance':'888'}]}, {'usdCashBalance':None,'usdSettledCash':None,'usdUnsettledCash':None}),
    ({'account_currency_assets':[{'currency':'USD','cash_balance':'NaN','settled_cash':'Infinity','unsettled_cash':'bad'}]}, {'usdCashBalance':None,'usdSettledCash':None,'usdUnsettledCash':None}),
])
def test_usd_cash_never_uses_buying_power_or_other_currency(payload,expected):
    assert usd_cash_fields(payload)==expected

def test_real_snapshot_price_and_source_timestamp():
    now=int(time.time()*1000)
    s=normalize_snapshot('AAPL',[{'symbol':'AAPL','price':'250.25','close':'240','last_trade_time':now}],{},1,True)
    assert s['lastPrice']=='250.25' and abs(s['asOf']-now/1000)<.001 and s['status']=='READY'

def test_production_entrypoint_parses():
    ast.parse((Path(__file__).resolve().parents[1]/'finfusion/main.py').read_text())

@pytest.mark.asyncio
async def test_sdk_permission_exception_is_not_generic_unavailable():
    class Denied(Exception):http_status=403
    async def call(*args):raise Denied('private broker details')
    market=MarketData(SimpleNamespace(_call=call))
    with pytest.raises(ApiError) as caught:await market.call(None)
    assert caught.value.code=='MARKET_DATA_DENIED'
    assert 'private broker' not in str(caught.value)

@pytest.mark.asyncio
async def test_real_common_stock_instrument_is_searchable():
    async def call(fn,*args):return [{'symbol':'AAPL','sub_category':'COMMON_STOCK','name':'Apple'}]
    gateway=SimpleNamespace(_call=call,CATEGORY='US_STOCK',data_client=SimpleNamespace(instrument=SimpleNamespace(get_instrument=None)))
    result=await MarketData(gateway).symbols('AAPL')
    assert result[0]['symbol']=='AAPL' and result[0]['subCategory']=='COMMON_STOCK'
