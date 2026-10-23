import importlib.util
from pathlib import Path
import pytest

spec=importlib.util.spec_from_file_location('host_ready_guard',Path(__file__).with_name('host_ready_guard.py'))
guard=importlib.util.module_from_spec(spec);spec.loader.exec_module(guard)

@pytest.mark.parametrize('case',['active','inactive','wrong_owner','sandbox','missing','null','numeric','enabled','connectivity','error'])
def test_only_formal_verified_false_is_accepted(case):
    service='active';environment='LIVE';owner=True;status=503
    ready={'globalTradeEnabled':False,'effectiveTradeEnabled':False}
    if case=='inactive':service='inactive'
    if case=='wrong_owner':owner=False
    if case=='sandbox':environment='SANDBOX'
    if case=='missing':ready={}
    if case=='null':ready['globalTradeEnabled']=None
    if case=='numeric':ready['effectiveTradeEnabled']=0
    if case=='enabled':ready['effectiveTradeEnabled']=True
    if case=='connectivity':ready['infrastructureReason']='connectivity-only-brokers-disconnected'
    if case=='error':status=500
    assert guard.confirmed(service,environment,owner,status,ready)==(case=='active')
