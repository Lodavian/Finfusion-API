"""Production reads only; encrypt fresh consistent database snapshots."""
import asyncio
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import pwd
import shutil
import subprocess
import sys
import tarfile
import tempfile
import uuid

ROOT=Path(__file__).resolve().parent
BACKUPS=Path('/var/lib/finfusion/backups/live')
STATUS=Path('/var/lib/finfusion/ops/backup.json')
IDENTITY=Path('/var/lib/finfusion/formal-deployment/live/secrets-identity.txt')
PYTHON='/opt/finfusion/venv/bin/python'


def write_status(value):
    STATUS.parent.mkdir(parents=True,exist_ok=True,mode=0o750)
    gid=pwd.getpwnam('finfusion').pw_gid
    os.chown(STATUS.parent,0,gid); STATUS.parent.chmod(0o750)
    temporary=STATUS.with_suffix('.tmp'); temporary.write_text(json.dumps(value,indent=2),encoding='utf-8')
    os.chown(temporary,0,gid); temporary.chmod(0o640); os.replace(temporary,STATUS)


def call(args):
    result=subprocess.run(list(map(str,args)),stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    if result.returncode: raise RuntimeError('backup_subprocess_failed')
    return result.stdout


def retention(directory):
    directory=directory.resolve()
    if directory!=BACKUPS.resolve(): raise ValueError('backup root mismatch')
    records=[]
    for path in directory.glob('live-db-*.json'):
        if path.is_symlink(): raise ValueError('backup symlink rejected')
        data=json.loads(path.read_text()); date=datetime.fromisoformat(data['createdAt'])
        archive=directory/data['filename']
        if archive.parent!=directory or archive.is_symlink() or not archive.is_file(): raise ValueError('invalid archive')
        records.append((date,path,archive))
    records.sort(reverse=True)
    keep={item[1] for item in records[:7]}
    weeks=set()
    for date,path,_ in records:
        week=date.isocalendar()[:2]
        if week not in weeks and len(weeks)<4: weeks.add(week); keep.add(path)
    for _,path,archive in records:
        if path not in keep: archive.unlink(); path.unlink()


def run():
    assert os.geteuid()==0
    os.umask(0o077)
    BACKUPS.mkdir(parents=True,exist_ok=True,mode=0o700); BACKUPS.chmod(0o700)
    previous=json.loads(STATUS.read_text()) if STATUS.exists() else {}
    stamp=datetime.now(timezone.utc).isoformat()
    scratch=Path(tempfile.mkdtemp(prefix='finfusion-backup-1.0-',dir='/run'))
    try:
        stage=scratch/'payload'; stage.mkdir(mode=0o700)
        user=pwd.getpwnam('postgres'); os.chown(scratch,user.pw_uid,user.pw_gid); os.chown(stage,user.pw_uid,user.pw_gid)
        call(['runuser','-u','postgres','--',PYTHON,__file__,'--capture',stage])
        os.chown(scratch,0,0); os.chown(stage,0,0)
        for file in stage.iterdir(): os.chown(file,0,0); file.chmod(0o600)
        shutil.copyfile('/run/finfusion/secrets/live/account_master_key',stage/'account_master_key')
        shutil.copyfile('/etc/finfusion/server.env',stage/'server.env.reference-only')
        shutil.copyfile('/var/lib/finfusion/formal-deployment/live/server-secrets.age',stage/'server-secrets.age')
        release=Path('/opt/finfusion/current').resolve()
        (stage/'release.json').write_text(json.dumps({'release':str(release),'schema':'LIVE','version':'1.0.0-rc1'}))
        tarpath=scratch/'snapshot.tar'
        with tarfile.open(tarpath,'w') as tar:
            for file in stage.iterdir(): tar.add(file,arcname=file.name)
        recipient=call(['age-keygen','-y',IDENTITY]).decode().strip()
        name='live-db-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8]
        final=BACKUPS/(name+'.age'); partial=final.with_suffix('.partial')
        call(['age','-r',recipient,'-o',partial,tarpath]); partial.chmod(0o600)
        decrypted=scratch/'verify.tar'; call(['age','-d','-i',IDENTITY,'-o',decrypted,partial])
        if hashlib.sha256(tarpath.read_bytes()).digest()!=hashlib.sha256(decrypted.read_bytes()).digest(): raise ValueError('decrypt verification failed')
        partial.replace(final)
        metadata={'createdAt':stamp,'filename':final.name,'sha256':hashlib.sha256(final.read_bytes()).hexdigest(),
            'encrypted':True,'decryptionVerified':True,'environment':'LIVE','containsBrokerTokens':False}
        (BACKUPS/(name+'.json')).write_text(json.dumps(metadata,indent=2))
        retention(BACKUPS)
        write_status({'status':'PASS','lastAttempt':stamp,'lastSuccess':stamp,'filename':final.name,'sha256':metadata['sha256'],'serverVersion':'1.0.0-rc1'})
        print('Encrypted LIVE backup verified; production unchanged')
    except Exception as exc:
        write_status({'status':'FAIL','lastAttempt':stamp,'lastSuccess':previous.get('lastSuccess'),'errorType':type(exc).__name__})
        print('LIVE backup failed: '+type(exc).__name__); raise SystemExit(1) from None
    finally:
        assert scratch.parent==Path('/run') and scratch.name.startswith('finfusion-backup-1.0-')
        shutil.rmtree(scratch)


if __name__=='__main__':
    if len(sys.argv)>1 and sys.argv[1]=='--capture':
        spec=importlib.util.spec_from_file_location('db_helpers',ROOT/'db_helpers.py')
        helper=importlib.util.module_from_spec(spec); spec.loader.exec_module(helper)
        helper.WORKSPACE=Path('/opt/finfusion/current')
        asyncio.run(helper.capture(Path(sys.argv[2])))
    else: run()
