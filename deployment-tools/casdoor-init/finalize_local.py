"""Finalize the one-time import without reapplying user credentials on restart."""
import os
from pathlib import Path
import subprocess
os.umask(0o077)
assert os.geteuid() == 0
config = Path('/var/lib/finfusion/casdoor/conf/app.conf')
text = config.read_text()
# This pinned Casdoor version always starts RADIUS. Port 0 means an ephemeral
# listener, so use an invalid port to prevent that unused listener entirely.
text = text.replace('radiusServerPort = 0', 'radiusServerPort = -1')
text = text.replace('initDataNewOnly = false', 'initDataNewOnly = true')
text = text.replace('initDataFile = /var/lib/finfusion/casdoor/init_data.json', 'initDataFile =')
config.write_text(text)
config.chmod(0o600)
subprocess.run(['runuser', '-u', 'postgres', '--', 'psql', '-X', '-v', 'ON_ERROR_STOP=1', '-d', 'casdoor', '-c', "DELETE FROM ldap WHERE id IN ('ldap-built-in', 'built-in/ldap-built-in');"], check=True, capture_output=True)
Path('/var/lib/finfusion/casdoor/init_data.json').unlink()
subprocess.run(['systemctl', 'enable', 'casdoor.service'], check=True, capture_output=True)
subprocess.run(['systemctl', 'restart', 'casdoor.service'], check=True)
print('One-time import disabled; bootstrap import removed; demo LDAP entries removed; service enabled and restarted.')
