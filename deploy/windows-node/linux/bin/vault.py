#!/usr/bin/env python3
"""Minimal age-backed Finfusion vault. Plaintext exists only below /run."""

from __future__ import annotations

import argparse
import json
import os
import grp
import pwd
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path


VAULT_DIR = Path("/var/lib/finfusion/vault")
IDENTITY = VAULT_DIR / "identity.txt"
RECIPIENT = VAULT_DIR / "recipient.txt"
ENCRYPTED = VAULT_DIR / "secrets.age"
RUNTIME = Path("/run/finfusion/secrets")
ALLOWED = {
    "environment",
    "webull_app_key", "webull_app_secret", "database_dsn",
    "account_master_key", "casdoor_client_secret", "casdoor_data_source", "tunnel_token",
}


def require_root() -> None:
    if os.geteuid() != 0:
        raise SystemExit("vault.py must run as root")


def private_regular(path: Path, mode: int = 0o600) -> None:
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise RuntimeError(f"unsafe file type: {path}")
    if info.st_uid != 0 or stat.S_IMODE(info.st_mode) != mode:
        raise RuntimeError(f"unsafe ownership/mode: {path}")


def init() -> None:
    VAULT_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(VAULT_DIR, 0o700)
    if IDENTITY.exists():
        private_regular(IDENTITY)
        return
    subprocess.run(["age-keygen", "-o", str(IDENTITY)], check=True)
    os.chmod(IDENTITY, 0o600)
    result = subprocess.run(["age-keygen", "-y", str(IDENTITY)], check=True, text=True, capture_output=True)
    RECIPIENT.write_text(result.stdout.strip() + "\n", encoding="ascii")
    os.chmod(RECIPIENT, 0o644)


def seal(source: Path) -> None:
    init()
    private_regular(source)
    payload = json.loads(source.read_text(encoding="utf-8"))
    if set(payload) != ALLOWED or any(not isinstance(payload[key], str) or not payload[key] for key in ALLOWED):
        raise RuntimeError("vault JSON must contain exactly the documented non-empty secret keys")
    recipient = RECIPIENT.read_text(encoding="ascii").strip()
    temporary = ENCRYPTED.with_suffix(".age.new")
    subprocess.run(["age", "-r", recipient, "-o", str(temporary), str(source)], check=True)
    os.chmod(temporary, 0o600)
    os.replace(temporary, ENCRYPTED)


def unseal() -> None:
    private_regular(IDENTITY)
    private_regular(ENCRYPTED)
    service_uid = pwd.getpwnam("finfusion").pw_uid
    service_gid = grp.getgrnam("finfusion").gr_gid
    RUNTIME.mkdir(mode=0o750, parents=True, exist_ok=True)
    os.chown(RUNTIME, 0, service_gid)
    os.chmod(RUNTIME, 0o750)
    with tempfile.TemporaryDirectory(dir="/run/finfusion") as directory:
        clear = Path(directory) / "secrets.json"
        subprocess.run(["age", "-d", "-i", str(IDENTITY), "-o", str(clear), str(ENCRYPTED)], check=True)
        payload = json.loads(clear.read_text(encoding="utf-8"))
        if set(payload) != ALLOWED:
            raise RuntimeError("vault key set does not match this release")
        if payload["environment"] not in {"SANDBOX", "LIVE"}:
            raise RuntimeError("invalid vault environment")
        environment_dir = RUNTIME / payload["environment"].lower()
        environment_dir.mkdir(mode=0o700, exist_ok=True)
        os.chown(environment_dir, service_uid, service_gid)
        os.chmod(environment_dir, 0o700)
        for name, value in payload.items():
            if name == "environment":
                continue
            # Casdoor/cloudflared consume their shared node secrets; the API
            # reads all its own secrets only from the environment directory.
            target = (RUNTIME if name in {"casdoor_data_source", "tunnel_token"} else environment_dir) / name
            target.write_text(value, encoding="utf-8")
            os.chown(target, service_uid, service_gid)
            os.chmod(target, 0o600)


def purge() -> None:
    if RUNTIME.exists():
        shutil.rmtree(RUNTIME)


def main() -> int:
    require_root()
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("init", "seal", "unseal", "purge", "recipient"))
    parser.add_argument("source", nargs="?", type=Path)
    args = parser.parse_args()
    if args.action == "init": init()
    elif args.action == "seal":
        if args.source is None: raise SystemExit("seal requires a source JSON path")
        seal(args.source)
    elif args.action == "unseal": unseal()
    elif args.action == "purge": purge()
    else:
        init()
        print(RECIPIENT.read_text(encoding="ascii").strip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
