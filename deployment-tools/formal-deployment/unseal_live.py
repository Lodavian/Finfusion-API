import grp,json,os,pwd,subprocess
from pathlib import Path
os.umask(0o077)
assert os.geteuid()==0
root=Path('/var/lib/finfusion/formal-deployment/live')
authorization=json.loads((root/'authorization.json').read_text())
assert authorization['environment']=='LIVE' and authorization['ordersAuthorized'] is False
result=subprocess.run(['age','-d','-i',str(root/'secrets-identity.txt'),str(root/'server-secrets.age')],capture_output=True)
assert result.returncode==0
data=json.loads(result.stdout);assert data.pop('environment')=='LIVE'
assert set(data)=={'database_dsn','account_master_key','casdoor_client_secret','webull_app_key','webull_app_secret'}
a=pwd.getpwnam('finfusion');path=Path('/run/finfusion/secrets/live')
path.mkdir(mode=0o700,parents=True,exist_ok=True)
for parent in [Path('/run/finfusion'),Path('/run/finfusion/secrets')]:os.chown(parent,0,a.pw_gid);parent.chmod(0o750)
os.chown(path,a.pw_uid,a.pw_gid);path.chmod(0o700)
for name,value in data.items():
    target=path/name;assert not target.is_symlink()
    target.write_text(value);os.chown(target,a.pw_uid,a.pw_gid);target.chmod(0o600)
tokens=Path('/var/lib/finfusion/webull_tokens/live');tokens.mkdir(mode=0o700,parents=True,exist_ok=True)
os.chown(tokens,a.pw_uid,a.pw_gid);tokens.chmod(0o700)
print('LIVE secrets unsealed to enforced volatile paths; values suppressed.')
