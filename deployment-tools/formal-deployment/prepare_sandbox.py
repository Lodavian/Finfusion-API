"""Prepare real Sandbox database and approved admin assets without broker placeholders."""
import asyncio
import base64
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys

os.umask(0o077)
assert os.geteuid() == 0
stage = Path('/var/lib/finfusion/formal-deployment')
stage.mkdir(mode=0o700, exist_ok=True)
stage.chmod(0o700)
identity = json.loads(Path('/var/lib/finfusion/casdoor-bootstrap/credentials.json').read_text())
secret_path = stage / 'prepared-secrets.json'
def sql(text):
    r = subprocess.run(['runuser','-u','postgres','--','psql','-X','-At','-v','ON_ERROR_STOP=1','-d','postgres'],input=text,text=True,capture_output=True)
    if r.returncode:
        raise RuntimeError('Database preparation failed; credential-bearing SQL suppressed')
    return r.stdout.strip()
if not secret_path.exists():
    assert sql("SELECT count(*) FROM pg_database WHERE datname='finfusion_sandbox'") == '0', 'Existing database requires inspection'
    assert sql("SELECT count(*) FROM pg_roles WHERE rolname='finfusion_sandbox_service'") == '0'
    password = secrets.token_urlsafe(36)
    prepared = {'environment':'SANDBOX', 'database_dsn':f'postgresql://finfusion_sandbox_service:{password}@127.0.0.1:5432/finfusion_sandbox', 'account_master_key':base64.urlsafe_b64encode(os.urandom(32)).decode(), 'casdoor_client_secret':identity['clientSecret']}
    secret_path.write_text(json.dumps(prepared))
    secret_path.chmod(0o600)
    sql(f"CREATE ROLE finfusion_sandbox_service LOGIN PASSWORD '{password}' NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;\nCREATE DATABASE finfusion_sandbox OWNER finfusion_sandbox_service;\nREVOKE CONNECT ON DATABASE finfusion_sandbox FROM PUBLIC;\nGRANT CONNECT ON DATABASE finfusion_sandbox TO finfusion_sandbox_service;")
else:
    prepared = json.loads(secret_path.read_text())
sys.path.insert(0, '/opt/finfusion/current')
from finfusion.postgres import PostgresStore, AccountCipher
async def migrate():
    store = await PostgresStore.connect(prepared['database_dsn'],AccountCipher(base64.urlsafe_b64decode(prepared['account_master_key'])))
    try:
        await store.migrate()
        await store.bind_environment('SANDBOX')
        controls = await store.load_controls(force_global_off=True)
        assert not controls.global_trade_enabled
        snapshot = await store.admin_snapshot()
        assert not snapshot['accounts'], 'Fresh staging database should not invent broker accounts'
    finally:
        await store.close()
asyncio.run(migrate())
source=Path('/home/finfusion_tech/worktrees/finfusion-admin-ui/server_admin')
destination=Path('/opt/finfusion/admin-ui')
if not destination.exists():
    shutil.copytree(source,destination)
for p in destination.rglob('*'):
    p.chmod(0o755 if p.is_dir() else 0o644)
destination.chmod(0o755)
manifest={str(p.relative_to(destination)):hashlib.sha256(p.read_bytes()).hexdigest() for p in destination.rglob('*') if p.is_file()}
(stage/'admin-ui-manifest.json').write_text(json.dumps(manifest,indent=2))
origin=identity['url']
values={
 'FINFUSION_ENVIRONMENT':'SANDBOX','FINFUSION_LIVE_ALLOWED':'false',
 'FINFUSION_BIND_HOST':'127.0.0.1','FINFUSION_PORT':'8080',
 'FINFUSION_SECRET_DIR':'/run/finfusion/secrets/sandbox',
 'FINFUSION_TOKEN_DIR':'/var/lib/finfusion/webull_tokens/sandbox',
 'FINFUSION_NODE_STATE_FILE':'/run/finfusion/node-state.json',
 'FINFUSION_ADMIN_STATIC_DIR':str(destination),
 'FINFUSION_CASDOOR_URL':origin,'FINFUSION_CASDOOR_ISSUER':origin,
 'FINFUSION_CASDOOR_JWKS_URL':origin+'/.well-known/jwks',
 'FINFUSION_CASDOOR_CLIENT_ID':identity['clientId'],
 'FINFUSION_CASDOOR_ORGANIZATION':'finfusion','FINFUSION_CASDOOR_APPLICATION':'finfusion-admin',
 'FINFUSION_CASDOOR_AUTHORIZATION_ENDPOINT':origin+'/login/oauth/authorize',
 'FINFUSION_CASDOOR_TOKEN_ENDPOINT':origin+'/api/login/oauth/access_token',
 'FINFUSION_ADMIN_REDIRECT_URI':'http://127.0.0.1:8081/admin/',
 'FINFUSION_MAX_ORDER_QTY':'1','FINFUSION_MAX_ORDER_VALUE':'100',
 'FINFUSION_MAX_MARKET_QTY':'1','FINFUSION_MAX_MARKET_ESTIMATED_VALUE':'100',
 'FINFUSION_MAX_DAILY_GROSS_NOTIONAL':'100','FINFUSION_MAX_OPEN_ORDERS':'1',
 'FINFUSION_QUOTE_STALE_SECONDS':'3',
}
(stage/'server.env.pending').write_text(''.join(f'{k}={v}\n' for k,v in values.items()))
print('PASS: real Sandbox PostgreSQL schema prepared; global trading remains off; no broker accounts invented.')
print('PASS: approved admin UI copied to /opt/finfusion/admin-ui with SHA256 manifest.')
print('PASS: Casdoor-connected service configuration staged; it is not installed as active server.env.')
print('Required before activation: valid Sandbox broker credentials and broker initialization.')
