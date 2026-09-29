#!/bin/bash
set -euo pipefail
if [[ "$(id -u)" != 0 ]]; then echo "install.sh must run as root" >&2; exit 77; fi
root="$(cd "$(dirname "$0")" && pwd)"
version="$(cat "$root/VERSION")"
release="/opt/finfusion/releases/$version"

python3 - "$root/debian-base-manifest.json" <<'PY'
import json, subprocess, sys
manifest = json.load(open(sys.argv[1], encoding="utf-8"))
required = {"python3", "python3-venv", "postgresql-17", "postgresql-client-17", "age", "minisign", "curl", "ca-certificates", "sudo", "iproute2"}
packages = manifest.get("packages", {})
if not isinstance(packages, dict) or not required.issubset(packages):
    raise SystemExit("Debian base manifest is missing required packages")
for package, expected in packages.items():
    actual = subprocess.check_output(["dpkg-query", "-W", "-f=${Version}", package], text=True).strip()
    if actual != expected:
        raise SystemExit(f"base package mismatch: {package}: expected {expected}, got {actual}")
PY
id finfusion >/dev/null 2>&1 || useradd --system --home /var/lib/finfusion --shell /usr/sbin/nologin finfusion
install -d -m 0755 /opt/finfusion/releases /opt/finfusion/venvs "$release" /opt/finfusion/bin /opt/casdoor /opt/casdoor/conf /opt/casdoor/conf.upstream
install -d -m 0700 -o root -g root /var/lib/finfusion/vault
install -d -m 0700 -o finfusion -g finfusion /var/lib/finfusion/webull_tokens
install -d -m 0750 -o finfusion -g finfusion /var/lib/finfusion/casdoor /etc/finfusion
install -d -m 0700 -o finfusion -g finfusion /var/lib/finfusion/casdoor/conf
cp -a "$root/app/finfusion_common" "$root/app/finfusion" "$root/app/server_admin" "$release/"
python3 -m venv "/opt/finfusion/venvs/$version"
"/opt/finfusion/venvs/$version/bin/pip" install --no-index --require-hashes --find-links "$root/wheelhouse" -r "$root/python-requirements.lock"
install -m 0755 "$root/bin/"* /opt/finfusion/bin/
install -m 0755 "$root/vendor/cloudflared" /usr/local/bin/cloudflared
install -m 0755 "$root/vendor/casdoor-release/casdoor" /opt/casdoor/casdoor
rm -rf -- /opt/casdoor/web
cp -R "$root/vendor/casdoor-release/web" /opt/casdoor/web
chown -R root:root /opt/casdoor/web
find /opt/casdoor/web -type d -exec chmod 0755 {} +
find /opt/casdoor/web -type f -exec chmod 0644 {} +
install -m 0444 "$root/vendor/casdoor-release/conf/app.conf" /opt/casdoor/conf.upstream/app.conf
ln -sfn "$release" /opt/finfusion/current
ln -sfn "/opt/finfusion/venvs/$version" /opt/finfusion/venv
cp "$root/systemd/"*.service "$root/systemd/"*.timer /etc/systemd/system/
install -m 0644 "$root/debian-base-manifest.json" /opt/finfusion/debian-base-manifest.json
install -m 0644 "$root/VERSION" /opt/finfusion/VERSION
install -m 0644 "$root/casdoor-release-manifest.json" /opt/casdoor/release-manifest.json
printf '[boot]\nsystemd=true\n' > /etc/wsl.conf
systemctl daemon-reload
systemctl enable postgresql finfusion-node-default-off finfusion-vault finfusion casdoor cloudflared finfusion-tunnel-health.timer
/opt/finfusion/bin/vault.py init
/opt/finfusion/bin/node_state.py deactivate --reason install
echo "Linux payload installed. Configure secrets before starting services."
