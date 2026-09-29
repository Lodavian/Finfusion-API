#!/usr/bin/env python3
from __future__ import annotations

import subprocess


def main() -> int:
    healthy = subprocess.run(
        ["curl", "--fail", "--silent", "--show-error", "--max-time", "2", "http://127.0.0.1:2000/ready"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    ).returncode == 0
    subprocess.run(
        ["/opt/finfusion/bin/node_state.py", "heartbeat", "--tunnel", "healthy" if healthy else "unhealthy", "--reason", "tunnel-probe"],
        check=True,
    )
    return 0 if healthy else 1


if __name__ == "__main__":
    raise SystemExit(main())
