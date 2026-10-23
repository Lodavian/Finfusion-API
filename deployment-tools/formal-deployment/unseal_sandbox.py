"""Decrypt only real Sandbox API secrets into the enforced volatile paths."""
import grp,json,os,pwd,subprocess
from pathlib import Path
os.umask(0o077)
assert os.geteuid()==0
root=Path('/var/lib/finfusion/formal-deployment')
classification=root/'credential-classification.json'
if classification.exists():
    assert json.loads(classification.read_text()).get('userReportedEnvironment')=='SANDBOX', 'Credential environment mismatch: refusing Sandbox runtime injection'
result=subprocess.run(['age','-d','-i',str(root/'secrets-identity.txt'),str(root/'server-secrets.age')],capture_output=True)
assert result.returncode==0,'Secret decryption failed'
data=json.loads(result.stdout)
assert data.pop('environment')=='SANDBOX'
assert set(data)=={'database_dsn','account_master_key','casdoor_client_secret','webull_app_key','webull_app_secret'}
a=pwd.getpwnam('finfusion')
path=Path('/run/finfusion/secrets/sandbox')
path.mkdir(parents=True,mode=0o700,exist_ok=True)
for parent in [Path('/run/finfusion'),Path('/run/finfusion/secrets')]:
    os.chown(parent,0,grp.getgrnam('finfusion').gr_gid);parent.chmod(0o750)
os.chown(path,a.pw_uid,a.pw_gid);path.chmod(0o700)
for name,value in data.items():
    target=path/name
    assert not target.is_symlink()
    target.write_text(value)
    os.chown(target,a.pw_uid,a.pw_gid);target.chmod(0o600)
tokens=Path('/var/lib/finfusion/webull_tokens/sandbox')
tokens.mkdir(mode=0o700,parents=True,exist_ok=True)
os.chown(tokens,a.pw_uid,a.pw_gid);tokens.chmod(0o700)
print('PASS: encrypted Sandbox secrets unsealed to user-owned 0700/0600 runtime paths.')
