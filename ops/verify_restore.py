"""Verify an encrypted 1.0 backup in a new, egress-free database cluster."""
import asyncio
import base64
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
from urllib.parse import quote

ROOT=Path(__file__).resolve().parent
PYTHON='/opt/finfusion/venv/bin/python'
BACKUPS=Path('/var/lib/finfusion/backups/live')
IDENTITY=Path('/var/lib/finfusion/formal-deployment/live/secrets-identity.txt')
REPORT=Path('/var/lib/finfusion/ops/restore-1.0.json')


async def child(stage):
    spec=importlib.util.spec_from_file_location('db_helpers',ROOT/'db_helpers.py')
    h=importlib.util.module_from_spec(spec); spec.loader.exec_module(h); h.WORKSPACE=Path('/opt/finfusion/current')
    subprocess.run(['ip','link','set','lo','up'],check=True)
    assert [x['ifname'] for x in json.loads(subprocess.check_output(['ip','-j','link','show']))]==['lo']
    cluster=h.Cluster(stage.parent/'restore'); cluster.start()
    results=[]
    try:
        baseline=json.loads((stage/'baseline.json').read_text()); identities={}
        for src,target in [('finfusion_live','finfusion_restore_live'),('casdoor','casdoor_restore')]:
            cluster.create(target); c=await cluster.connect(target); await c.close()
            cluster.pg('pg_restore','--no-owner','--no-acl','--exit-on-error','--single-transaction','--dbname='+target,stage/(src+'.dump'))
            actual,identities[src]=await h.restored_inventory(cluster,target)
            assert actual==baseline[src]
            results.append({'database':src,'tables':len(actual['tables']),'passed':True})
        assert h.cross_check(identities)==baseline['identities']
        cluster.stop(); cluster.restart()
        for src,target in [('finfusion_live','finfusion_restore_live'),('casdoor','casdoor_restore')]:
            h.json_write(cluster.directory/'target-marker.json',{'data':str(cluster.directory/'data'),'database':target})
            actual,_=await h.restored_inventory(cluster,target); assert actual==baseline[src]
        sys.path.insert(0,'/opt/finfusion/current')
        from finfusion.postgres import AccountCipher,PostgresStore
        encoded=(stage/'account_master_key').read_text().strip()
        cipher=AccountCipher(base64.urlsafe_b64decode(encoded+'='*(-len(encoded)%4)))
        h.json_write(cluster.directory/'target-marker.json',{'data':str(cluster.directory/'data'),'database':'finfusion_restore_live'})
        c=await cluster.connect('finfusion_restore_live')
        rows=await c.fetch('SELECT broker_account_cipher FROM finfusion.broker_accounts'); assert all(cipher.decrypt(r[0]) for r in rows); await c.close()
        dsn='postgresql://'+cluster.user+':'+cluster.password+'@/finfusion_restore_live?host='+quote(str(cluster.directory/'socket'),safe='')
        store=await PostgresStore.connect(dsn,cipher)
        try: await store.migrate(); await store.bind_environment('LIVE')
        finally: await store.close()
        actual,_=await h.restored_inventory(cluster,'finfusion_restore_live'); assert actual==baseline['finfusion_live']
        REPORT.write_text(json.dumps({'status':'PASS','mode':'LIVE_ISOLATED_RESTORE','networkIsolated':True,'serverVersion':'1.0.0-rc1',
            'databases':results,'restartVerified':True,'migrationPreserved':True,'cipherCount':len(rows),'identityMapping':True,
            'productionWrites':0,'brokerCalls':0},indent=2)); REPORT.chmod(0o600)
    finally: cluster.stop()


def run():
    scratch=Path(tempfile.mkdtemp(prefix='finfusion-live-db-restore-1.0-',dir='/run')); scratch.chmod(0o711)
    try:
        path=sorted(BACKUPS.glob('live-db-*.age'))[-1]
        assert path.parent==BACKUPS and not path.is_symlink()
        archive=scratch/'payload.tar'
        subprocess.run(['age','-d','-i',IDENTITY,'-o',str(archive),str(path)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=True)
        stage=scratch/'payload'; stage.mkdir(mode=0o700)
        allowed={'finfusion_live.dump','casdoor.dump','baseline.json','account_master_key','server.env.reference-only','server-secrets.age','release.json'}
        with tarfile.open(archive) as tar:
            members=tar.getmembers(); assert {x.name for x in members}==allowed and all(x.isfile() and '/' not in x.name for x in members)
            tar.extractall(stage,members=members)
        subprocess.run(['unshare','--net','--',PYTHON,__file__,str(stage)],check=True)
        print('Latest encrypted 1.0 backup restored and verified in isolation')
    finally:
        assert scratch.parent==Path('/run') and scratch.name.startswith('finfusion-live-db-restore-1.0-')
        shutil.rmtree(scratch)


if __name__=='__main__':
    if len(sys.argv)>1: asyncio.run(child(Path(sys.argv[1])))
    else: run()
