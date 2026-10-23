"""Publish an audited source overlay; retain the original release and rollback link."""
import ast,datetime,hashlib,json,os,shutil,subprocess,tarfile,time,urllib.request
from pathlib import Path
os.umask(0o077)
source=Path('/home/finfusion_tech/worktrees/finfusion-client-market')
baseline='f581d3b7fc7ad42dbe07c234b48771c0fda778d8'
def git(*args):
    return subprocess.check_output(['runuser','-u','finfusion_tech','--','git','-C',str(source),*args])
assert git('rev-parse','HEAD').decode().strip()==baseline
release=Path('/opt/finfusion/releases/f581d3b-market-20261009')
assert not release.exists(),'Candidate release exists; inspect before replacing'
live=Path('/var/lib/finfusion/formal-deployment/live')
rollback=live/'market-rollback';rollback.mkdir(mode=0o700)
current=Path('/opt/finfusion/current');assert current.is_symlink()
previous=current.resolve();(rollback/'previous-release.txt').write_text(str(previous))
shutil.copyfile('/etc/finfusion/server.env',rollback/'server.env')
(rollback/'finfusion-unit.txt').write_text(subprocess.check_output(['systemctl','cat','finfusion'],text=True))
with (rollback/'finfusion_live.dump').open('wb') as f:
    subprocess.run(['runuser','-u','postgres','--','pg_dump','-Fc','finfusion_live'],stdout=f,check=True)
subprocess.run(['pg_restore','--list',str(rollback/'finfusion_live.dump')],stdout=subprocess.DEVNULL,check=True)
archive=rollback/'baseline.tar';archive.write_bytes(git('archive',baseline))
release.mkdir(mode=0o755)
with tarfile.open(archive) as f:f.extractall(release,filter='data')
overlay=['finfusion/api.py','finfusion/gateway.py','finfusion/main.py','finfusion/market.py','finfusion/account_view.py','docs/API.md','docs/MARKET.md','docs/openapi.json','tests/test_client_market.py','tests/test_account_view.py']
manifest={'baseline':baseline,'overlay':{},'environment':'LIVE','readOnly':True}
for name in overlay:
    original=source/name;target=release/name
    assert original.is_file() and not original.is_symlink()
    shutil.copyfile(original,target)
    manifest['overlay'][name]=hashlib.sha256(target.read_bytes()).hexdigest()
for p in release.rglob('*.py'):ast.parse(p.read_text(encoding='utf-8-sig'))
for p in release.rglob('*'):
    if not p.is_symlink():p.chmod(0o755 if p.is_dir() else 0o644)
(live/'market-release-manifest.json').write_text(json.dumps(manifest,indent=2))
def link(target):
    pending=current.with_name('current-market-pending')
    assert not pending.exists() and not pending.is_symlink()
    pending.symlink_to(target);os.replace(pending,current)
try:
    subprocess.run(['systemctl','stop','finfusion'],check=True)
    link(release)
    subprocess.run(['systemctl','start','finfusion'],check=True)
    for attempt in range(20):
        try:
            with urllib.request.urlopen('http://127.0.0.1:8081/livez',timeout=2) as r:assert r.status==200
            break
        except Exception:
            if attempt==19:raise
            time.sleep(1)
    print('PASS: audited market release active; original release, configuration and database rollback preserved.')
except Exception:
    subprocess.run(['systemctl','stop','finfusion'],check=False)
    link(previous)
    subprocess.run(['systemctl','start','finfusion'],check=True)
    print('Candidate activation failed; previous source release restored. Database was not restored or modified.')
    raise
