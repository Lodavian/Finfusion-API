"""One-time, local-only Casdoor bootstrap. Run as root inside Ubuntu.

No credentials are accepted in command arguments or printed. Refuses an
existing Casdoor database; does not alter Finfusion's running API service.
"""
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import pwd
import secrets
import subprocess

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

os.umask(0o077)
assert os.geteuid() == 0
assert hashlib.sha256(Path('/opt/casdoor/casdoor').read_bytes()).hexdigest() == 'cdde5f88b65e9a91803a745748710760757bc0f8834e7d7c971d5fbddb4e3f43'
account = pwd.getpwnam('finfusion')
private = Path('/var/lib/finfusion/casdoor-bootstrap')
runtime = Path('/var/lib/finfusion/casdoor')

def psql(sql):
    result = subprocess.run(['runuser', '-u', 'postgres', '--', 'psql', '-X', '-v', 'ON_ERROR_STOP=1', '-At', '-d', 'postgres'], input=sql, text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError('PostgreSQL operation failed; no credential-bearing SQL is printed')
    return result.stdout.strip()

assert psql("SELECT count(*) FROM pg_database WHERE datname='casdoor';") == '0', 'Existing Casdoor database: refusing one-time initialization'
assert psql("SELECT count(*) FROM pg_roles WHERE rolname='casdoor_service';") == '0'
assert not private.exists(), 'Existing bootstrap state: inspect before retry'
private.mkdir(mode=0o700)
for directory in [runtime, runtime / 'conf', runtime / 'tmp', runtime / 'logs']:
    directory.mkdir(mode=0o700, exist_ok=True)
    os.chown(directory, account.pw_uid, account.pw_gid)
    directory.chmod(0o700)

def write(path, value, service=False):
    path.write_text(value, encoding='utf-8')
    path.chmod(0o600)
    if service:
        os.chown(path, account.pw_uid, account.pw_gid)

db_password = secrets.token_urlsafe(36)
credentials = {
    'url': 'http://127.0.0.1:8000',
    'casdoorAdmin': {'organization': 'built-in', 'username': 'admin', 'password': secrets.token_urlsafe(24)},
    'finfusionAdmin': {'organization': 'finfusion', 'username': 'admin', 'password': secrets.token_urlsafe(24)},
    'application': 'finfusion-admin', 'clientId': secrets.token_urlsafe(18),
    'clientSecret': secrets.token_urlsafe(36),
}
write(private / 'credentials.json', json.dumps(credentials, indent=2))
psql(f"CREATE ROLE casdoor_service LOGIN PASSWORD '{db_password}' NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;\nCREATE DATABASE casdoor OWNER casdoor_service;\nREVOKE CONNECT ON DATABASE casdoor FROM PUBLIC;\nGRANT CONNECT ON DATABASE casdoor TO casdoor_service;\n")
source = f'host=127.0.0.1 port=5432 user=casdoor_service password={db_password} dbname=casdoor sslmode=disable'
write(private / 'casdoor_data_source', source)

def certificate(name):
    key = rsa.generate_private_key(public_exponent=65537, key_size=4096)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)])
    now = dt.datetime.now(dt.timezone.utc)
    cert = x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(key.public_key()).serial_number(x509.random_serial_number()).not_valid_before(now - dt.timedelta(minutes=5)).not_valid_after(now + dt.timedelta(days=365*3)).sign(key, hashes.SHA256())
    return {'owner': 'admin', 'name': name, 'displayName': name, 'scope': 'JWT', 'type': 'x509', 'cryptoAlgorithm': 'RS256', 'bitSize': 4096, 'expireInYears': 3, 'certificate': cert.public_bytes(serialization.Encoding.PEM).decode(), 'privateKey': key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL, serialization.NoEncryption()).decode()}

def organization(name):
    return {'owner': 'admin', 'name': name, 'displayName': 'Finfusion' if name == 'finfusion' else 'Casdoor Administration', 'passwordType': 'bcrypt', 'passwordOptions': ['AtLeast12', 'UpperLower', 'Number'], 'countryCodes': ['CN'], 'languages': ['zh', 'en'], 'tags': [], 'isProfilePublic': False, 'enableTour': False, 'dcrPolicy': 'disabled'}

