from __future__ import annotations

import json
import hashlib
import hmac
import uuid
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .controls import ControlSnapshot
from .models import AccountGrant, ClientGrant, ServerOrder, UserGrant
from .store import ACTIVE_STATUSES


class AccountCipher:
    def __init__(self, key: bytes):
        if len(key) != 32:
            raise ValueError("账户加密主密钥必须是32字节")
        self._cipher = AESGCM(key)
        self._key = key

    def encrypt(self, account_id: str) -> bytes:
        import os

        nonce = os.urandom(12)
        return nonce + self._cipher.encrypt(nonce, account_id.encode("utf-8"), b"Finfusion/account-id/v1")

    def decrypt(self, value: bytes) -> str:
        raw = bytes(value)
        if len(raw) < 29:
            raise ValueError("账户密文损坏")
        return self._cipher.decrypt(raw[:12], raw[12:], b"Finfusion/account-id/v1").decode("utf-8")

    def fingerprint(self, account_id: str) -> str:
        """Stable, non-reversible identifier used only to reject duplicate account rows."""
        return hmac.new(self._key, account_id.encode("utf-8"), hashlib.sha256).hexdigest()


class PostgresStore:
    def __init__(self, pool: Any, cipher: AccountCipher):
        self.pool = pool
        self.cipher = cipher

    @classmethod
    async def connect(cls, dsn: str, cipher: AccountCipher) -> "PostgresStore":
        try:
            import asyncpg
        except ImportError as exc:  # pragma: no cover - deployment dependency
            raise RuntimeError("asyncpg未安装") from exc
        pool = await asyncpg.create_pool(
            dsn, min_size=1, max_size=8, command_timeout=10,
            server_settings={"search_path": "finfusion", "application_name": "finfusion-server"},
        )
        return cls(pool, cipher)

    async def migrate(self) -> None:
        # One active trading process per environment: in-memory account locks
        # and cached permissions must never be bypassed by a second worker.
        self._leader = await self.pool.acquire()
        if not await self._leader.fetchval("SELECT pg_try_advisory_lock(739158201)"):
            await self.pool.release(self._leader)
            self._leader = None
            raise RuntimeError("已有 Finfusion 交易进程使用该数据库")
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                for path in sorted(Path(__file__).with_name("migrations").glob("*.sql")):
                    await connection.execute(path.read_text(encoding="utf-8"))

    async def bind_environment(self, environment: str) -> None:
        await self.pool.execute("INSERT INTO deployment_environment(singleton,environment) VALUES(TRUE,$1) ON CONFLICT DO NOTHING", environment)
        if await self.pool.fetchval("SELECT environment FROM deployment_environment WHERE singleton=TRUE") != environment:
            raise RuntimeError("数据库已属于另一个交易环境，请使用独立数据库")

    async def consume_nonce(self, client_id: str, nonce: str) -> None:
        from .controls import AccessDenied
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute("DELETE FROM request_nonces WHERE seen_at < now()-interval '120 seconds'")
                result = await connection.execute("INSERT INTO request_nonces(client_id,nonce) VALUES($1::uuid,$2) ON CONFLICT DO NOTHING", client_id, nonce)
                if result.endswith(" 0"):
                    raise AccessDenied("请求已被重放")

    async def configure_client(self, client_id: str, payload: dict, actor: str) -> ControlSnapshot:
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                row = await connection.fetchrow("SELECT * FROM clients WHERE client_id=$1::uuid FOR UPDATE", client_id)
                if row is None:
                    raise ValueError("客户端不存在")
                rotated = "publicKeyPem" in payload
                await connection.execute(
                    "UPDATE clients SET enabled=$2,public_key_pem=$3,can_read=$4,can_trade=$5,can_cancel=$6 WHERE client_id=$1::uuid",
                    client_id, False if rotated else payload.get("enabled", row["enabled"]),
                    payload.get("publicKeyPem", row["public_key_pem"]), payload.get("canRead", row["can_read"]),
                    payload.get("canTrade", row["can_trade"]), payload.get("canCancel", row["can_cancel"]),
                )
                await connection.execute("UPDATE control_state SET version=version+1 WHERE singleton=TRUE")
                await connection.execute("INSERT INTO audit_events(actor_user_id,client_id,action,outcome) VALUES($1,$2::uuid,$3,'OK')", actor, client_id, "client.rotate" if rotated else "client.permissions")
        return await self.load_controls()

    async def close(self) -> None:
        if getattr(self, "_leader", None) is not None:
            await self._leader.execute("SELECT pg_advisory_unlock(739158201)")
            await self.pool.release(self._leader)
            self._leader = None
        await self.pool.close()

    async def healthy(self) -> bool:
        try:
            return int(await self.pool.fetchval("SELECT 1")) == 1
        except Exception:
            return False

    async def load_controls(self, *, force_global_off: bool = False) -> ControlSnapshot:
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                if force_global_off:
                    await connection.execute(
                        "UPDATE control_state SET global_trade_enabled=FALSE, version=version+1, "
                        "updated_at=now(), updated_by='bootstrap', reason='服务重启后默认关闭交易' WHERE singleton=TRUE"
                    )
                state = await connection.fetchrow("SELECT global_trade_enabled, version FROM control_state WHERE singleton=TRUE")
                users = await connection.fetch("SELECT user_id, enabled, trade_enabled FROM app_users")
                clients = await connection.fetch("SELECT client_id, user_id, public_key_pem, enabled, can_read, can_trade, can_cancel FROM clients")
                accounts = await connection.fetch(
                    "SELECT a.account_ref, a.broker_account_cipher, a.account_mask, a.alias, a.enabled, "
                    "a.trade_enabled, b.user_id FROM broker_accounts a "
                    "JOIN user_account_bindings b ON b.account_ref=a.account_ref"
                )
        return ControlSnapshot.frozen(
            global_trade_enabled=bool(state["global_trade_enabled"]),
            version=int(state["version"]),
            users={
                str(row["user_id"]): UserGrant(str(row["user_id"]), bool(row["enabled"]), bool(row["trade_enabled"]))
                for row in users
            },
            clients={
                str(row["client_id"]): ClientGrant(str(row["client_id"]), str(row["user_id"]), str(row["public_key_pem"]), bool(row["enabled"]), bool(row["can_read"]), bool(row["can_trade"]), bool(row["can_cancel"]))
                for row in clients
            },
            accounts={
                str(row["account_ref"]): AccountGrant(
                    str(row["account_ref"]), str(row["user_id"]),
                    self.cipher.decrypt(row["broker_account_cipher"]), str(row["alias"]),
                    str(row["account_mask"]), bool(row["enabled"]), bool(row["trade_enabled"]),
                )
                for row in accounts
            },
        )

    async def set_control(self, scope: str, key: str | None, enabled: bool, actor: str, reason: str) -> ControlSnapshot:
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                if scope == "global":
                    await connection.execute(
                        "UPDATE control_state SET global_trade_enabled=$1, version=version+1, updated_at=now(), updated_by=$2, reason=$3 WHERE singleton=TRUE",
                        enabled, actor, reason,
                    )
                elif scope == "user":
                    result = await connection.execute("UPDATE app_users SET trade_enabled=$1, updated_at=now() WHERE user_id=$2", enabled, key)
                    if result.endswith(" 0"):
                        raise ValueError("用户不存在")
                    await connection.execute("UPDATE control_state SET version=version+1 WHERE singleton=TRUE")
                elif scope == "account":
                    result = await connection.execute("UPDATE broker_accounts SET trade_enabled=$1, updated_at=now() WHERE account_ref=$2::uuid", enabled, key)
                    if result.endswith(" 0"):
                        raise ValueError("账户不存在")
                    await connection.execute("UPDATE control_state SET version=version+1 WHERE singleton=TRUE")
                else:
                    raise ValueError("不支持的控制范围")
                await connection.execute(
                    "INSERT INTO audit_events(actor_user_id, action, account_ref, outcome, reason) VALUES($1,$2,$3::uuid,'OK',$4)",
                    actor, f"trade.{scope}.{'enable' if enabled else 'disable'}", key if scope == "account" else None, reason,
                )
        return await self.load_controls()

    async def register_client(self, user_id: str, label: str, public_key_pem: str) -> tuple[str, ControlSnapshot]:
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                exists = await connection.fetchval("SELECT enabled FROM app_users WHERE user_id=$1", user_id)
                if exists is None or not exists:
                    raise ValueError("用户尚未由管理员启用")
                client_id = await connection.fetchval(
                    "INSERT INTO clients(user_id,label,public_key_pem,enabled) VALUES($1,$2,$3,FALSE) RETURNING client_id",
                    user_id, label, public_key_pem,
                )
                await connection.execute("UPDATE control_state SET version=version+1 WHERE singleton=TRUE")
                await connection.execute(
                    "INSERT INTO audit_events(actor_user_id,client_id,action,outcome) VALUES($1,$2,'client.register','OK')",
                    user_id, client_id,
                )
        return str(client_id), await self.load_controls()

    async def set_client_enabled(self, client_id: str, enabled: bool, actor: str) -> ControlSnapshot:
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                result = await connection.execute("UPDATE clients SET enabled=$1 WHERE client_id=$2::uuid", enabled, client_id)
                if result.endswith(" 0"):
                    raise ValueError("客户端不存在")
                await connection.execute("UPDATE control_state SET version=version+1 WHERE singleton=TRUE")
                await connection.execute(
                    "INSERT INTO audit_events(actor_user_id,client_id,action,outcome) VALUES($1,$2::uuid,$3,'OK')",
                    actor, client_id, "client.enable" if enabled else "client.disable",
                )
        return await self.load_controls()

    async def record_login(self, user_id: str, client_id: str) -> None:
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute(
                    "UPDATE clients SET last_seen_at=now() WHERE client_id=$1::uuid AND user_id=$2",
                    client_id, user_id,
                )
                await connection.execute(
                    "INSERT INTO audit_events(actor_user_id,client_id,action,outcome) VALUES($1,$2::uuid,'login.accepted','OK')",
                    user_id, client_id,
                )

    async def record_rejection(self, client_id: str, path: str, reason: str) -> None:
        try:
            safe_client = str(uuid.UUID(client_id))
        except (ValueError, AttributeError):
            safe_client = None
        await self.pool.execute(
            "INSERT INTO audit_events(actor_user_id,client_id,action,outcome,reason) VALUES('unknown',$1::uuid,$2,'REJECTED',$3)",
            safe_client, f"request.reject:{path[:80]}", reason[:200],
        )

    async def upsert_user(self, user_id: str, casdoor_name: str, actor: str) -> ControlSnapshot:
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute(
                    "INSERT INTO app_users(user_id,casdoor_name,enabled,trade_enabled) VALUES($1,$2,TRUE,FALSE) "
                    "ON CONFLICT(user_id) DO UPDATE SET casdoor_name=EXCLUDED.casdoor_name, enabled=TRUE, updated_at=now()", user_id, casdoor_name,
                )
                await connection.execute("UPDATE control_state SET version=version+1 WHERE singleton=TRUE")
                await connection.execute(
                    "INSERT INTO audit_events(actor_user_id,action,outcome,reason) VALUES($1,'user.create','OK',$2)",
                    actor, user_id,
                )
        return await self.load_controls()

    async def set_user_enabled(self, user_id: str, enabled: bool, actor: str) -> ControlSnapshot:
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                result = await connection.execute(
                    "UPDATE app_users SET enabled=$1, updated_at=now() WHERE user_id=$2", enabled, user_id,
                )
                if result.endswith(" 0"):
                    raise ValueError("用户不存在")
                await connection.execute("UPDATE control_state SET version=version+1 WHERE singleton=TRUE")
                await connection.execute(
                    "INSERT INTO audit_events(actor_user_id,action,outcome,reason) VALUES($1,$2,'OK',$3)",
                    actor, "user.enable" if enabled else "user.disable", user_id,
                )
        return await self.load_controls()

    async def casdoor_name(self, user_id: str) -> str:
        name = await self.pool.fetchval("SELECT casdoor_name FROM app_users WHERE user_id=$1", user_id)
        if not name:
            raise ValueError("用户不存在或缺少身份系统映射")
        return str(name)

    async def add_broker_account(self, broker_account_id: str, alias: str, account_mask: str, actor: str) -> tuple[str, ControlSnapshot]:
        value = self.cipher.encrypt(broker_account_id)
        fingerprint = self.cipher.fingerprint(broker_account_id)
        try:
            async with self.pool.acquire() as connection:
                async with connection.transaction():
                    account_ref = await connection.fetchval(
                        "INSERT INTO broker_accounts(broker_account_cipher,account_fingerprint,account_mask,alias,enabled,trade_enabled) "
                        "VALUES($1,$2,$3,$4,TRUE,FALSE) RETURNING account_ref", value, fingerprint, account_mask, alias,
                    )
                    await connection.execute("UPDATE control_state SET version=version+1 WHERE singleton=TRUE")
                    await connection.execute(
                        "INSERT INTO audit_events(actor_user_id,action,account_ref,outcome) VALUES($1,'account.register',$2::uuid,'OK')",
                        actor, account_ref,
                    )
        except Exception as exc:
            existing = await self.pool.fetchval(
                "SELECT account_ref FROM broker_accounts WHERE account_fingerprint=$1", fingerprint,
            )
            if existing is not None:
                raise ValueError("该机构账户已登记") from None
            raise exc
        return str(account_ref), await self.load_controls()

    async def bind_account(self, user_id: str, account_ref: str, actor: str) -> ControlSnapshot:
        try:
            async with self.pool.acquire() as connection:
                async with connection.transaction():
                    await connection.execute(
                        "INSERT INTO user_account_bindings(user_id,account_ref) VALUES($1,$2::uuid)", user_id, account_ref,
                    )
                    await connection.execute("UPDATE control_state SET version=version+1 WHERE singleton=TRUE")
                    await connection.execute(
                        "INSERT INTO audit_events(actor_user_id,action,account_ref,outcome,reason) VALUES($1,'account.bind',$2::uuid,'OK',$3)",
                        actor, account_ref, user_id,
                    )
        except Exception as exc:
            raise ValueError("账户绑定失败；账户可能已分配给其他用户") from exc
        return await self.load_controls()

    async def unbind_account(self, account_ref: str, actor: str) -> ControlSnapshot:
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                result = await connection.execute(
                    "DELETE FROM user_account_bindings WHERE account_ref=$1::uuid", account_ref,
                )
                if result.endswith(" 0"):
                    raise ValueError("账户尚未绑定")
                await connection.execute("UPDATE control_state SET version=version+1 WHERE singleton=TRUE")
                await connection.execute(
                    "INSERT INTO audit_events(actor_user_id,action,account_ref,outcome) VALUES($1,'account.unbind',$2::uuid,'OK')",
                    actor, account_ref,
                )
        return await self.load_controls()

    async def admin_snapshot(self) -> dict[str, Any]:
        async with self.pool.acquire() as connection:
            users = await connection.fetch("SELECT user_id,casdoor_name,enabled,trade_enabled,updated_at FROM app_users ORDER BY casdoor_name")
            accounts = await connection.fetch(
                "SELECT a.account_ref,a.account_mask,a.alias,a.enabled,a.trade_enabled,b.user_id "
                "FROM broker_accounts a LEFT JOIN user_account_bindings b USING(account_ref) ORDER BY a.alias"
            )
            clients = await connection.fetch(
                "SELECT client_id,user_id,label,enabled,can_read,can_trade,can_cancel,created_at,last_seen_at FROM clients ORDER BY created_at DESC"
            )
            state = await connection.fetchrow("SELECT global_trade_enabled,version,reason,updated_at,updated_by FROM control_state WHERE singleton=TRUE")
        def clean(row: Any) -> dict[str, Any]:
            return {key: (value.isoformat() if isinstance(value, datetime) else str(value) if key.endswith("_ref") or key.endswith("_id") else value) for key, value in dict(row).items()}
        return {"control": clean(state), "users": [clean(row) for row in users], "accounts": [clean(row) for row in accounts], "clients": [clean(row) for row in clients]}

    async def registered_broker_account_ids(self) -> set[str]:
        rows = await self.pool.fetch("SELECT broker_account_cipher FROM broker_accounts")
        return {self.cipher.decrypt(row["broker_account_cipher"]) for row in rows}

    async def find_request(self, account_ref: str, request_id: str) -> tuple[ServerOrder, str] | None:
        row = await self.pool.fetchrow(
            "SELECT o.*, i.payload_hash AS action_hash FROM idempotency_keys i JOIN orders o USING(account_ref, client_order_id) "
            "WHERE i.account_ref=$1::uuid AND i.request_id=$2::uuid", account_ref, request_id,
        )
        return (self._row(row), str(row["action_hash"])) if row else None

    async def find(self, account_ref: str, client_order_id: str) -> ServerOrder | None:
        row = await self.pool.fetchrow("SELECT * FROM orders WHERE account_ref=$1::uuid AND client_order_id=$2", account_ref, client_order_id)
        return self._row(row) if row else None

    async def insert(self, order: ServerOrder) -> ServerOrder:
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                existing = await connection.fetchrow(
                    "SELECT payload_hash, client_order_id FROM idempotency_keys WHERE account_ref=$1::uuid AND request_id=$2::uuid FOR UPDATE",
                    order.account_ref, order.request_id,
                )
                if existing:
                    found = await connection.fetchrow("SELECT * FROM orders WHERE account_ref=$1::uuid AND client_order_id=$2", order.account_ref, existing["client_order_id"])
                    return self._row(found)
                await connection.execute(
                    "INSERT INTO orders(account_ref,client_order_id,origin_request_id,user_id,client_id,symbol,side,order_type,quantity,limit_price,reference_price,estimated_notional,status,version,message,created_at,updated_at) "
                    "VALUES($1::uuid,$2,$3::uuid,$4,$5::uuid,$6,$7,$8,$9,$10::numeric,$11::numeric,$12::numeric,$13,$14,$15,to_timestamp($16),to_timestamp($17))",
                    order.account_ref, order.client_order_id, order.request_id, order.user_id, order.client_id, order.symbol, order.side,
                    order.order_type, order.quantity, Decimal(order.limit_price) if order.limit_price is not None else None, Decimal(order.reference_price), Decimal(order.estimated_notional),
                    order.status, order.version, order.message, order.created_at, order.updated_at,
                )
                await connection.execute(
                    "INSERT INTO idempotency_keys(account_ref,request_id,payload_hash,client_order_id) VALUES($1::uuid,$2::uuid,$3,$4)",
                    order.account_ref, order.request_id, order.payload_hash, order.client_order_id,
                )
                await connection.execute(
                    "INSERT INTO order_events(account_ref,client_order_id,version,status,payload) VALUES($1::uuid,$2,$3,$4,$5::jsonb)",
                    order.account_ref, order.client_order_id, order.version, order.status,
                    json.dumps(order.public(), ensure_ascii=False),
                )
                await connection.execute(
                    "INSERT INTO audit_events(actor_user_id,client_id,action,account_ref,client_order_id,outcome) "
                    "VALUES($1,$2::uuid,'order.submit',$3::uuid,$4,'RECEIVED')",
                    order.user_id, order.client_id, order.account_ref, order.client_order_id,
                )
        return order

    async def remember_request(self, order: ServerOrder, request_id: str, payload_hash: str) -> None:
        try:
            await self.pool.execute(
                "INSERT INTO idempotency_keys(account_ref,request_id,payload_hash,client_order_id) VALUES($1::uuid,$2::uuid,$3,$4)",
                order.account_ref, request_id, payload_hash, order.client_order_id,
            )
        except Exception as exc:
            row = await self.find_request(order.account_ref, request_id)
            if row is None or row[0].client_order_id != order.client_order_id or row[1] != payload_hash:
                if row is not None:
                    raise ValueError("相同 Idempotency-Key 的操作字段不一致") from None
                raise exc

    async def update(self, order: ServerOrder, status: str, *, message: str = "", result: object = None) -> ServerOrder:
        encoded = json.dumps(result, ensure_ascii=False, default=str) if result is not None else None
        row = await self.pool.fetchrow(
            "UPDATE orders SET status=$3, version=version+1, message=CASE WHEN $4='' THEN message ELSE $4 END, "
            "result_json=COALESCE($5::jsonb,result_json), limit_price=$6::numeric, reference_price=$7::numeric, estimated_notional=$8::numeric, pending_action=$9, previous_limit_price=$10, previous_notional=$11, updated_at=now() "
            "WHERE account_ref=$1::uuid AND client_order_id=$2 RETURNING *",
            order.account_ref, order.client_order_id, status, message, encoded, Decimal(order.limit_price) if order.limit_price is not None else None,
            Decimal(order.reference_price), Decimal(order.estimated_notional), order.pending_action, order.previous_limit_price, order.previous_notional,
        )
        updated = self._row(row)
        await self.pool.execute(
            "INSERT INTO order_events(account_ref,client_order_id,version,status,payload) VALUES($1::uuid,$2,$3,$4,$5::jsonb) ON CONFLICT DO NOTHING",
            updated.account_ref, updated.client_order_id, updated.version, updated.status,
            json.dumps(updated.public(), ensure_ascii=False),
        )
        return updated

    async def recent(self, user_id: str, account_ref: str | None, limit: int = 50, before: tuple[float, str] | None = None) -> list[ServerOrder]:
        cursor_time = before[0] if before else None
        cursor_id = before[1] if before else None
        if account_ref:
            rows = await self.pool.fetch(
                "SELECT * FROM orders WHERE user_id=$1 AND account_ref=$2::uuid "
                "AND ($3::double precision IS NULL OR (created_at,client_order_id)<(to_timestamp($3),$4)) "
                "ORDER BY created_at DESC,client_order_id DESC LIMIT $5", user_id, account_ref, cursor_time, cursor_id, max(1, min(limit, 200)),
            )
        else:
            rows = await self.pool.fetch(
                "SELECT * FROM orders WHERE user_id=$1 AND ($2::double precision IS NULL OR "
                "(created_at,client_order_id)<(to_timestamp($2),$3)) ORDER BY created_at DESC,client_order_id DESC LIMIT $4",
                user_id, cursor_time, cursor_id, max(1, min(limit, 200)),
            )
        return [self._row(row) for row in rows]

    async def open_count(self, account_ref: str) -> int:
        return int(await self.pool.fetchval("SELECT count(*) FROM orders WHERE account_ref=$1::uuid AND status=ANY($2::text[])", account_ref, list(ACTIVE_STATUSES)))

    async def daily_notional(self, account_ref: str, since: float) -> Decimal:
        value = await self.pool.fetchval(
            "SELECT COALESCE(sum(estimated_notional),0) FROM orders WHERE account_ref=$1::uuid AND created_at>=to_timestamp($2) AND status<>'REJECTED'",
            account_ref, since,
        )
        return Decimal(value or 0)

    async def unresolved(self) -> list[ServerOrder]:
        rows = await self.pool.fetch(
            "SELECT * FROM orders WHERE status=ANY($1::text[]) ORDER BY created_at", list(ACTIVE_STATUSES)
        )
        return [self._row(row) for row in rows]

    async def audit(self, action: str, order: ServerOrder, outcome: str, reason: str = "") -> None:
        await self.pool.execute(
            "INSERT INTO audit_events(actor_user_id,client_id,action,account_ref,client_order_id,outcome,reason) "
            "VALUES($1,$2::uuid,$3,$4::uuid,$5,$6,$7)",
            order.user_id, order.client_id, action, order.account_ref, order.client_order_id,
            outcome[:32], reason[:200],
        )

    @staticmethod
    def _row(row: Any) -> ServerOrder:
        def epoch(value: Any) -> float:
            return value.timestamp() if isinstance(value, datetime) else float(value or 0)
        return ServerOrder(
            account_ref=str(row["account_ref"]), user_id=str(row["user_id"]), client_id=str(row["client_id"]),
            request_id=str(row["origin_request_id"] or ""), client_order_id=str(row["client_order_id"]), symbol=str(row["symbol"]),
            side=str(row["side"]), order_type=str(row["order_type"]), quantity=int(row["quantity"]),
            limit_price=str(row["limit_price"]) if row["limit_price"] is not None else None,
            reference_price=str(row["reference_price"]), estimated_notional=str(row["estimated_notional"]),
            status=str(row["status"]), version=int(row["version"]), message=str(row["message"] or ""),
            result=row["result_json"], created_at=epoch(row["created_at"]), updated_at=epoch(row["updated_at"]),
            pending_action=str(row["pending_action"] or ""),
            previous_limit_price=row["previous_limit_price"], previous_notional=row["previous_notional"],
        )
