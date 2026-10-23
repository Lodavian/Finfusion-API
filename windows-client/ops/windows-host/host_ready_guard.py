"""Read formal Linux unit directly; never trust the connectivity-only proxy."""
import json
from pathlib import Path
import re
import subprocess
import urllib.error
import urllib.request


def confirmed(service, environment, owner_matches, status, ready):
    return (service == 'active' and environment == 'LIVE' and owner_matches is True
            and status in (200, 503) and isinstance(ready, dict)
            and ready.get('globalTradeEnabled') is False
            and ready.get('effectiveTradeEnabled') is False
            and ready.get('infrastructureReason') != 'connectivity-only-brokers-disconnected')


def run():
    result = {'offConfirmed': False, 'source': 'FORMAL_WSL_UNIT_DIRECT', 'mutations': 0}
    try:
        env = {}
        for line in Path('/etc/finfusion/server.env').read_text().splitlines():
            if line.startswith(('FINFUSION_PORT=', 'FINFUSION_ENVIRONMENT=')):
                key, value = line.split('=', 1); env[key] = value.strip().strip('"').strip("'")
        port = int(env['FINFUSION_PORT']); assert 1 <= port <= 65535
        service = subprocess.run(['systemctl', 'is-active', 'finfusion.service'], capture_output=True, text=True).stdout.strip()
        pid = int(subprocess.check_output(['systemctl', 'show', 'finfusion.service', '-p', 'MainPID', '--value'], text=True))
        owner = subprocess.check_output(['ss', '-ltnp', f'sport = :{port}'], text=True)
        matches = pid > 0 and re.search(r'\bpid='+str(pid)+r'\b', owner) is not None
        result.update(formalService=service, environment=env.get('FINFUSION_ENVIRONMENT'), port=port, listenerOwnedByFormalUnit=matches)
        if service != 'active' or not matches:
            return result
        # Ignore HTTP_PROXY and use the formal process's own Linux loopback listener.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try: response = opener.open(f'http://127.0.0.1:{port}/readyz', timeout=5)
        except urllib.error.HTTPError as error: response = error
        with response:
            ready = json.loads(response.read()); status = response.status
        result.update(httpStatus=status, globalTradeEnabled=ready.get('globalTradeEnabled'),
                      effectiveTradeEnabled=ready.get('effectiveTradeEnabled'))
        result['offConfirmed'] = confirmed(service, env.get('FINFUSION_ENVIRONMENT'), matches, status, ready)
    except (OSError, ValueError, KeyError, AssertionError, subprocess.SubprocessError) as error:
        result['reason'] = type(error).__name__
    return result


if __name__ == '__main__':
    import time
    deadline = time.monotonic() + 30
    while True:
        proof = run()
        # A fresh WSL start can still be bringing up systemd dependencies. Retry reads only.
        warming = (proof.get('formalService') in ('inactive', 'activating') or
                   proof.get('formalService') == 'active' and 'httpStatus' not in proof)
        if not warming or time.monotonic() >= deadline:
            break
        time.sleep(2)
    print(json.dumps(proof))
