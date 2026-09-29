"""Safely extract the reviewed Casdoor Linux release runtime tree."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import stat
import tarfile
from pathlib import Path, PurePosixPath


MAX_MEMBER_BYTES = 256 * 1024 * 1024
MAX_TOTAL_BYTES = 1024 * 1024 * 1024
MAX_ARCHIVE_BYTES = 512 * 1024 * 1024
REQUIRED = {"casdoor", "conf/app.conf", "web/build/index.html", "web/build/asset-manifest.json"}


def _safe_name(raw: str) -> str:
    if not raw or "\\" in raw or "\x00" in raw:
        raise ValueError(f"unsafe Casdoor archive path: {raw!r}")
    path = PurePosixPath(raw.removeprefix("./"))
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise ValueError(f"unsafe Casdoor archive path: {raw!r}")
    normalized = path.as_posix()
    if normalized == "casdoor" or normalized == "conf/app.conf" or normalized.startswith("web/build/"):
        return normalized
    if normalized in {"conf", "web", "web/build"}:
        return normalized
    raise ValueError(f"unexpected Casdoor archive member: {normalized}")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def extract(archive: Path, destination: Path, manifest_out: Path | None = None, expected_sha256: str | None = None) -> dict:
    archive = archive.resolve(strict=True)
    destination = destination.resolve()
    if destination.exists():
        raise ValueError("Casdoor extraction destination already exists")
    if archive.stat().st_size > MAX_ARCHIVE_BYTES:
        raise ValueError("Casdoor release archive exceeds the compressed size limit")
    payload = archive.read_bytes()
    archive_sha256 = hashlib.sha256(payload).hexdigest()
    if expected_sha256 is not None and archive_sha256 != expected_sha256.lower():
        raise ValueError("Casdoor release archive SHA-256 mismatch")
    records: list[tuple[tarfile.TarInfo, str]] = []
    seen: set[str] = set()
    total = 0
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as source:
        for member in source.getmembers():
            name = _safe_name(member.name)
            if name in seen:
                raise ValueError(f"duplicate Casdoor archive member: {name}")
            seen.add(name)
            if not (member.isfile() or member.isdir()):
                raise ValueError(f"links and special Casdoor archive members are forbidden: {name}")
            if member.size < 0 or member.size > MAX_MEMBER_BYTES:
                raise ValueError(f"Casdoor archive member is too large: {name}")
            total += member.size
            if total > MAX_TOTAL_BYTES:
                raise ValueError("Casdoor archive expands beyond the size limit")
            records.append((member, name))
        missing = REQUIRED - seen
        if missing:
            raise ValueError(f"Casdoor archive is incomplete: {sorted(missing)}")

        destination.mkdir(mode=0o755, parents=True)
        manifest: dict[str, dict[str, object]] = {}
        for member, name in records:
            target = destination / Path(*PurePosixPath(name).parts)
            resolved = target.resolve()
            if destination != resolved and destination not in resolved.parents:
                raise ValueError(f"Casdoor extraction escaped destination: {name}")
            if member.isdir():
                target.mkdir(mode=0o755, parents=True, exist_ok=True)
                os.chmod(target, 0o755)
                manifest[name] = {"type": "directory", "mode": "0755"}
                continue
            target.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
            stream = source.extractfile(member)
            if stream is None:
                raise ValueError(f"cannot read Casdoor archive member: {name}")
            with target.open("xb") as output:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    output.write(block)
            mode = 0o755 if name == "casdoor" else 0o644
            os.chmod(target, mode)
            manifest[name] = {"type": "file", "mode": f"{mode:04o}", "bytes": target.stat().st_size, "sha256": _sha256(target)}

    result = {"schemaVersion": 1, "archiveSha256": archive_sha256, "members": manifest}
    if manifest_out is not None:
        manifest_out.parent.mkdir(parents=True, exist_ok=True)
        manifest_out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("archive", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--manifest-out", type=Path)
    parser.add_argument("--expected-sha256")
    args = parser.parse_args()
    extract(args.archive, args.destination, args.manifest_out, args.expected_sha256)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
