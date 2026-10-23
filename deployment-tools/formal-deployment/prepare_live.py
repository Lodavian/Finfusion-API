"""Separate LIVE storage after explicit authorization for read-only deployment."""
import asyncio,base64,json,os,pwd,grp,secrets,subprocess,sys
from pathlib import Path
os.umask(0o077)
assert os.geteuid()==0
stage=Path('/var/lib/finfusion/formal-deployment')
root=stage/'live';root.mkdir(mode=0o700,exist_ok=True)
encrypted=root/'server-secrets.age';identity=root/'secrets-identity.txt'
def sql(text):
    r=subprocess.run(['runuser','-u','postgres','--','psql','-X','-At','-v','ON_ERROR_STOP=1','-d','postgres'],input=text,text=True,capture_output=True)
    assert r.returncode==0,'Database operation failed; SQL suppressed'
    return r.stdout.strip()
if not encrypted.exists():
    assert sql("SELECT count(*) FROM pg_database WHERE datname='finfusion_live'")=='0','Existing LIVE DB: refusing overwrite'
    assert sql("SELECT count(*) FROM pg_roles WHERE rolname='finfusion_live_service'")=='0'
    previous=subprocess.run(['age','-d','-i',str(stage/'secrets-identity.txt'),str(stage/'server-secrets.age')],capture_output=True)
    assert previous.returncode==0
    prior=json.loads(previous.stdout)
    password=secrets.token_urlsafe(36)
    data={'environment':'LIVE','database_dsn':f'postgresql://finfusion_live_service:{password}@127.0.0.1:5432/finfusion_live','account_master_key':base64.urlsafe_b64encode(os.urandom(32)).decode(),'casdoor_client_secret':prior['casdoor_client_secret'],'webull_app_key':prior['webull_app_key'],'webull_app_secret':prior['webull_app_secret']}
    assert subprocess.run(['age-keygen','-o',str(identity)],capture_output=True).returncode==0
    identity.chmod(0o600)
    recipient=subprocess.check_output(['age-keygen','-y',str(identity)],text=True).strip()
    assert subprocess.run(['age','-r',recipient,'-o',str(encrypted)],input=json.dumps(data).encode(),capture_output=True).returncode==0
    encrypted.chmod(0o600)
    sql(f"CREATE ROLE finfusion_live_service LOGIN PASSWORD '{password}' NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;\nCREATE DATABASE finfusion_live OWNER finfusion_live_service;\nREVOKE CONNECT ON DATABASE finfusion_live FROM PUBLIC;\nGRANT CONNECT ON DATABASE finfusion_live TO finfusion_live_service;")
else:
    result=subprocess.run(['age','-d','-i',str(identity),str(encrypted)],capture_output=True)
    assert result.returncode==0
    data=json.loads(result.stdout)
sys.path.insert(0,'/opt/finfusion/current')
from finfusion.postgres import PostgresStore,AccountCipher
async def migrate():
    store=await PostgresStore.connect(data['database_dsn'],AccountCipher(base64.urlsafe_b64decode(data['account_master_key'])))
    try:
        await store.migrate();await store.bind_environment('LIVE')
        snapshot=await store.load_controls(force_global_off=True)
        assert not snapshot.global_trade_enabled
    finally:await store.close()
asyncio.run(migrate())
env=(stage/'server.env.pending').read_text().replace('=SANDBOX\n','=LIVE\n').replace('FINFUSION_LIVE_ALLOWED=false','FINFUSION_LIVE_ALLOWED=true').replace('/sandbox','/live')
(root/'server.env.pending').write_text(env)
(root/'authorization.json').write_text(json.dumps({'environment':'LIVE','region':'hk','authorized':'management and read-only account queries','ordersAuthorized':False},indent=2))
print('PASS: independent LIVE database and encrypted keys prepared; global trading is off; Sandbox data preserved.')
