from __future__ import annotations

import asyncio
import json
import math
import os
import stat
import threading
import time
from dataclasses import dataclass, replace
from pathlib import Path
from .errors import ApiError


@dataclass(frozen=True, slots=True)
class InfrastructureSnapshot:
    """Immutable node-health snapshot read by the order hot path."""

    node_active: bool = False
    tunnel_healthy: bool = False
    generation: int = 0
    updated_at: float = 0.0
    reason: str = "startup-default-off"

    @property
    def mutation_ready(self) -> bool:
        return self.node_active and self.tunnel_healthy


class InfrastructureGate:
    """Atomic, in-memory fail-closed gate for new and replacement orders."""

    def __init__(self, snapshot: InfrastructureSnapshot | None = None):
        self._snapshot = snapshot or InfrastructureSnapshot()
        self._lock = threading.Lock()

    @property
    def snapshot(self) -> InfrastructureSnapshot:
        return self._snapshot

    def replace(self, snapshot: InfrastructureSnapshot) -> None:
        with self._lock:
            self._snapshot = snapshot

    def force_closed(self, reason: str) -> None:
        current = self._snapshot
        self.replace(
            replace(
                current,
                node_active=False,
                tunnel_healthy=False,
                generation=current.generation + 1,
                updated_at=time.time(),
                reason=reason,
            )
        )

    def require_mutation_ready(self) -> None:
        snapshot = self._snapshot
        if not snapshot.node_active:
            raise ApiError("NODE_NOT_READY", "服务器节点未激活，新单与改单已关闭", 503)
        if not snapshot.tunnel_healthy:
            raise ApiError("NODE_NOT_READY", "Cloudflare Tunnel 未就绪，新单与改单已关闭", 503)


class NodeStateFileMonitor:
    """Load a root-written runtime state file into an in-process gate.

    Missing, stale, malformed, symlinked, or unexpectedly permissive files are
    treated as unhealthy. The file contains no secret and must live on the WSL
    Linux filesystem (normally /run/finfusion/node-state.json).
    """

    def __init__(
        self,
        gate: InfrastructureGate,
        path: Path,
        *,
        stale_seconds: float = 15.0,
        poll_seconds: float = 1.0,
    ):
        if not math.isfinite(stale_seconds) or not 0 < stale_seconds <= 120:
            raise ValueError("状态过期时间必须在 (0, 120] 秒内")
        if not math.isfinite(poll_seconds) or not 0 < poll_seconds <= stale_seconds:
            raise ValueError("状态轮询间隔无效")
        self.gate = gate
        self.path = path
        self.stale_seconds = stale_seconds
        self.poll_seconds = poll_seconds

    def load_once(self) -> InfrastructureSnapshot:
        try:
            parent = self.path.parent.lstat()
            if stat.S_ISLNK(parent.st_mode) or not stat.S_ISDIR(parent.st_mode):
                raise ValueError("state-directory-type")
            info = self.path.lstat()
            if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
                raise ValueError("state-file-type")
            if os.name != "nt":
                if parent.st_uid != 0 or stat.S_IMODE(parent.st_mode) & 0o022:
                    raise ValueError("state-directory-permissions")
                if info.st_uid != 0 or stat.S_IMODE(info.st_mode) & 0o022:
                    raise ValueError("state-file-permissions")
            value = json.loads(self.path.read_text(encoding="utf-8"))
            updated_at = float(value["updatedAt"])
            generation = int(value["generation"])
            age = time.time() - updated_at
            if not math.isfinite(updated_at) or age > self.stale_seconds or age < -5:
                raise ValueError("state-file-stale")
            if type(value["nodeActive"]) is not bool or type(value["tunnelHealthy"]) is not bool:
                raise ValueError("state-file-fields")
            snapshot = InfrastructureSnapshot(
                node_active=value["nodeActive"],
                tunnel_healthy=value["tunnelHealthy"],
                generation=generation,
                updated_at=updated_at,
                reason=str(value.get("reason") or "host-state")[:120],
            )
        except Exception as exc:
            current = self.gate.snapshot
            snapshot = InfrastructureSnapshot(
                generation=current.generation + 1,
                updated_at=time.time(),
                reason=f"unhealthy:{type(exc).__name__}",
            )
        self.gate.replace(snapshot)
        return snapshot

    async def run(self) -> None:
        while True:
            self.load_once()
            await asyncio.sleep(self.poll_seconds)
