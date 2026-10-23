"""Prepare the actual Windows client's DPAPI key, preserving existing credentials."""
import json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2] / 'windows-client'))
from finfusion_client.security import data_directory,restrict_directory,KeyStore
from finfusion_client.storage import Journal
directory=data_directory();restrict_directory(directory)
journal=Journal(directory/'requests.sqlite3')
assert not journal.pending(), 'Existing unresolved requests: do not change client configuration'
keys=KeyStore(directory)
if not keys.path.exists():keys.generate()
public=keys.public_pem().decode('ascii')
target=directory.parent/'Admin'/'live-client-registration.json'
target.write_text(json.dumps({'label':'Windows 只读工作站','publicKeyPem':public,'keyLocation':'Windows DPAPI only'},ensure_ascii=False),encoding='utf-8')
print('PASS: actual Windows client P-256 key prepared; existing key preserved; no unresolved requests.')
print('Only the public key is exported; private key remains Windows DPAPI protected.')
