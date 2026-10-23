from pathlib import Path
import subprocess
root=Path('/var/lib/finfusion/formal-deployment/live/rollback')
nginx=Path('/etc/nginx/conf.d/finfusion.conf')
if not (root/'nginx-before-oauth.conf').exists(): (root/'nginx-before-oauth.conf').write_bytes(nginx.read_bytes())
s=nginx.read_text()
if 'location = /admin/oauth/token' not in s:
 s=s.replace('    location / {','    location = /admin/oauth/token {\n        limit_except POST OPTIONS { deny all; }\n        proxy_pass http://127.0.0.1:8000/api/login/oauth/access_token;\n        proxy_set_header Host $http_host;\n        proxy_next_upstream off;\n        proxy_cache off;\n        proxy_connect_timeout 5s;\n        proxy_read_timeout 15s;\n    }\n\n    location / {')
 nginx.write_text(s)
env=Path('/etc/finfusion/server.env')
lines=env.read_text().splitlines()
lines=['FINFUSION_CASDOOR_TOKEN_ENDPOINT=http://127.0.0.1:8081/admin/oauth/token' if x.startswith('FINFUSION_CASDOOR_TOKEN_ENDPOINT=') else x for x in lines]
env.write_text('\n'.join(lines)+'\n')
subprocess.run(['nginx','-t'],check=True)
subprocess.run(['systemctl','reload','nginx'],check=True)
subprocess.run(['systemctl','restart','finfusion'],check=True)
print('PASS: same-origin OAuth token exchange deployed; credentials and PKCE flow unchanged.')
