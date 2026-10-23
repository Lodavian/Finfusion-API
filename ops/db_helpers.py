"""Root-only LIVE DB acceptance; production read-only, isolated write targets.

Run after staging this directory and deployed sources in an independent workspace:
  /opt/finfusion/venv/bin/python tools/live_db_acceptance/acceptance.py run
"""
import asyncio
import base64
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import pwd
import secrets
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import urllib.error
import uuid

import asyncpg

PG = Path('/usr/lib/postgresql/17/bin')
PYTHON = '/home/finfusion_tech/worktrees/finfusion-client-market/.venv/bin/python'
CAPTURE_PYTHON = '/opt/finfusion/venv/bin/python'
PRODUCTION = Path('/opt/finfusion/current')
IDENTITY = Path('/var/lib/finfusion/formal-deployment/live/secrets-identity.txt')
ARTIFACT_ROOT = Path('/var/lib/finfusion/acceptance/live-db')
WORKSPACE = Path(__file__).resolve().parents[2]
SCRIPT = Path(__file__).resolve()
sys.path.insert(0, str(WORKSPACE))


def execute(args, *, environment=None, output=None, input_data=None, check=True):
    result = subprocess.run(list(map(str, args)), input=input_data, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, env=environment, cwd=WORKSPACE)
    if output:
        Path(output).write_bytes(result.stdout + result.stderr)
        Path(output).chmod(0o600)
    if check and result.returncode:
        raise RuntimeError('subprocess_failed:' + Path(str(args[0])).name)
    return result


def json_write(path, value):
    Path(path).write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding='utf-8')
    Path(path).chmod(0o600)


def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def quote(identifier): return '"' + identifier.replace('"', '""') + '"'
def digest(rows): return hashlib.sha256('\n'.join(sorted(rows)).encode()).hexdigest()


async def inventory(connection):
    """Only counts and hashes leave memory. Includes all non-system schemas."""
    tables = await connection.fetch("SELECT schemaname,tablename FROM pg_tables WHERE schemaname NOT IN ('pg_catalog','information_schema') ORDER BY 1,2")
    data = {}
    for table in tables:
        name = quote(table['schemaname']) + '.' + quote(table['tablename'])
        rows = await connection.fetch('SELECT to_jsonb(t)::text AS row FROM ' + name + ' t')
        data[table['schemaname'] + '.' + table['tablename']] = {'count': len(rows), 'sha256': digest([r['row'] for r in rows])}
    columns = await connection.fetch("SELECT table_schema,table_name,column_name,ordinal_position,data_type,udt_name,is_nullable,column_default FROM information_schema.columns WHERE table_schema NOT IN ('pg_catalog','information_schema') ORDER BY 1,2,4")
    constraints = await connection.fetch("SELECT n.nspname,c.relname,con.conname,pg_get_constraintdef(con.oid,true) AS definition FROM pg_constraint con JOIN pg_class c ON c.oid=con.conrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname NOT IN ('pg_catalog','information_schema') ORDER BY 1,2,3")
    indexes = await connection.fetch("SELECT schemaname,tablename,indexname,indexdef FROM pg_indexes WHERE schemaname NOT IN ('pg_catalog','information_schema') ORDER BY 1,2,3")
    sequences = {}
    for sequence in await connection.fetch("SELECT schemaname,sequencename FROM pg_sequences WHERE schemaname NOT IN ('pg_catalog','information_schema') ORDER BY 1,2"):
        name = quote(sequence['schemaname']) + '.' + quote(sequence['sequencename'])
        row = await connection.fetchrow('SELECT last_value,is_called FROM ' + name)
        sequences[name] = hashlib.sha256(json.dumps(dict(row), sort_keys=True).encode()).hexdigest()
    schema = [[dict(r) for r in group] for group in [columns, constraints, indexes]]
    return {'tables': data, 'schemaSha256': hashlib.sha256(json.dumps(schema, sort_keys=True).encode()).hexdigest(), 'sequences': sequences}


async def identity_records(connection, database):
    if database == 'finfusion_live':
        return [(str(r['user_id']), r['casdoor_name']) for r in await connection.fetch('SELECT user_id,casdoor_name FROM finfusion.app_users')]
    # Casdoor's xorm user table is named user in public schema.
    return [(str(r['id']), str(r['name'])) for r in await connection.fetch('SELECT id,name FROM public."user"')]


