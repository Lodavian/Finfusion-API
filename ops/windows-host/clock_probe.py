"""Diagnostic only: never changes clocks, services, permissions or orders."""
import argparse
import concurrent.futures
import json
from pathlib import Path
import socket
import struct
import subprocess
import time

EPOCH = 2208988800


def stamp(value):
    seconds = value + EPOCH
    return struct.pack('!II', int(seconds), int((seconds % 1) * 2**32))


def timestamp(value):
    seconds, fraction = struct.unpack('!II', value)
    return seconds - EPOCH + fraction / 2**32


def decode(packet, sent, t1, t4, elapsed):
    if len(packet) < 48 or packet[0] & 7 != 4 or packet[0] >> 6 == 3:
        raise ValueError('INVALID_NTP_RESPONSE')
    if not 1 <= packet[1] <= 15 or packet[24:32] != sent or packet[40:48] == b'\0'*8:
        raise ValueError('INVALID_NTP_RESPONSE')
    if abs((t4-t1)-elapsed) > 0.2:
        raise ValueError('LOCAL_CLOCK_CHANGED_DURING_PROBE')
    t2, t3 = timestamp(packet[32:40]), timestamp(packet[40:48])
    delay = (t4-t1)-(t3-t2)
    if t3 < t2 or delay < -0.01 or delay > 2:
        raise ValueError('UNRELIABLE_NTP_DELAY')
    return {'offsetSeconds': round(((t2-t1)+(t3-t4))/2, 4),
            'rttSeconds': round(max(delay, 0), 4), 'stratum': packet[1]}


def probe(server):
    try:
        address = socket.getaddrinfo(server, 123, socket.AF_INET, socket.SOCK_DGRAM)[0][4]
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.settimeout(3)
            sock.connect(address)
            t1, tick = time.time(), time.monotonic()
            sent = stamp(t1)
            request = bytearray(48); request[0] = 0x23; request[40:48] = sent
            sock.send(request)
            packet = sock.recv(512)
            t4, elapsed = time.time(), time.monotonic()-tick
        return {'server': server, 'result': 'MEASURED', **decode(packet, sent, t1, t4, elapsed)}
    except (OSError, ValueError) as exc:
        return {'server': server, 'result': 'UNAVAILABLE', 'reason': type(exc).__name__}


def classify(samples):
    good = [x for x in samples if x['result'] == 'MEASURED']
    if len(good) < 2:
        return 'UNVERIFIED'
    if max(x['offsetSeconds'] for x in good)-min(x['offsetSeconds'] for x in good) > 2:
        return 'SOURCE_DISAGREEMENT'
    offset = max(abs(x['offsetSeconds']) for x in good)
    return 'ALERT' if offset >= 15 else 'WARNING' if offset >= 5 else 'PASS'


def run(distro):
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        samples = list(pool.map(probe, ['time.windows.com', 'time.cloudflare.com']))
    report = {'timestampUtc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
              'externalTime': classify(samples), 'samples': samples,
              'diagnosticNtpUnauthenticated': True, 'productionWrites': 0, 'orders': 0}
    code = """import time,json,subprocess,pathlib
units=['finfusion.service','finfusion-api-tunnel.service','postgresql.service','casdoor.service','finfusion-node-default-off.service','finfusion-backup-1.0.timer','finfusion-health-1.0.timer']
health=pathlib.Path('/var/lib/finfusion/ops/health.json')
state=json.loads(health.read_text()) if health.exists() else {}
print(json.dumps({'epoch':time.time(),'bootId':pathlib.Path('/proc/sys/kernel/random/boot_id').read_text().strip(),'pid1':subprocess.check_output(['ps','-p','1','-o','comm='],text=True).strip(),'services':{u:subprocess.run(['systemctl','is-active',u],capture_output=True,text=True).stdout.strip() for u in units},'operationsStatus':state.get('status'),'tradeEnabled':state.get('components',{}).get('effectiveTradeEnabled'),'healthCheckedAt':state.get('checkedAt')}))
"""
    before = time.time()
    try:
        process = subprocess.run(['wsl.exe','-d',distro,'-u','root','--cd','/',
                                  '--exec','/usr/bin/python3','-c',code],
                                 capture_output=True, text=True, encoding='utf-8', timeout=15)
        after = time.time()
        data = json.loads(process.stdout)
        epoch = data.pop('epoch')
        # Bracket sampling time instead of treating WSL process startup latency as clock skew.
        data['clockOutsideHostIntervalSeconds'] = round(max(before-epoch, epoch-after, 0), 4)
        data['probeDurationSeconds'] = round(after-before, 4)
        data['clockComparison'] = ('INCONCLUSIVE' if after-before > 5 else
                                   'PASS' if data['clockOutsideHostIntervalSeconds'] < 1 else 'ALERT')
        report['wsl'] = data
    except (OSError, ValueError, subprocess.TimeoutExpired):
        report['wsl'] = {'result': 'UNAVAILABLE'}
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--distro', default='Ubuntu')
    parser.add_argument('--output', required=True); args = parser.parse_args()
    output = Path(args.output); output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(run(args.distro), ensure_ascii=False, indent=2), encoding='utf-8')
