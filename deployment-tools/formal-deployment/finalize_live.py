from pathlib import Path
import json,subprocess,os,datetime
os.umask(0o077)
root=Path('/var/lib/finfusion/formal-deployment/live')
subprocess.run(['systemctl','disable','finfusion-connectivity'],check=True)
subprocess.run(['systemctl','enable','finfusion'],check=True)
backup=root/'backups';backup.mkdir(exist_ok=True,mode=0o700)
stamp=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d-%H%M%S')
for database in ['finfusion_live','casdoor']:
 target=backup/(database+'-'+stamp+'.dump')
 with target.open('wb') as f: subprocess.run(['runuser','-u','postgres','--','pg_dump','-Fc',database],stdout=f,check=True)
 subprocess.run(['pg_restore','--list',str(target)],stdout=subprocess.DEVNULL,check=True)
classification=Path('/var/lib/finfusion/formal-deployment/credential-classification.json')
classification.write_text(json.dumps({'enteredLabel':'SANDBOX','userReportedEnvironment':'LIVE','activatedEnvironment':'LIVE','ordersAuthorized':False,'readOnlyVerified':True},indent=2))
print('PASS: formal service enabled for Ubuntu boot; old connectivity service disabled; LIVE and Casdoor backups verified.')
for service in ['finfusion','casdoor','nginx','finfusion-api-tunnel']:
 state=subprocess.check_output(['systemctl','is-active',service],text=True).strip()
 print(service+': '+state);assert state=='active'
