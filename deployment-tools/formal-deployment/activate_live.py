"""Activate only after a valid Webull token; retain service rollback files."""
import json,os,pwd,shutil,subprocess
from pathlib import Path
os.umask(0o077);assert os.geteuid()==0
root=Path('/var/lib/finfusion/formal-deployment/live')
lines=Path('/var/lib/finfusion/webull_tokens/live/token.txt').read_text().splitlines()
assert len(lines)>=3 and lines[2]=='NORMAL','Token is not verified: refusing activation'
assert not Path('/etc/finfusion/server.env').exists(),'Existing active environment: inspect rather than overwrite'
a=pwd.getpwnam('finfusion')
backups=root/'rollback';backups.mkdir(mode=0o700,exist_ok=True)
for service in ['finfusion.service','finfusion-connectivity.service']:
    (backups/(service+'.txt')).write_text(subprocess.check_output(['systemctl','cat',service],text=True))
(backups/'connectivity-enabled.txt').write_text(subprocess.run(['systemctl','is-enabled','finfusion-connectivity.service'],capture_output=True,text=True).stdout)
script=Path('/opt/finfusion/formal-deployment/live_readonly_server.py')
shutil.copyfile('/home/finfusion_tech/formal-deployment/live_readonly_server.py',script);script.chmod(0o644)
config=Path('/etc/finfusion');config.mkdir(mode=0o750,exist_ok=True)
env=config/'server.env';env.write_text((root/'server.env.pending').read_text());env.chmod(0o640);os.chown(env,0,a.pw_gid)
unit=Path('/etc/systemd/system/finfusion-live-secrets.service')
unit.write_text('''[Unit]
Description=Unseal Finfusion LIVE read-only secrets into volatile storage
Before=finfusion.service
[Service]
Type=oneshot
ExecStart=/opt/finfusion/venv/bin/python -I /opt/finfusion/formal-deployment/unseal_live.py
RemainAfterExit=yes
UMask=0077
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/run/finfusion /var/lib/finfusion/webull_tokens
''');unit.chmod(0o644)
dropin=Path('/etc/systemd/system/finfusion.service.d/20-live-readonly.conf')
assert not dropin.exists()
dropin.write_text('''[Unit]
Requires=
Requires=postgresql.service casdoor.service finfusion-live-secrets.service finfusion-node-default-off.service
After=finfusion-live-secrets.service
[Service]
ExecStart=
ExecStart=/opt/finfusion/venv/bin/python -I -B /opt/finfusion/formal-deployment/live_readonly_server.py
UMask=0077
CapabilityBoundingSet=
RestrictSUIDSGID=true
''');dropin.chmod(0o644)
subprocess.run(['systemctl','daemon-reload'],check=True)
subprocess.run(['systemctl','start','finfusion-live-secrets.service'],check=True)
subprocess.run(['systemctl','start','finfusion.service'],check=True)
print('LIVE read-only service start requested; rollback files preserved; original SDK/business code unchanged.')
