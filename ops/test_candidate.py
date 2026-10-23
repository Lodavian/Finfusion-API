"""LIVE candidate tests in a disposable, egress-free real PostgreSQL cluster."""
import asyncio
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import shutil
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
PYTHON = sys.executable
HELPER = str(ROOT / 'tools/live_db_acceptance/acceptance.py')


async def child(scratch):
    spec=importlib.util.spec_from_file_location('db_acceptance',HELPER)
    helper=importlib.util.module_from_spec(spec); spec.loader.exec_module(helper)
    subprocess.run(['ip','link','set','lo','up'],check=True)
    links=json.loads(subprocess.check_output(['ip','-j','link','show']))
    assert [x['ifname'] for x in links]==['lo']
    helper.WORKSPACE=ROOT
    cluster=helper.Cluster(scratch/'integration')
    try:
        cluster.start(); database='finfusion_test_live_candidate'
        cluster.create(database)
        c=await cluster.connect(database); await c.close()
        dsn='postgresql://'+cluster.user+':'+cluster.password+'@/'+database+'?host='+quote(str(cluster.directory/'socket'),safe='')
        env={**os.environ,'FINFUSION_TEST_DSN':dsn,'FINFUSION_LIVE_TEST_DSN':dsn,'FINFUSION_ENVIRONMENT':'LIVE','FINFUSION_LIVE_ALLOWED':'true'}
        env.pop('PYTHONPATH',None)
        (ROOT/'build').mkdir(exist_ok=True)
        output=ROOT/'build/server-1.0-pg.log'
        with output.open('wb') as log:
            result=subprocess.run([PYTHON,'-m','pytest','-q','--junitxml',ROOT/'build/server-1.0-pg.xml'],cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT)
        output.chmod(0o600)
        assert result.returncode==0, 'Candidate tests failed; see private log'
    finally: cluster.stop()


def main():
    if len(sys.argv)>1:
        asyncio.run(child(Path(sys.argv[1]))); return
    scratch=Path(tempfile.mkdtemp(prefix='finfusion-live-db-candidate-',dir='/run')); scratch.chmod(0o711)
    try:
        r=subprocess.run(['unshare','--net','--',PYTHON,__file__,str(scratch)],cwd=ROOT)
        if r.returncode: raise SystemExit(r.returncode)
        print('Candidate LIVE PostgreSQL tests PASS; real broker calls 0')
    finally:
        assert scratch.parent==Path('/run') and scratch.name.startswith('finfusion-live-db-candidate-')
        shutil.rmtree(scratch)


if __name__=='__main__': main()
