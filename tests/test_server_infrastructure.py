from __future__ import annotations

import json
import os
import time
import uuid
from decimal import Decimal

import pytest

from finfusion.controls import ControlPlane, ControlSnapshot
from finfusion.infrastructure import InfrastructureGate, InfrastructureSnapshot, NodeStateFileMonitor
from finfusion.models import AccountGrant, ClientGrant, Principal, UserGrant
from finfusion.service import InstitutionalTradingService
from finfusion.store import MemoryOrderStore


class Gateway:
    events_healthy = True

    def __init__(self): self.calls = []
    async def fresh_price(self, symbol, max_age): return Decimal("10")
    async def get_available_position(self, account_id, symbol): return Decimal("10")
    async def place_order(self, account_id, order): self.calls.append("place"); return {"ok": True}
    async def replace_order(self, account_id, order): self.calls.append("replace"); return {"ok": True}
    async def cancel_order(self, account_id, client_order_id): self.calls.append("cancel"); return {"ok": True}
    async def get_order_detail(self, account_id, client_order_id): return None


def controls():
    snapshot = ControlSnapshot.frozen(
        global_trade_enabled=True,
        version=1,
        users={"u": UserGrant("u", True, True)},
        clients={"d": ClientGrant("d", "u", "unused", True)},
        accounts={"a": AccountGrant("a", "u", "broker", "A", "***1", True, True)},
    )
    return ControlPlane(snapshot)


@pytest.mark.asyncio
async def test_infrastructure_gate_blocks_submit_and_replace_but_not_cancel():
    gate = InfrastructureGate()
    gateway = Gateway()
    service = InstitutionalTradingService(controls(), MemoryOrderStore(), gateway, infrastructure=gate)
    principal = Principal("u", "d")
    payload = {"accountRef": "a", "symbol": "AAPL", "side": "BUY", "orderType": "LIMIT", "quantity": 1, "limitPrice": "10"}
    with pytest.raises(RuntimeError, match="未激活"):
        await service.submit(principal, payload, str(uuid.uuid4()))
    gate.replace(InfrastructureSnapshot(True, True, 1, time.time(), "test"))
    placed = await service.submit(principal, payload, str(uuid.uuid4()))
    gate.force_closed("test-outage")
    with pytest.raises(RuntimeError, match="未激活"):
        await service.replace_limit(principal, "a", placed["order"]["clientOrderId"], "9", str(uuid.uuid4()))
    cancelled = await service.cancel(principal, "a", placed["order"]["clientOrderId"], str(uuid.uuid4()))
    assert cancelled["order"]["status"] == "CANCEL_REQUESTED"
    assert gateway.calls == ["place", "cancel"]


def test_state_monitor_is_fail_closed_for_stale_and_malformed_files(tmp_path, monkeypatch):
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"nodeActive": True, "tunnelHealthy": True, "generation": 1, "updatedAt": time.time()}), encoding="utf-8")
    if os.name != "nt":
        state.chmod(0o600)
        # A normal Linux user cannot create the root-owned production fixture.
        # First verify that the real non-root fixture is rejected; then simulate
        # only this fixture's ownership for the stale/malformed unit checks.
        if os.getuid() != 0:
            assert not NodeStateFileMonitor(InfrastructureGate(), state, stale_seconds=2).load_once().mutation_ready
        path_type = type(state)
        original_lstat = path_type.lstat

        def fixture_lstat(path, *args, **kwargs):
            info = original_lstat(path, *args, **kwargs)
            if path in {state.parent, state}:
                fields = list(info)
                fields[4] = 0  # st_uid; production filesystem ownership is unchanged.
                return os.stat_result(fields)
            return info

        monkeypatch.setattr(path_type, "lstat", fixture_lstat)
    gate = InfrastructureGate()
    monitor = NodeStateFileMonitor(gate, state, stale_seconds=2)
    assert monitor.load_once().mutation_ready
    state.write_text("{}", encoding="utf-8")
    assert not monitor.load_once().mutation_ready
    state.write_text(json.dumps({"nodeActive": True, "tunnelHealthy": True, "generation": 2, "updatedAt": time.time() - 10}), encoding="utf-8")
    assert not monitor.load_once().mutation_ready
