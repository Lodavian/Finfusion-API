"""Read broker credentials on stdin, combine with prepared keys, seal with age."""
import json
import os
from pathlib import Path
import subprocess
import sys
os.umask(0o077)
assert os.geteuid()==0
root=Path('/var/lib/finfusion/formal-deployment')
incoming=json.load(sys.stdin)
assert incoming.get('environment')=='SANDBOX'
assert set(incoming)=={'environment','appKey','appSecret'}
assert all(isinstance(incoming[k],str) and len(incoming[k])>=8 and not any(c in incoming[k] for c in '\r\n\x00') for k in ['appKey','appSecret'])
identity=root/'secrets-identity.txt'
if not identity.exists():
    result=subprocess.run(['age-keygen','-o',str(identity)],capture_output=True)
    assert result.returncode==0,'age identity generation failed'
    identity.chmod(0o600)
recipient=subprocess.check_output(['age-keygen','-y',str(identity)],text=True).strip()
encrypted=root/'server-secrets.age'
if encrypted.exists():
    result=subprocess.run(['age','-d','-i',str(identity),str(encrypted)],capture_output=True)
    assert result.returncode==0,'existing secret decryption failed'
    data=json.loads(result.stdout)
else:
    data=json.loads((root/'prepared-secrets.json').read_text())
data.update(webull_app_key=incoming['appKey'],webull_app_secret=incoming['appSecret'])
assert set(data)=={'environment','database_dsn','account_master_key','casdoor_client_secret','webull_app_key','webull_app_secret'}
temporary=encrypted.with_suffix('.age.new')
result=subprocess.run(['age','-r',recipient,'-o',str(temporary)],input=json.dumps(data).encode(),capture_output=True)
assert result.returncode==0,'secret encryption failed'
temporary.chmod(0o600)
temporary.replace(encrypted)
result=subprocess.run(['age','-d','-i',str(identity),str(encrypted)],capture_output=True)
assert result.returncode==0 and json.loads(result.stdout)==data
(root/'prepared-secrets.json').unlink(missing_ok=True)
print('PASS: Sandbox server secrets imported through stdin and sealed; no values emitted.')
