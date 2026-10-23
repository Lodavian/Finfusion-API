import importlib.util
from pathlib import Path
import struct
import pytest

spec=importlib.util.spec_from_file_location('host_clock',Path(__file__).with_name('clock_probe.py'))
clock=importlib.util.module_from_spec(spec); spec.loader.exec_module(clock)

def response(t1,offset):
    sent=clock.stamp(t1); packet=bytearray(48); packet[0]=0x24;packet[1]=2
    packet[24:32]=sent;packet[32:40]=clock.stamp(t1+offset+.05);packet[40:48]=clock.stamp(t1+offset+.06)
    return packet,sent

@pytest.mark.parametrize('offset,expected',[(0.1,'PASS'),(-6,'WARNING'),(16,'ALERT'),(-31,'ALERT')])
def test_offsets_and_signed_request_margin(offset,expected):
    packet,sent=response(1700000000,offset)
    sample={'result':'MEASURED',**clock.decode(packet,sent,1700000000,1700000000.11,.11)}
    assert clock.classify([sample,sample])==expected

@pytest.mark.parametrize('damage',['origin','unsynced','stratum','mode','truncated','clockjump'])
def test_never_green_on_bad_time_evidence(damage):
    packet,sent=response(1700000000,.1); elapsed=.11
    if damage=='origin':packet[24]=0
    if damage=='unsynced':packet[0]|=0xc0
    if damage=='stratum':packet[1]=0
    if damage=='mode':packet[0]=0x23
    if damage=='truncated':packet=packet[:40]
    if damage=='clockjump':elapsed=1.5
    with pytest.raises(ValueError):clock.decode(packet,sent,1700000000,1700000000.11,elapsed)

def test_missing_or_conflicting_sources_are_not_pass():
    assert clock.classify([{'result':'UNAVAILABLE'}])=='UNVERIFIED'
    assert clock.classify([{'result':'MEASURED','offsetSeconds':0},{'result':'MEASURED','offsetSeconds':3}])=='SOURCE_DISAGREEMENT'
