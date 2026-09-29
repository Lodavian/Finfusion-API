#!/usr/bin/env python3
"""Root-only node activation and tunnel heartbeat state manager."""

from __future__ import annotations

import argparse
import json
import os
import grp
import tempfile
import time
from pathlib import Path


STATE = Path("/run/finfusion/node-state.json")


def read() -> dict:
    try:
        value = json.loads(STATE.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def write(*, active: bool | None = None, tunnel: bool | None = None, reason: str) -> dict:
    previous = read()
    value = {
        "nodeActive": bool(previous.get("nodeActive", False) if active is None else active),
        "tunnelHealthy": bool(previous.get("tunnelHealthy", False) if tunnel is None else tunnel),
        "generation": int(previous.get("generation", 0)) + 1,
        "updatedAt": time.time(),
        "reason": reason[:120],
    }
    STATE.parent.mkdir(mode=0o750, parents=True, exist_ok=True)
    service_gid = grp.getgrnam("finfusion").gr_gid
    os.chown(STATE.parent, 0, service_gid)
    os.chmod(STATE.parent, 0o750)
    fd, temporary = tempfile.mkstemp(prefix=".node-state-", dir=STATE.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, separators=(",", ":"))
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o640)
        os.chown(temporary, 0, service_gid)
        os.replace(temporary, STATE)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
    return value


def main() -> int:
    if os.geteuid() != 0:
        raise SystemExit("node_state.py must run as root")
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("activate", "deactivate", "heartbeat", "show"))
    parser.add_argument("--tunnel", choices=("healthy", "unhealthy"))
    parser.add_argument("--reason", default="operator")
    args = parser.parse_args()
    if args.action == "show":
        print(json.dumps(read(), sort_keys=True))
        return 0
    if args.action == "activate":
        value = write(active=True, reason=args.reason)
    elif args.action == "deactivate":
        value = write(active=False, reason=args.reason)
    else:
        value = write(tunnel=args.tunnel == "healthy", reason=args.reason)
    print(json.dumps(value, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