def application(name, org, cert, client_id, client_secret):
    return {'owner': 'admin', 'name': name, 'displayName': 'Finfusion 管理登录' if org == 'finfusion' else 'Casdoor', 'category': 'Default', 'type': 'All', 'organization': org, 'cert': cert, 'enablePassword': True, 'enableSignUp': False, 'enableGuestSignin': False, 'enableSigninSession': True, 'signinMethods': [{'name': 'Password', 'displayName': 'Password', 'rule': 'All'}], 'providers': [], 'signupItems': [], 'redirectUris': ['http://127.0.0.1:8081/admin/'] if org == 'finfusion' else [], 'grantTypes': ['authorization_code'], 'clientId': client_id, 'clientSecret': client_secret, 'tokenFormat': 'JWT-Custom', 'tokenSigningMethod': 'RS256', 'tokenFields': ['Owner', 'Name', 'DisplayName', 'Roles'], 'expireInHours': 1, 'refreshExpireInHours': 8, 'cookieExpireInHours': 8, 'failedSigninLimit': 5, 'failedSigninFrozenTime': 15, 'formOffset': 2}

data = {
    'organizations': [organization('built-in'), organization('finfusion')],
    'applications': [application('app-built-in', 'built-in', 'cert-built-in', secrets.token_urlsafe(18), secrets.token_urlsafe(36)), application('finfusion-admin', 'finfusion', 'finfusion-signing', credentials['clientId'], credentials['clientSecret'])],
    'users': [{'owner': c['organization'], 'name': c['username'], 'password': c['password'], 'displayName': 'Finfusion Administrator' if c['organization'] == 'finfusion' else 'Casdoor Administrator', 'type': 'normal-user', 'isAdmin': True, 'isForbidden': False, 'signupApplication': 'finfusion-admin' if c['organization'] == 'finfusion' else 'app-built-in', 'registerType': 'Add User', 'registerSource': 'local-bootstrap', 'createdIp': '127.0.0.1', 'language': 'zh'} for c in [credentials['casdoorAdmin'], credentials['finfusionAdmin']]],
    'certs': [certificate('cert-built-in'), certificate('finfusion-signing')],
    'roles': [{'owner': 'finfusion', 'name': 'finfusion-admin', 'displayName': 'Finfusion Administrator', 'users': ['finfusion/admin'], 'groups': [], 'roles': [], 'domains': [], 'isEnabled': True}],
    'ldaps': [{'id': 'ldap-built-in', 'owner': 'built-in', 'serverName': 'Disabled', 'password': secrets.token_urlsafe(36), 'autoSync': 0}],
}
write(runtime / 'init_data.json', json.dumps(data), True)
config = f'''appname = casdoor
httpport = 8000
httpaddr = 127.0.0.1
runmode = prod
copyrequestbody = true
SessionOn = true
driverName = postgres
dataSourceName = {source}
dbName = casdoor
tableNamePrefix =
showSql = false
redisEndpoint =
defaultStorageProvider =
isCloudIntranet = false
authState = casdoor
socks5Proxy =
verificationCodeTimeout = 10
initScore = 0
logPostOnly = true
isUsernameLowered = false
origin = http://127.0.0.1:8000
originFrontend = http://127.0.0.1:8000
staticBaseUrl = http://127.0.0.1:8000
isDemoMode = false
batchSize = 100
showGithubCorner = false
forceLanguage = zh
defaultLanguage = zh
aiAssistantUrl =
defaultApplication = app-built-in
maxItemsForFlatMenu = 7
enableErrorMask = true
enableGzip = true
ldapServerPort = 0
ldapsServerPort = 0
radiusServerPort = -1
quota = {{"organization": -1, "user": -1, "application": -1, "provider": -1}}
logConfig = {{"adapter":"console"}}
initDataNewOnly = false
initDataFile = /var/lib/finfusion/casdoor/init_data.json
frontendBaseDir = /opt/casdoor/web/build
'''
write(runtime / 'conf/app.conf', config, True)
dropin = Path('/etc/systemd/system/casdoor.service.d/20-local-bootstrap.conf')
assert not dropin.exists()
write(private / 'original-unit.txt', subprocess.check_output(['systemctl', 'cat', 'casdoor.service'], text=True))
write(dropin, '''# Local Casdoor-only configuration; replace when full encrypted vault is configured.
[Unit]
Requires=
Requires=postgresql.service
ConditionPathExists=
ConditionPathExists=/var/lib/finfusion/casdoor/conf/app.conf
[Service]
ExecStart=
ExecStart=/opt/casdoor/casdoor -config /var/lib/finfusion/casdoor/conf/app.conf -createDatabase=false
WorkingDirectory=/var/lib/finfusion/casdoor
UMask=0077
''')
subprocess.run(['systemctl', 'daemon-reload'], check=True)
subprocess.run(['systemctl', 'start', 'casdoor.service'], check=True)
print('Casdoor local bootstrap created and service start requested. Credentials retained in root-only storage.')
