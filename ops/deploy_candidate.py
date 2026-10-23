"""Atomic read-only Server 1.0 upgrade with a verified rollback pointer."""
from datetime import datetime, timezone
import hashlib
import ast
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import urllib.request
import urllib.error

SOURCE=Path('/home/finfusion_tech/worktrees/finfusion-server-1.0')
CURRENT=Path('/opt/finfusion/current')
RELEASES=Path('/opt/finfusion/releases')


def ready():
    try:
        with urllib.request.urlopen('http://127.0.0.1:8081/livez',timeout=3) as response:
            if json.loads(response.read()).get('ok') is not True: return False
        try: response=urllib.request.urlopen('http://127.0.0.1:8081/readyz',timeout=3)
        except urllib.error.HTTPError as e: response=e
        data=json.loads(response.read())
        return data.get('database') is True and data.get('brokerEvents') is True and data.get('market') is True and data.get('reconciliation') is True and data.get('globalTradeEnabled') is False and data.get('effectiveTradeEnabled') is False
    except (OSError,ValueError): return False


def switch(target):
    assert target.parent==RELEASES and target.is_dir()
    pointer=CURRENT.with_name('current.server-1.0-staging')
    if pointer.exists() or pointer.is_symlink(): raise RuntimeError('Staging pointer exists')
    pointer.symlink_to(target); os.replace(pointer,CURRENT)
    subprocess.run(['systemctl','restart','finfusion'],check=True)


def run():
    assert os.geteuid()==0
    previous=CURRENT.resolve()
    assert previous.parent==RELEASES and ready()
    assert subprocess.run(['systemctl','is-active','--quiet','finfusion-api-tunnel','casdoor','nginx']).returncode==0
    subprocess.run(['/opt/finfusion/venv/bin/python','-I','-B','/opt/finfusion-ops/backup.py'],check=True)
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    rollback=Path('/var/lib/finfusion/formal-deployment/live/rollback')/('server-1.0-'+stamp)
    rollback.mkdir(parents=True,mode=0o700)
    (rollback/'previous-release.txt').write_text(str(previous))
    target=RELEASES/('server-1.0.0-rc1-'+stamp)
    assert not target.exists()
    target.mkdir(mode=0o755)
    for name in ['finfusion','finfusion_common','server_admin']:
        shutil.copytree(SOURCE/name,target/name,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    shutil.copytree(SOURCE/'docs',target/'docs',ignore=shutil.ignore_patterns('__pycache__'))
    changed={'finfusion/api.py','finfusion/main.py','finfusion/__init__.py','finfusion/deployment.py','finfusion/gateway.py'}
    def methods(path):
        tree=ast.parse(path.read_text())
        cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='InstitutionalWebullGateway')
        return {n.name:ast.dump(n,include_attributes=False) for n in cls.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))}
    old_methods=methods(previous/'finfusion/gateway.py'); new_methods=methods(target/'finfusion/gateway.py')
    for name,code in old_methods.items():
        if name not in {'__init__','_start_market','_subscribe_many'}:
            assert new_methods[name]==code, 'Trading gateway method changed'
    for package in ['finfusion','finfusion_common','server_admin']:
        for old in (previous/package).rglob('*'):
            if old.is_file() and '__pycache__' not in old.parts and old.suffix!='.pyc':
                rel=old.relative_to(previous)
                if str(rel) not in changed:
                    assert hashlib.sha256(old.read_bytes()).digest()==hashlib.sha256((target/rel).read_bytes()).digest(), 'Unexpected production core/UI change'
    files={str(p.relative_to(target)):hashlib.sha256(p.read_bytes()).hexdigest() for p in target.rglob('*') if p.is_file()}
    manifest={'version':'1.0.0-rc1','baseline':'f581d3b7fc7ad42dbe07c234b48771c0fda778d8','release':str(target),'previous':str(previous),
        'deploymentMode':'READ_ONLY','files':files,'rollback':str(rollback)}
    (target/'release-manifest.json').write_text(json.dumps(manifest,indent=2))
    try:
        switch(target)
        deadline=time.monotonic()+120
        while time.monotonic()<deadline:
            if ready(): break
            time.sleep(2)
        else: raise RuntimeError('Candidate health timeout')
        subprocess.run(['/opt/finfusion/venv/bin/python','-I','-B','/opt/finfusion-ops/health.py'],check=True)
        subprocess.run(['/opt/finfusion/venv/bin/python','-I','-B','/opt/finfusion-ops/backup.py'],check=True)
        (rollback/'result.json').write_text(json.dumps({'status':'PASS','release':str(target),'readOnly':True}))
        print('Server 1.0 read-only deployed:',target)
    except Exception:
        switch(previous)
        (rollback/'result.json').write_text(json.dumps({'status':'ROLLED_BACK','release':str(previous)}))
        raise


if __name__=='__main__': run()
