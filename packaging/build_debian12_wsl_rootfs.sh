#!/usr/bin/env bash
set -euo pipefail
umask 077

if [[ "$(id -u)" != 0 ]]; then
  echo "run as root inside a Linux/WSL build environment" >&2
  exit 77
fi

output_dir="${1:?absolute output directory required}"
case "$output_dir" in /*) ;; *) echo "output directory must be absolute" >&2; exit 64 ;; esac

suite="bookworm"
architecture="amd64"
debian_mirror="https://deb.debian.org/debian"
pgdg_key_fingerprint="B97B0AFCAA1A47F044F244A07FCC7D46ACCC4CF8"
work="$(mktemp -d /var/tmp/finfusion-debian12.XXXXXX)"
root="$work/rootfs"
trap 'umount -lf "$root/proc" "$root/sys" "$root/dev/pts" "$root/dev" 2>/dev/null || true; rm -rf -- "$work"' EXIT

apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
  debootstrap debian-archive-keyring ca-certificates curl gnupg tar
debootstrap --arch="$architecture" --variant=minbase "$suite" "$root" "$debian_mirror"

printf '#!/bin/sh\nexit 101\n' > "$root/usr/sbin/policy-rc.d"
chmod 0755 "$root/usr/sbin/policy-rc.d"
cp /etc/resolv.conf "$root/etc/resolv.conf"
mount --bind /dev "$root/dev"
mount --bind /dev/pts "$root/dev/pts"
mount -t proc proc "$root/proc"
mount -t sysfs sys "$root/sys"

chroot "$root" /bin/bash -euo pipefail <<'CHROOT'
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y --no-install-recommends ca-certificates curl gnupg
curl --fail --silent --show-error --location https://www.postgresql.org/media/keys/ACCC4CF8.asc -o /tmp/pgdg.asc
actual="$(gpg --show-keys --with-colons /tmp/pgdg.asc | awk -F: '$1=="fpr" {print $10; exit}')"
test "$actual" = "B97B0AFCAA1A47F044F244A07FCC7D46ACCC4CF8"
gpg --dearmor -o /usr/share/keyrings/postgresql.gpg /tmp/pgdg.asc
chmod 0644 /usr/share/keyrings/postgresql.gpg
echo 'deb [signed-by=/usr/share/keyrings/postgresql.gpg] https://apt.postgresql.org/pub/repos/apt bookworm-pgdg main' > /etc/apt/sources.list.d/pgdg.list
apt-get update -qq
apt-get install -y --no-install-recommends \
  systemd-sysv dbus ca-certificates curl sudo iproute2 age minisign \
  python3 python3-venv postgresql-17 postgresql-client-17
printf '[boot]\nsystemd=true\n' > /etc/wsl.conf
printf 'FinfusionNode\n' > /etc/hostname
: > /etc/machine-id
rm -f /var/lib/dbus/machine-id /tmp/pgdg.asc /usr/sbin/policy-rc.d
apt-get clean
rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*
CHROOT

# Do not archive transient kernel-backed filesystems.  Explicitly detach them
# before querying and packing so tar cannot race changing /proc or /sys files.
umount -lf "$root/proc"
umount -lf "$root/sys"
umount -lf "$root/dev/pts"
umount -lf "$root/dev"

install -d -m 0700 "$output_dir"
manifest="$output_dir/debian-12-base-manifest.json"
rootfs="$output_dir/debian-12-wsl-rootfs.tar.gz"
chroot "$root" dpkg-query -W '-f=${binary:Package}\t${Version}\n' | LC_ALL=C sort > "$work/packages.tsv"
python3 - "$work/packages.tsv" "$manifest" <<'PY'
import json, pathlib, sys
packages = {}
for line in pathlib.Path(sys.argv[1]).read_text(encoding="utf-8").splitlines():
    name, version = line.split("\t", 1)
    packages[name.split(":", 1)[0]] = version
required = {"python3", "python3-venv", "postgresql-17", "postgresql-client-17", "age", "minisign", "curl", "ca-certificates", "sudo", "iproute2"}
missing = sorted(required - packages.keys())
if missing:
    raise SystemExit(f"rootfs is missing required packages: {missing}")
payload = {"schemaVersion": 1, "distribution": "Debian", "suite": "bookworm", "architecture": "amd64", "packages": packages}
pathlib.Path(sys.argv[2]).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
tar --numeric-owner --xattrs --acls --one-file-system -czf "$rootfs" -C "$root" .
sha256sum "$rootfs" "$manifest" > "$output_dir/SHA256SUMS"
echo "Built $rootfs"
cat "$output_dir/SHA256SUMS"
