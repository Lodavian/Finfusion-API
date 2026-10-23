import hashlib,json,os,subprocess,time,urllib.request
from pathlib import Path
live=Path('/var/lib/finfusion/formal-deployment/live')
release=Path('/opt/finfusion/releases/f581d3b-market-20261009')
manifest=json.loads((live/'market-release-manifest.json').read_text())
for name,digest in manifest['overlay'].items():assert hashlib.sha256((release/name).read_bytes()).hexdigest()==digest
release.chmod(0o755)
current=Path('/opt/finfusion/current');previous=current.resolve()
def link(target):
    pending=current.with_name('current-market-pending')
    assert not pending.exists() and not pending.is_symlink()
    pending.symlink_to(target);os.replace(pending,current)
try:
    subprocess.run(['systemctl','stop','finfusion'],check=True)
    subprocess.run(['systemctl','reset-failed','finfusion'],check=True)
    link(release);subprocess.run(['systemctl','start','finfusion'],check=True)
    for attempt in range(30):
        try:
            with urllib.request.urlopen('http://127.0.0.1:8081/livez',timeout=2) as r:assert r.status==200
            break
        except Exception:
            if attempt==29:raise
            time.sleep(1)
    print('PASS: audited market source active; loopback health 200; rollback retained.')
except Exception:
    subprocess.run(['systemctl','stop','finfusion'],check=False)
    link(previous);subprocess.run(['systemctl','reset-failed','finfusion'],check=False)
    subprocess.run(['systemctl','start','finfusion'],check=True)
    print('Candidate failed; old release restored.')
    raise
