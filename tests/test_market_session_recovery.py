from pathlib import Path
from types import SimpleNamespace
import pytest
from finfusion.gateway import GatewayConfig,InstitutionalWebullGateway


class InvalidSession(Exception):
    http_status=417
    error_code='INVALID_SESSION'


@pytest.mark.parametrize('second_fails',[False,True])
async def test_invalid_quote_session_recreates_only_market_connection_once(second_fails):
    gateway=InstitutionalWebullGateway(GatewayConfig('synthetic','synthetic',Path('unused')))
    calls=[]
    def bad(*args): calls.append('old-subscribe'); raise InvalidSession()
    old=SimpleNamespace(subscribe=bad,disconnect=lambda:calls.append('disconnect'),loop_stop=lambda:calls.append('loop-stop'))
    gateway.streaming_client=old; gateway.market_healthy=True; gateway._subscribed={'AAPL','NVDA'}
    def subscribe(symbols,*args):
        calls.append(('new-subscribe',set(symbols)))
        if second_fails: raise InvalidSession()
    async def start():
        calls.append('new-market'); gateway.streaming_client=SimpleNamespace(subscribe=subscribe); gateway.market_healthy=True
    async def call(function,*args,**kwargs): return function(*args)
    gateway._start_market=start; gateway._call=call
    if second_fails:
        with pytest.raises(InvalidSession): await gateway._subscribe_many(('NVDA',))
        assert not gateway.market_healthy
    else:
        await gateway._subscribe_many(('NVDA',)); assert gateway.market_healthy
    assert calls.count('new-market')==1
    assert calls.count('old-subscribe')==1
    assert ('new-subscribe',{'AAPL','NVDA'}) in calls
    assert not gateway._recovering_market
