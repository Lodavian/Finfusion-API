from __future__ import annotations

import threading
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping

from .models import AccountGrant, ClientGrant, Principal, UserGrant


class AccessDenied(PermissionError):
    """A public-safe authorization or trade-control rejection."""


@dataclass(frozen=True, slots=True)
class ControlSnapshot:
    global_trade_enabled: bool = False
    version: int = 0
    users: Mapping[str, UserGrant] = field(default_factory=dict)
    clients: Mapping[str, ClientGrant] = field(default_factory=dict)
    accounts: Mapping[str, AccountGrant] = field(default_factory=dict)

    @classmethod
    def frozen(
        cls,
        *,
        global_trade_enabled: bool,
        version: int,
        users: Mapping[str, UserGrant],
        clients: Mapping[str, ClientGrant],
        accounts: Mapping[str, AccountGrant],
    ) -> "ControlSnapshot":
        return cls(
            global_trade_enabled=global_trade_enabled,
            version=version,
            users=MappingProxyType(dict(users)),
            clients=MappingProxyType(dict(clients)),
            accounts=MappingProxyType(dict(accounts)),
        )


class ControlPlane:
    """Atomic, in-process authorization snapshot used by the order hot path."""

    def __init__(self, snapshot: ControlSnapshot | None = None):
        self._snapshot = snapshot or ControlSnapshot()
        self._swap_lock = threading.Lock()

    @property
    def snapshot(self) -> ControlSnapshot:
        return self._snapshot

    def authorize(self, principal: Principal, permission: str = "read") -> ClientGrant:
        snapshot = self._snapshot
        user = snapshot.users.get(principal.user_id)
        client = snapshot.clients.get(principal.client_id)
        if user is None or not user.enabled or client is None or not client.enabled or client.user_id != principal.user_id:
            raise AccessDenied("用户或客户端未获授权")
        if permission not in {"read", "trade", "cancel"} or not getattr(client, "can_" + permission):
            raise AccessDenied("客户端缺少操作权限")
        return client

    def replace(self, snapshot: ControlSnapshot) -> None:
        if snapshot.version <= self._snapshot.version:
            raise ValueError("控制快照版本必须递增")
        with self._swap_lock:
            if snapshot.version <= self._snapshot.version:
                raise ValueError("控制快照版本必须递增")
            self._snapshot = snapshot

    def resolve(self, principal: Principal, account_ref: str, *, mutation: str, check_trade_gate: bool = True) -> AccountGrant:
        self.authorize(principal, "trade" if mutation in {"submit", "replace"} else "cancel" if mutation == "cancel" else "read")
        snapshot = self._snapshot
        user = snapshot.users.get(principal.user_id)
        if user is None or not user.enabled:
            raise AccessDenied("用户已禁用")
        client = snapshot.clients.get(principal.client_id)
        if client is None or client.user_id != principal.user_id or not client.enabled:
            raise AccessDenied("客户端未获授权")
        account = snapshot.accounts.get(str(account_ref))
        if account is None or account.owner_user_id != principal.user_id or not account.enabled:
            raise AccessDenied("账户不可用或未授权")
        if mutation in {"submit", "replace"}:
            if not check_trade_gate:
                return account
            if not snapshot.global_trade_enabled:
                raise AccessDenied("机构交易总开关已关闭")
            if not user.trade_enabled:
                raise AccessDenied("当前用户交易已中断")
            if not account.trade_enabled:
                raise AccessDenied("当前账户交易已中断")
        elif mutation not in {"read", "cancel", "select"}:
            raise ValueError("未知控制操作")
        return account

    def public_accounts(self, principal: Principal) -> list[dict[str, object]]:
        client = self.authorize(principal)
        snapshot = self._snapshot
        user = snapshot.users.get(principal.user_id)
        client = snapshot.clients.get(principal.client_id)
        if user is None or not user.enabled or client is None or not client.enabled or client.user_id != principal.user_id:
            raise AccessDenied("用户或客户端未获授权")
        result = []
        for item in snapshot.accounts.values():
            if item.owner_user_id != principal.user_id or not item.enabled:
                continue
            result.append(
                {
                    "accountRef": item.account_ref,
                    "alias": item.alias,
                    "accountMask": item.account_mask,
                    "tradeEnabled": bool(
                        snapshot.global_trade_enabled and user.trade_enabled and item.trade_enabled and client.can_trade
                    ),
                    "controlVersion": snapshot.version,
                }
            )
        return sorted(result, key=lambda row: (str(row["alias"]), str(row["accountRef"])))