def cross_check(identities):
    casdoor_ids = {r[0] for r in identities['casdoor']}
    casdoor_names = {r[1] for r in identities['casdoor']}
    users = identities['finfusion_live']
    matched = sum(uid in casdoor_ids and name in casdoor_names for uid, name in users)
    return {'users': len(users), 'matched': matched, 'allMatched': matched == len(users),
            'mappingSha256': digest([json.dumps(row) for row in users])}


async def capture(stage):
    baseline = {}
    identities = {}
    for database in ['finfusion_live', 'casdoor']:
        connection = await asyncpg.connect(database=database, user='postgres', host='/var/run/postgresql')
        try:
            async with connection.transaction(isolation='repeatable_read', readonly=True):
                assert await connection.fetchval('SHOW transaction_read_only') == 'on'
                snapshot = await connection.fetchval('SELECT pg_export_snapshot()')
                baseline[database] = await inventory(connection)
                identities[database] = await identity_records(connection, database)
                if database == 'finfusion_live':
                    assert await connection.fetchval('SELECT environment FROM finfusion.deployment_environment') == 'LIVE'
                    baseline['controls'] = await production_controls(connection)
                execute([PG/'pg_dump', '--format=custom', '--no-owner', '--no-acl', '--snapshot='+snapshot,
                         '--file='+str(stage/(database+'.dump')), database])
                assert (await inventory(connection))['sequences'] == baseline[database]['sequences'], 'sequence changed during dump; recapture'
        finally: await connection.close()
    baseline['identities'] = cross_check(identities)
    assert baseline['identities']['allMatched'], 'Casdoor identity mapping mismatch'
    json_write(stage/'baseline.json', baseline)


async def production_controls(connection):
    rows = []
    for query in [
        'SELECT singleton,global_trade_enabled,version FROM finfusion.control_state',
        'SELECT user_id,enabled,trade_enabled FROM finfusion.app_users',
        'SELECT account_ref,enabled,trade_enabled FROM finfusion.broker_accounts',
        'SELECT client_id,enabled,can_read,can_trade,can_cancel,public_key_pem FROM finfusion.clients']:
        rows.extend([json.dumps(dict(r), default=str, sort_keys=True) for r in await connection.fetch(query)])
    return digest(rows)


def health():
    services = {}
    for service in ['finfusion', 'casdoor', 'nginx', 'finfusion-api-tunnel']:
        result = execute(['systemctl','show',service,'--property=ActiveState,MainPID,NRestarts'], check=True)
        services[service] = result.stdout.decode().strip().splitlines()
    states = {}
    for endpoint in ['livez','readyz']:
        try: response = urllib.request.urlopen('http://127.0.0.1:8081/'+endpoint, timeout=5)
        except urllib.error.HTTPError as error: response = error
        payload = json.loads(response.read())
        states[endpoint] = {k: v for k,v in payload.items() if type(v) is bool}
    assert states['livez'].get('ok') is True
    assert states['readyz'].get('database') is True
    assert states['readyz'].get('effectiveTradeEnabled') is False
    assert all('ActiveState=active' in s for s in services.values())
    return {'release': str(PRODUCTION.resolve()), 'services': services, 'health': states,
            'nodeStateSha256': sha('/run/finfusion/node-state.json')}


def validate_target(directory, database):
    directory = Path(directory).resolve()
    assert directory.parent.parent == Path('/run') and directory.parent.name.startswith('finfusion-live-db-'), 'target outside acceptance scratch'
    assert directory.name in {'integration','restore'}, 'unexpected cluster'
    assert database.startswith('finfusion_test_live_') or database in {'finfusion_restore_live','casdoor_restore'}, 'production DB name rejected'
    assert directory.exists() and (directory/'target-marker.json').exists(), 'missing target marker'
    marker = json.loads((directory/'target-marker.json').read_text())
    assert marker['data'] == str(directory/'data') and marker['database'] == database, 'target marker mismatch'


