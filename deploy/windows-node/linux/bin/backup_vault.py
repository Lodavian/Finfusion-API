#!/usr/bin/env python3
"""Create and validate the versioned plaintext payload used inside an age vault."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
try:
    import pwd
    import grp
except ImportError:  # Allows platform-neutral policy unit tests; runtime is Linux-only.
    pwd = None  # type: ignore[assignment]
    grp = None  # type: ignore[assignment]
import stat
import tarfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath


PRODUCT = "Finfusion Node Backup"
SCHEMA_VERSION = 1
MAX_MEMBER_BYTES = 8 * 1024 * 1024 * 1024
MAX_TOTAL_BYTES = 16 * 1024 * 1024 * 1024
REQUIRED_FILES = {
    "databases/finfusion.dump",
    "databases/casdoor.dump",
    "vault/identity.txt",
    "vault/recipient.txt",
    "vault/secrets.age",
    "config/server.env",
    "config/domains.json",
    "config/backup-recipient.txt",
    "metadata/VERSION",
}
REQUIRED_MEMBERS = REQUIRED_FILES | {"webull_tokens"}
ALLOWED_PREFIXES = ("databases/", "vault/", "webull_tokens/", "config/", "metadata/")
ALLOWED_FIXED = REQUIRED_FILES | {
    "databases", "vault", "webull_tokens", "config", "metadata",
    "config/update-minisign.pub", "metadata/debian-base-manifest.json",
}


def sha256_stream(stream) -> str:
    digest = hashlib.sha256()
    for block in iter(lambda: stream.read(1024 * 1024), b""):
        digest.update(block)
    return digest.hexdigest()


def owner_names(uid: int, gid: int) -> tuple[str, str]:
    if pwd is None or grp is None: raise RuntimeError("backup Vault runtime requires Linux")
    try: user = pwd.getpwuid(uid).pw_name
    except KeyError: user = str(uid)
    try: group = grp.getgrgid(gid).gr_name
    except KeyError: group = str(gid)
    return user, group


def safe_name(name: str) -> str:
    normalized = name.removeprefix("./")
    path = PurePosixPath(normalized)
    if not normalized or path.is_absolute() or ".." in path.parts or "\\" in normalized:
        raise ValueError(f"unsafe archive path: {name}")
    return path.as_posix()


def policy(path: str, kind: str, mode: int, user: str, group: str, uid: int, gid: int) -> None:
    if path != "manifest.json" and not path.startswith(ALLOWED_PREFIXES):
        raise ValueError(f"archive path outside policy: {path}")
    if kind not in {"file", "directory"}:
        raise ValueError(f"unsupported archive member type: {path}")
    if mode & 0o7022 or mode > 0o755:
        raise ValueError(f"unsafe archive mode: {path}: {mode:o}")
    if user not in {"root", "finfusion"} or group not in {"root", "finfusion"}:
        raise ValueError(f"unsafe archive owner: {path}: {user}:{group}")
    if (user == "root" and uid != 0) or (group == "root" and gid != 0) or (user == "finfusion" and uid <= 0) or (group == "finfusion" and gid <= 0):
        raise ValueError(f"archive numeric/name owner mismatch: {path}")
    if path != "manifest.json" and path not in ALLOWED_FIXED and not path.startswith("webull_tokens/"):
        raise ValueError(f"unexpected backup member: {path}")
    exact = {
        "manifest.json": (0o600, "root", "root"),
        "databases": (0o700, "root", "root"),
        "vault": (0o700, "root", "root"),
        "config": (0o700, "root", "root"),
        "metadata": (0o700, "root", "root"),
        "webull_tokens": (0o700, "finfusion", "finfusion"),
        "databases/finfusion.dump": (0o600, "root", "root"),
        "databases/casdoor.dump": (0o600, "root", "root"),
        "vault/identity.txt": (0o600, "root", "root"),
        "vault/recipient.txt": (0o644, "root", "root"),
        "vault/secrets.age": (0o600, "root", "root"),
        "config/server.env": (0o640, "root", "finfusion"),
        "config/domains.json": (0o640, "root", "finfusion"),
        "config/backup-recipient.txt": (0o644, "root", "root"),
        "metadata/VERSION": (0o644, "root", "root"),
    }
    if path in exact and (mode, user, group) != exact[path]:
        raise ValueError(f"archive metadata mismatch: {path}")
    if path.startswith("webull_tokens/"):
        expected_mode = 0o700 if kind == "directory" else 0o600
        if (mode, user, group) != (expected_mode, "finfusion", "finfusion"):
            raise ValueError(f"unsafe token metadata: {path}")


def scan_stage(stage: Path) -> dict[str, dict[str, object]]:
    files: dict[str, dict[str, object]] = {}
    for path in sorted(stage.rglob("*")):
        relative = path.relative_to(stage).as_posix()
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode) or not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)):
            raise ValueError(f"unsupported staged member: {relative}")
        kind = "directory" if stat.S_ISDIR(info.st_mode) else "file"
        user, group = owner_names(info.st_uid, info.st_gid)
        mode = stat.S_IMODE(info.st_mode)
        policy(relative, kind, mode, user, group, info.st_uid, info.st_gid)
        record: dict[str, object] = {"type": kind, "mode": f"{mode:04o}", "owner": user, "group": group, "uid": info.st_uid, "gid": info.st_gid}
        if kind == "file":
            with path.open("rb") as stream: record["sha256"] = sha256_stream(stream)
            record["bytes"] = info.st_size
        files[relative] = record
    missing = REQUIRED_MEMBERS - files.keys()
    if missing:
        raise ValueError(f"backup payload missing required files: {sorted(missing)}")
    return files


def create(stage: Path, archive: Path, version_file: Path) -> None:
    if archive.exists():
        raise ValueError("refusing to overwrite archive")
    version = version_file.read_text(encoding="utf-8").strip()
    files = scan_stage(stage)
    node_id = hashlib.sha256(Path("/etc/machine-id").read_bytes()).hexdigest()[:16]
    manifest = {
        "schemaVersion": SCHEMA_VERSION,
        "product": PRODUCT,
        "applicationVersion": version,
        "createdUtc": datetime.now(timezone.utc).isoformat(),
        "sourceNodeId": node_id,
        "databaseFormat": "PostgreSQL custom",
        "files": files,
    }
    manifest_path = stage / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    os.chown(manifest_path, 0, 0)
    os.chmod(manifest_path, 0o600)
    with tarfile.open(archive, "w", format=tarfile.PAX_FORMAT) as output:
        output.add(manifest_path, arcname="manifest.json", recursive=False)
        for relative in sorted(files):
            output.add(stage / relative, arcname=relative, recursive=False)
    os.chmod(archive, 0o600)


def validate_and_extract(archive: Path, destination: Path, version_file: Path) -> dict:
    if pwd is None or grp is None: raise RuntimeError("backup Vault runtime requires Linux")
    current_version = version_file.read_text(encoding="utf-8").strip()
    with tarfile.open(archive, "r:") as source:
        members = source.getmembers()
        total_bytes = 0
        for member in members:
            if member.size < 0 or member.size > MAX_MEMBER_BYTES:
                raise ValueError(f"archive member exceeds size limit: {member.name}")
            total_bytes += member.size
            if total_bytes > MAX_TOTAL_BYTES:
                raise ValueError("backup archive exceeds total size limit")
        names = [safe_name(item.name) for item in members]
        if len(names) != len(set(names)) or "manifest.json" not in names:
            raise ValueError("archive has duplicate paths or no manifest")
        manifest_member = members[names.index("manifest.json")]
        if not manifest_member.isfile() or manifest_member.size > 8 * 1024 * 1024:
            raise ValueError("invalid manifest member")
        policy("manifest.json", "file", manifest_member.mode, manifest_member.uname or str(manifest_member.uid), manifest_member.gname or str(manifest_member.gid), manifest_member.uid, manifest_member.gid)
        manifest_stream = source.extractfile(manifest_member)
        if manifest_stream is None: raise ValueError("manifest cannot be read")
        manifest = json.load(manifest_stream)
        if manifest.get("schemaVersion") != SCHEMA_VERSION or manifest.get("product") != PRODUCT:
            raise ValueError("unsupported backup schema/product")
        if manifest.get("applicationVersion") != current_version or manifest.get("databaseFormat") != "PostgreSQL custom":
            raise ValueError("backup application/database version mismatch")
        expected = manifest.get("files")
        if not isinstance(expected, dict) or REQUIRED_MEMBERS - expected.keys():
            raise ValueError("manifest is incomplete")
        if set(names) != {"manifest.json", *expected.keys()}:
            raise ValueError("archive and manifest member sets differ")
        for member, name in zip(members, names):
            if name == "manifest.json": continue
            record = expected.get(name)
            if not isinstance(record, dict): raise ValueError(f"missing manifest entry: {name}")
            kind = "directory" if member.isdir() else "file" if member.isfile() else "unsupported"
            user, group = member.uname or str(member.uid), member.gname or str(member.gid)
            policy(name, kind, member.mode, user, group, member.uid, member.gid)
            if (record.get("type") != kind or record.get("mode") != f"{member.mode:04o}" or record.get("owner") != user or record.get("group") != group
                    or record.get("uid") != member.uid or record.get("gid") != member.gid):
                raise ValueError(f"manifest metadata mismatch: {name}")
            if kind == "file":
                stream = source.extractfile(member)
                if stream is None or sha256_stream(stream) != record.get("sha256") or member.size != record.get("bytes"):
                    raise ValueError(f"manifest checksum/size mismatch: {name}")

        destination.mkdir(mode=0o700, parents=True, exist_ok=False)
        os.chmod(destination, 0o700)
        for member, name in zip(members, names):
            target = destination / name
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                stream = source.extractfile(member)
                if stream is None: raise ValueError(f"cannot extract: {name}")
                with target.open("xb") as output:
                    for block in iter(lambda: stream.read(1024 * 1024), b""): output.write(block)
            user, group = member.uname or str(member.uid), member.gname or str(member.gid)
            os.chown(target, pwd.getpwnam(user).pw_uid, grp.getgrnam(group).gr_gid)
            os.chmod(target, member.mode)
    return manifest


def main() -> int:
    if os.geteuid() != 0: raise SystemExit("backup_vault.py must run as root")
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="action", required=True)
    create_parser = subparsers.add_parser("create")
    create_parser.add_argument("stage", type=Path)
    create_parser.add_argument("archive", type=Path)
    create_parser.add_argument("--version-file", type=Path, default=Path("/opt/finfusion/VERSION"))
    validate_parser = subparsers.add_parser("validate-extract")
    validate_parser.add_argument("archive", type=Path)
    validate_parser.add_argument("destination", type=Path)
    validate_parser.add_argument("--version-file", type=Path, default=Path("/opt/finfusion/VERSION"))
    args = parser.parse_args()
    if args.action == "create": create(args.stage.resolve(), args.archive.resolve(), args.version_file)
    else: print(json.dumps(validate_and_extract(args.archive.resolve(), args.destination.resolve(), args.version_file), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
