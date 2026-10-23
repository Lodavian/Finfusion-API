"""Real local HTTP/OAuth/JWKS checks. Never print credentials or tokens."""
import base64
import hashlib
import http.cookiejar
import json
import os
from pathlib import Path
import re
import secrets
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

credentials = json.loads(Path('/var/lib/finfusion/casdoor-bootstrap/credentials.json').read_text())
origin = credentials['url']
jar = http.cookiejar.CookieJar()
client = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
deadline = time.monotonic() + 15
while True:
    try:
        with client.open(origin, timeout=2) as response:
            assert response.status == 200
        break
    except urllib.error.URLError:
        if time.monotonic() >= deadline:
            raise RuntimeError('Casdoor did not become ready within 15 seconds') from None
        time.sleep(0.5)

def request(path, body=None):
    payload = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(origin + path, data=payload, headers={'Content-Type': 'application/json', 'Origin': origin})
    try:
        with client.open(req, timeout=15) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return json.loads(exc.read())

for account, app in [('casdoorAdmin', 'app-built-in'), ('finfusionAdmin', 'finfusion-admin')]:
    c = credentials[account]
    body = {'application': app, 'organization': c['organization'], 'username': c['username'], 'password': c['password'], 'type': 'login', 'signinMethod': 'Password'}
    result = request('/api/login', body)
    assert result.get('status') == 'ok', f'{account} login failed: status={result.get("status")}'
    print(f'PASS: {account} actual password login')
    body['password'] = '123'
    result = request('/api/login', body)
    assert result.get('status') != 'ok', 'Default password unexpectedly accepted'
    print(f'PASS: {account} default password rejected')

c = credentials['finfusionAdmin']
verifier = secrets.token_urlsafe(48)
challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
query = urllib.parse.urlencode({'clientId': credentials['clientId'], 'responseType': 'code', 'redirectUri': 'http://127.0.0.1:8081/admin/', 'scope': 'openid', 'state': secrets.token_urlsafe(16), 'code_challenge_method': 'S256', 'code_challenge': challenge})
result = request('/api/login?' + query, {'application': 'finfusion-admin', 'organization': c['organization'], 'username': c['username'], 'password': c['password'], 'type': 'code', 'signinMethod': 'Password'})
assert result.get('status') == 'ok', 'OAuth code login failed'
assert isinstance(result.get('data'), str), 'OAuth code response not a string'
code = result['data']
token_result = request('/api/login/oauth/access_token', {'grant_type': 'authorization_code', 'client_id': credentials['clientId'], 'code': code, 'code_verifier': verifier, 'redirect_uri': 'http://127.0.0.1:8081/admin/'})
assert token_result.get('access_token'), 'OAuth PKCE token exchange failed'
print('PASS: authorization code + S256 PKCE without client secret')
sys.path.insert(0, '/opt/finfusion/current')
from finfusion.security import CasdoorJwtVerifier
validator = CasdoorJwtVerifier(origin + '/.well-known/jwks', origin, credentials['clientId'])
validator.refresh()
claims = validator.verify(token_result['access_token'])
assert claims.get('sub')
assert 'finfusion-admin' in [role.get('name') if isinstance(role, dict) else role for role in claims.get('roles', [])], 'Admin role missing in token'
assert not any(field in claims for field in ['password', 'passwordSalt', 'clientSecret'])
print('PASS: existing Finfusion JWT verifier accepts signature, issuer, audience and admin role')
replay = request('/api/login/oauth/access_token', {'grant_type': 'authorization_code', 'client_id': credentials['clientId'], 'code': code, 'code_verifier': verifier})
assert not replay.get('access_token'), 'OAuth code reuse accepted'
print('PASS: OAuth authorization code reuse rejected')
from finfusion.casdoor import CasdoorAdminClient, CasdoorAdminConfig
admin = CasdoorAdminClient(CasdoorAdminConfig(origin, credentials['clientId'], credentials['clientSecret'], 'finfusion', 'finfusion-admin'))
service_token = admin._client_token()
result = admin._get('/api/get-user', {'id': 'finfusion/admin'}, service_token)
assert result.get('status') == 'ok' and result.get('data', {}).get('id'), 'Backend management authentication failed'
print('PASS: existing Finfusion CasdoorAdminClient obtains service token and reads the managed user')
with client.open(origin, timeout=15) as response:
    html = response.read().decode()
assets = re.findall(r'(?:src|href)="([^"]+\.(?:js|css))"', html)
assert assets
for asset in assets:
    url = urllib.parse.urljoin(origin, asset)
    assert urllib.parse.urlparse(url).netloc == '127.0.0.1:8000'
    with client.open(url, timeout=15) as response:
        assert response.status == 200
print(f'PASS: frontend HTML and {len(assets)} local JS/CSS assets')
print('All local Casdoor checks passed. No credentials or tokens emitted.')