class Cluster:
    def __init__(self, directory):
        self.directory = directory
        self.password = secrets.token_hex(32)
        self.started = False
        self.user = 'acceptance_' + uuid.uuid4().hex[:12]
        self.environment = {**os.environ, 'PGPASSWORD': self.password, 'PGHOST': str(directory/'socket'), 'PGUSER': self.user}

    def pg(self, binary, *args, check=True, output=None):
        return execute([PG/binary, *args], environment=self.environment, check=check, output=output)

    def start(self):
        account = pwd.getpwnam('postgres')
        for path in [self.directory, self.directory/'socket']:
            path.mkdir(mode=0o700, exist_ok=True)
            os.chown(path, account.pw_uid, account.pw_gid)
        password = self.directory/'password'
        password.write_text(self.password); password.chmod(0o600)
        os.chown(password, account.pw_uid, account.pw_gid)
        execute(['runuser','-u','postgres','--',PG/'initdb','-D',self.directory/'data','-U',self.user,
            '-A','scram-sha-256','--pwfile',password,'--encoding=UTF8','--locale=C'], output=self.directory/'init.log')
        password.unlink()
        self.restart()

    def restart(self):
        execute(['runuser','-u','postgres','--',PG/'pg_ctl','-D',self.directory/'data', '-l',self.directory/'postgres.log',
                 '-o',"-c listen_addresses='' -k " + str(self.directory/'socket'),'-w','start'])
        self.started = True

    def stop(self):
        if self.started:
            execute(['runuser','-u','postgres','--',PG/'pg_ctl','-D',self.directory/'data','-m','fast','-w','stop'])
            self.started = False

    def create(self, database):
        self.pg('createdb',database)
        json_write(self.directory/'target-marker.json', {'data': str(self.directory/'data'), 'database': database})

    async def connect(self, database):
        validate_target(self.directory, database)
        c = await asyncpg.connect(database=database,user=self.user,password=self.password,host=str(self.directory/'socket'))
        assert await c.fetchval('SHOW data_directory') == str(self.directory/'data')
        assert await c.fetchval('SELECT current_database()') == database
        return c


async def restored_inventory(cluster, database):
    c = await cluster.connect(database)
    try:
        async with c.transaction(isolation='repeatable_read',readonly=True):
            return await inventory(c), await identity_records(c, 'finfusion_live' if database == 'finfusion_restore_live' else 'casdoor')
    finally: await c.close()


async def isolated(run, stage):
    # A new network namespace has no interface other than its own loopback.
    execute(['ip','link','set','lo','up'])
    interfaces = [x['ifname'] for x in json.loads(execute(['ip','-j','link','show']).stdout)]
    assert interfaces == ['lo'], 'unexpected network interfaces'
    assert os.readlink('/proc/self/ns/net') != os.readlink('/proc/1/ns/net')
    report = {'mode':'LIVE','networkIsolation':True,'realBrokerCalls':0,'checks':[]}
    a, b = Cluster(stage.parent/'integration'), Cluster(stage.parent/'restore')
    try:
        a.start()
        database = 'finfusion_test_live_' + uuid.uuid4().hex
        a.create(database)
        c = await a.connect(database); await c.close()
        from urllib.parse import quote as urlquote
        dsn = 'postgresql://'+a.user+':'+a.password+'@/'+database+'?host='+urlquote(str(a.directory/'socket'),safe='')
        env = {**os.environ,'FINFUSION_TEST_DSN':dsn,'FINFUSION_LIVE_TEST_DSN':dsn,'FINFUSION_ENVIRONMENT':'LIVE','FINFUSION_LIVE_ALLOWED':'true'}
        env.pop('PYTHONPATH',None)
        tests = execute([PYTHON,'-m','pytest','-q','--basetemp',run/'pytest-temp','--junitxml',run/'tests.xml'], environment=env,
                        output=run/'pytest-private.log', check=False)
        report['checks'].append({'check':'live_postgres_suite','passed':tests.returncode == 0})
        json_write(run/'result.json',report)
        assert tests.returncode == 0, 'pytest failed; inspect private log'
        b.start()
        baseline = json.loads((stage/'baseline.json').read_text())
        identities = {}
        for source, target in [('finfusion_live','finfusion_restore_live'),('casdoor','casdoor_restore')]:
            b.create(target)
            c = await b.connect(target); await c.close()
            validate_target(b.directory,target)
            b.pg('pg_restore','--no-owner','--no-acl','--exit-on-error','--single-transaction','--dbname='+target,stage/(source+'.dump'))
            actual, identities[source] = await restored_inventory(b,target)
            assert actual == baseline[source], 'restored data/schema/sequence mismatch'
            report['checks'].append({'check':source+'_restore_exact','passed':True,'tables':len(actual['tables']),
                                    'rows':sum(x['count'] for x in actual['tables'].values())})
        assert cross_check(identities) == baseline['identities']
        report['checks'].append({'check':'casdoor_identity_mapping','passed':True,'users':baseline['identities']['users']})
        b.stop(); b.restart()
        for source,target in [('finfusion_live','finfusion_restore_live'),('casdoor','casdoor_restore')]:
            json_write(b.directory/'target-marker.json',{'data':str(b.directory/'data'),'database':target})
            actual,_ = await restored_inventory(b,target)
            assert actual == baseline[source]
        report['checks'].append({'check':'cluster_restart_persistence','passed':True})
        json_write(b.directory/'target-marker.json',{'data':str(b.directory/'data'),'database':'finfusion_restore_live'})
        from finfusion.postgres import PostgresStore, AccountCipher
        key_text = (stage/'account_master_key').read_text().strip()
        cipher = AccountCipher(base64.urlsafe_b64decode(key_text+'='*(-len(key_text)%4)))
        c = await b.connect('finfusion_restore_live')
        rows = await c.fetch('SELECT broker_account_cipher FROM finfusion.broker_accounts')
        assert all(cipher.decrypt(r['broker_account_cipher']) for r in rows)
        await c.close()
        report['checks'].append({'check':'account_cipher_decrypt','passed':True,'count':len(rows)})
        # Migrations are checked only in the restored isolated cluster.
        restore_dsn = 'postgresql://'+b.user+':'+b.password+'@/finfusion_restore_live?host='+urlquote(str(b.directory/'socket'),safe='')
        store = await PostgresStore.connect(restore_dsn,cipher)
        try:
            await store.migrate(); await store.bind_environment('LIVE')
        finally: await store.close()
        actual,_ = await restored_inventory(b,'finfusion_restore_live')
        assert actual == baseline['finfusion_live'], 'migration changed restored records'
        report['checks'].append({'check':'restored_migration_preserves_snapshot','passed':True})
        for path,name in [(Path('/var/lib/postgresql/17/main'),'finfusion_live'), (b.directory,'finfusion_live')]:
            try: validate_target(path,name)
            except AssertionError: pass
            else: raise AssertionError('production target not blocked')
        report['checks'].append({'check':'production_target_rejected','passed':True})
    finally:
        a.stop(); b.stop()
        report['clustersStopped'] = not a.started and not b.started
        json_write(run/'result.json',report)


