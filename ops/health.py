"""Local operational health is distinct from intentional trading shutdown."""
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import pwd
import time
import urllib.request
import urllib.error

DIRECTORY=Path('/var/lib/finfusion/ops')


def fetch(url):
    try: response=urllib.request.urlopen(url,timeout=3)
    except urllib.error.HTTPError as error: response=error
    return json.loads(response.read())


def run():
    now=datetime.now(timezone.utc)
    state={'serverVersion':'1.0.0-rc1','checkedAt':now.isoformat(),'issues':[]}
    previous=json.loads((DIRECTORY/'health.json').read_text()) if (DIRECTORY/'health.json').exists() else {}
    try:
        live=fetch('http://127.0.0.1:8081/livez'); ready=fetch('http://127.0.0.1:8081/readyz')
        state['live']=live.get('ok') is True
        state['components']={k:ready.get(k) for k in ['database','brokerEvents','market','reconciliation','nodeActive','tunnel','globalTradeEnabled','effectiveTradeEnabled']}
        for name in ['database','brokerEvents','market','reconciliation']:
            if ready.get(name) is not True: state['issues'].append(name.upper()+'_UNAVAILABLE')
        state['tradingReady']=ready.get('effectiveTradeEnabled') is True
        if not state['live']: state['issues'].append('API_NOT_LIVE')
        with urllib.request.urlopen('http://127.0.0.1:2000/ready',timeout=3) as tunnel:
            if tunnel.status!=200: state['issues'].append('TUNNEL_UNAVAILABLE')
    except (OSError,ValueError): state['issues'].append('HEALTH_PROBE_FAILED')
    # Check the real program ingress, not only a connected Tunnel connector.
    # Use an honest application identity; never impersonate a web browser.
    if time.time()-previous.get('publicCheckedEpoch',0)>=300:
        state['publicCheckedEpoch']=time.time()
        try:
            request=urllib.request.Request('https://api.finfusion.asia/livez',headers={'User-Agent':'FinfusionServerHealth/1.0.0-rc1'})
            with urllib.request.urlopen(request,timeout=5) as response:
                state['publicStatus']=response.status
        except urllib.error.HTTPError as error: state['publicStatus']=error.code
        except OSError: state['publicStatus']=0
    else:
        state['publicCheckedEpoch']=previous.get('publicCheckedEpoch',0)
        state['publicStatus']=previous.get('publicStatus',0)
    if state['publicStatus']!=200:
        state['issues'].append('PUBLIC_API_BLOCKED' if state['publicStatus']==403 else 'PUBLIC_API_UNAVAILABLE')
    if (DIRECTORY/'backup.json').exists():
        backup=json.loads((DIRECTORY/'backup.json').read_text()); state['backupStatus']=backup.get('status')
        success=backup.get('lastSuccess')
        if not success or (now-datetime.fromisoformat(success)).total_seconds()>26*3600: state['issues'].append('BACKUP_STALE')
        if backup.get('status')=='FAIL': state['issues'].append('BACKUP_FAILED')
    else: state['issues'].append('BACKUP_MISSING')
    state['consecutiveFailures']=previous.get('consecutiveFailures',0)+1 if state['issues'] else 0
    state['status']='ALERT' if state['consecutiveFailures']>=3 else 'WARNING' if state['issues'] else 'OK'
    DIRECTORY.mkdir(mode=0o750,parents=True,exist_ok=True)
    gid=pwd.getpwnam('finfusion').pw_gid; os.chown(DIRECTORY,0,gid); DIRECTORY.chmod(0o750)
    path=DIRECTORY/'health.tmp'; path.write_text(json.dumps(state,indent=2)); os.chown(path,0,gid); path.chmod(0o640); os.replace(path,DIRECTORY/'health.json')
    if state['status']=='ALERT': print('Finfusion local alert: '+','.join(state['issues']))


if __name__=='__main__': run()
