"""Durable command intent journal. Recovery never sends a mutation."""
import json
import os
from pathlib import Path
import sqlite3
import time
import uuid
from contextlib import contextmanager

OPEN = ("PREPARED", "SENDING", "UNCERTAIN", "OPERATION_PENDING")


class BusyError(RuntimeError):
    pass


def encode_body(payload):
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


class Journal:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("""CREATE TABLE IF NOT EXISTS intents (
                request_id TEXT PRIMARY KEY, origin TEXT NOT NULL, client_id TEXT NOT NULL,
                account_ref TEXT NOT NULL, operation TEXT NOT NULL, method TEXT NOT NULL,
                path TEXT NOT NULL, body BLOB NOT NULL, target TEXT NOT NULL,
                phase TEXT NOT NULL, created REAL NOT NULL, error_code TEXT NOT NULL DEFAULT '',
                order_id TEXT NOT NULL DEFAULT '')""")
            db.execute("UPDATE intents SET phase='UNCERTAIN', error_code='RESTART_RECOVERY' "
                       "WHERE phase IN ('PREPARED','SENDING')")

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA synchronous=FULL")
        try:
            with db:
                yield db
        finally:
            db.close()

    def pending(self, origin=None, client_id=None):
        with self.connection() as db:
            rows = db.execute("SELECT * FROM intents WHERE phase IN (?,?,?,?) ORDER BY created", OPEN).fetchall()
        return [dict(row) for row in rows if origin is None or
                (row["origin"] == origin and row["client_id"] == client_id)]

    def reserve(self, origin, client_id, account_ref, operation, method, path, payload, target=""):
        body = encode_body(payload)
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute("SELECT * FROM intents WHERE origin=? AND client_id=? AND account_ref=? "
                                  "AND phase IN (?,?,?,?)", (origin, client_id, account_ref, *OPEN)).fetchall()
            if operation in {"submit", "replace"} and any(row["operation"] in {"submit", "replace"} for row in existing):
                raise BusyError("该账户有待确认下单/改单，请先查询原请求")
            if target and any(row["target"] == target for row in existing):
                raise BusyError("该订单已有待确认操作，请先查询原请求")
            request_id = str(uuid.uuid4())
            db.execute("INSERT INTO intents VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       (request_id, origin, client_id, account_ref, operation, method, path,
                        body, target, "PREPARED", time.time(), "", ""))
        return self.get(request_id)

    def get(self, request_id):
        with self.connection() as db:
            row = db.execute("SELECT * FROM intents WHERE request_id=?", (request_id,)).fetchone()
        return dict(row) if row else None

    def begin_send(self, request_id):
        with self.connection() as db:
            result = db.execute("UPDATE intents SET phase='SENDING' WHERE request_id=? AND phase='PREPARED'",
                                (request_id,))
        return result.rowcount == 1

    def update(self, request_id, phase, error_code="", order_id=""):
        with self.connection() as db:
            db.execute("UPDATE intents SET phase=?, error_code=?, order_id=CASE WHEN ?<>'' THEN ? ELSE order_id END "
                       "WHERE request_id=?", (phase, error_code, order_id, order_id, request_id))


class ConfigStore:
    def __init__(self, directory, journal):
        self.path = Path(directory) / "settings.json"
        self.journal = journal

    def load(self):
        if not self.path.exists():
            return {"origin": "", "client_id": ""}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return {"origin": str(data["origin"]), "client_id": str(data["client_id"])}
        except Exception:
            raise RuntimeError("配置文件损坏；待确认请求记录仍保留") from None

    def save(self, origin, client_id):
        # Validate origin without needing to load a private key.
        from urllib.parse import urlsplit
        parsed = urlsplit(origin)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or
                parsed.query or parsed.fragment or parsed.path not in {"", "/"}):
            raise ValueError("服务器地址必须是 HTTPS origin，不含路径、查询或用户名")
        uuid.UUID(client_id)
        origin = origin.rstrip("/")
        if any((item["origin"], item["client_id"]) != (origin, client_id) for item in self.journal.pending()):
            raise BusyError("有待确认请求，不能更换服务器或 clientId；请先查询原请求")
        temporary = self.path.with_suffix(".tmp")
        with temporary.open("w", encoding="utf-8") as stream:
            json.dump({"origin": origin, "client_id": client_id}, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, self.path)