def orchestrate():
    assert os.geteuid() == 0
    os.umask(0o077)
    assert PRODUCTION.resolve() == Path('/opt/finfusion/releases/f581d3b-market-20261009-2')
    run = ARTIFACT_ROOT/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8])
    run.mkdir(parents=True,mode=0o710)
    os.chown(run,0,pwd.getpwnam('postgres').pw_gid); run.chmod(0o710)
    before = health(); json_write(run/'health-before.json',before)
    manifest = json.loads(Path('/var/lib/finfusion/formal-deployment/live/market-release-manifest.json').read_text())
    deployed = {}
    for relative,expected in manifest['overlay'].items():
        path = PRODUCTION/relative
        if not path.exists(): path = WORKSPACE/relative
        assert path.exists() and sha(path) == expected, 'release/contract hash mismatch'
        deployed[relative] = expected
    source_hashes = {}
    for package in ['finfusion','finfusion_common']:
        for path in (PRODUCTION/package).rglob('*.py'):
            relative = str(path.relative_to(PRODUCTION))
            assert sha(path) == sha(WORKSPACE/relative), 'deployed source differs from acceptance source'
            source_hashes[relative] = sha(path)
    json_write(run/'release-check.json',{'release':str(PRODUCTION.resolve()),'verified':deployed,
               'baseline':manifest['baseline'],'acceptanceSourceSha256':sha(SCRIPT),'sourceFiles':source_hashes})
    scratch = Path(tempfile.mkdtemp(prefix='finfusion-live-db-',dir='/run'))
    stage = scratch/'payload'; stage.mkdir(mode=0o700)
    account = pwd.getpwnam('postgres')
    os.chown(scratch,account.pw_uid,account.pw_gid); os.chown(stage,account.pw_uid,account.pw_gid)
    try:
        execute(['runuser','-u','postgres','--',CAPTURE_PYTHON,SCRIPT,'capture',stage], output=run/'capture-private.log')
        os.chown(scratch,0,0); scratch.chmod(0o711); os.chown(stage,0,0)
        for path in stage.iterdir(): os.chown(path,0,0); path.chmod(0o600)
        shutil.copyfile('/run/finfusion/secrets/live/account_master_key',stage/'account_master_key')
        shutil.copyfile('/etc/finfusion/server.env',stage/'server.env.reference-only')
        json_write(stage/'release.json',{'path':str(PRODUCTION.resolve()),'files':deployed})
        archive = scratch/'payload.tar'
        with tarfile.open(archive,'w') as tar:
            for path in stage.iterdir(): tar.add(path,arcname=path.name)
        recipient = execute(['age-keygen','-y',IDENTITY]).stdout.decode().strip()
        encrypted = run/'live-db-backup.age'
        execute(['age','-r',recipient,'-o',encrypted,archive])
        encrypted.chmod(0o600)
        json_write(run/'backup-manifest.json',{'encryptedSha256':sha(encrypted),'environment':'LIVE',
                   'databases':['finfusion_live','casdoor'],'includesBrokerTokens':False,'keyMaterialEncrypted':True,
                   'decryptionIdentityPath':str(IDENTITY),'recipientSha256':hashlib.sha256(recipient.encode()).hexdigest()})
        # Recover exclusively from the encrypted artifact, not original clear dumps.
        shutil.rmtree(stage); stage.mkdir(mode=0o700)
        decrypted = scratch/'recovered.tar'
        execute(['age','-d','-i',IDENTITY,'-o',decrypted,encrypted])
        with tarfile.open(decrypted) as tar:
            members=tar.getmembers()
            allowed={'finfusion_live.dump','casdoor.dump','baseline.json','account_master_key','server.env.reference-only','release.json'}
            assert {m.name for m in members} == allowed
            assert all(m.isfile() and '/' not in m.name and m.size < 1024**3 for m in members)
            tar.extractall(stage,members=members)
        # Negative authenticated-decryption tests; no restore follows failure.
        wrongkey = scratch/'wrong-identity'
        execute(['age-keygen','-o',wrongkey])
        bad=execute(['age','-d','-i',wrongkey,encrypted],check=False)
        assert bad.returncode != 0
        corrupted=scratch/'corrupted.age'; content=bytearray(encrypted.read_bytes()); content[-1]^=1; corrupted.write_bytes(content)
        bad=execute(['age','-d','-i',IDENTITY,corrupted],check=False)
        assert bad.returncode != 0
        json_write(run/'negative-backup-tests.json',{'wrongKeyRejected':True,'corruptionRejected':True})
        execute(['unshare','--net','--',PYTHON,SCRIPT,'isolated',run,stage],output=run/'isolated-private.log')
        # Re-read only gate configuration; audit rows may legitimately change.
        # postgres cannot read secret-bearing payload, only this separate output dir.
        control_output = scratch/'control-output'; control_output.mkdir(mode=0o700)
        os.chown(control_output,account.pw_uid,account.pw_gid)
        execute(['runuser','-u','postgres','--',CAPTURE_PYTHON,SCRIPT,'controls',control_output/'controls-after.json'])
        baseline=json.loads((stage/'baseline.json').read_text())
        assert json.loads((control_output/'controls-after.json').read_text())['sha256'] == baseline['controls'], 'production permissions changed'
        after=health(); json_write(run/'health-after.json',after)
        assert before == after, 'production health/process/gates changed'
        result=json.loads((run/'result.json').read_text()); result.update(productionUnchanged=True,
            encryptedRecovery=True,negativeBackupTests=True,status='PASS')
        json_write(run/'result.json',result)
        print('PASS',run,flush=True)
    except Exception as error:
        json_write(run/'failure.json',{'type':type(error).__name__,'status':'FAIL',
                   'stage':str(error) if isinstance(error,RuntimeError) and str(error).startswith('subprocess_failed:') else 'validation'})
        print('FAIL',run,type(error).__name__,flush=True)
        raise SystemExit(1) from None
    finally:
        try: json_write(run/'health-final.json',health())
        except Exception: json_write(run/'health-final.json',{'status':'FAILED_HEALTH_CHECK'})
        assert scratch.parent == Path('/run') and scratch.name.startswith('finfusion-live-db-')
        shutil.rmtree(scratch)


async def controls(path):
    c=await asyncpg.connect(database='finfusion_live',user='postgres',host='/var/run/postgresql')
    try:
        async with c.transaction(readonly=True): json_write(path,{'sha256':await production_controls(c)})
    finally: await c.close()


if __name__ == '__main__':
    if sys.argv[1]=='run': orchestrate()
    elif sys.argv[1]=='capture': asyncio.run(capture(Path(sys.argv[2])))
    elif sys.argv[1]=='isolated': asyncio.run(isolated(Path(sys.argv[2]),Path(sys.argv[3])))
    elif sys.argv[1]=='controls': asyncio.run(controls(Path(sys.argv[2])))
    else: raise SystemExit('unsupported mode')
