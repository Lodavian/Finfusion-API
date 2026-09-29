#!/usr/bin/env python3
from __future__ import annotations

import base64
import json
import os
import re
import shlex
import subprocess
import tempfile
from urllib.parse import urlparse
from decimal import Decimal
from pathlib import Path


FQDN = re.compile(r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")
ROOT = Path("/etc/finfusion")


def required(config: dict, name: str) -> str:
    value = str(config.get(name) or "").strip()
    if not value:
        raise ValueError(f"missing {name}")
    return value


def main() -> int:
    if os.geteuid() != 0:
        raise SystemExit("node_configure.py must run as root")
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("config", type=Path)
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise ValueError("configuration must be a JSON object")
    environment = str(config.get("environment", "SANDBOX")).upper()
    if environment not in {"SANDBOX", "LIVE"}:
        raise ValueError("environment must be SANDBOX or LIVE")
    if environment == "LIVE" and config.get("liveAllowed") is not True:
        raise ValueError("LIVE requires explicit liveAllowed=true")
    marker = ROOT / "server.env"
    if marker.exists() and f"FINFUSION_ENVIRONMENT={environment}\n" not in marker.read_text():
        raise ValueError("Use a separate WSL node for another environment; in-place environment switching is forbidden")
    if marker.exists() and not config.get("accountMasterKey"):
        raise ValueError("Reconfiguration requires the existing accountMasterKey; never silently rotate it")
    slug = environment.lower()
    if urlparse(required(config, "databaseDsn")).path != f"/finfusion_{slug}":
        raise ValueError("databaseDsn must name finfusion_" + slug)
    domains = [required(config, key).lower() for key in ("apiDomain", "authDomain", "adminDomain")]
    if len(set(domains)) != 3 or any(not FQDN.fullmatch(item) for item in domains):
        raise ValueError("api/auth/admin domains must be three distinct FQDNs")
    backup_recipient = required(config, "backupRecipient")
    if not re.fullmatch(r"age1[023456789acdefghjklmnpqrstuvwxyz]{58}", backup_recipient):
        raise ValueError("backupRecipient must be an age X25519 recipient whose identity is kept off-node")
    limits = config.get("riskLimits")
    if not isinstance(limits, dict):
        raise ValueError("missing riskLimits")
    integer_limits = {"maxOrderQty", "maxMarketQty", "maxOpenOrders"}
    for key in ("maxOrderQty", "maxOrderValue", "maxMarketQty", "maxMarketEstimatedValue", "maxDailyGrossNotional", "maxOpenOrders"):
        value = Decimal(str(limits.get(key) or ""))
        if not value.is_finite() or value <= 0 or (key in integer_limits and value != value.to_integral_value()):
            raise ValueError(f"invalid risk limit {key}")
    quote_age = Decimal(str(config.get("quoteStaleSeconds", 3)))
    if not quote_age.is_finite() or quote_age <= 0 or quote_age > 60:
        raise ValueError("quoteStaleSeconds must be within (0, 60]")

    secrets = {
        "environment": environment,
        "webull_app_key": required(config, "webullAppKey"),
        "webull_app_secret": required(config, "webullAppSecret"),
        "database_dsn": required(config, "databaseDsn"),
        "casdoor_data_source": required(config, "casdoorDataSourceName"),
        "account_master_key": str(config.get("accountMasterKey") or base64.urlsafe_b64encode(os.urandom(32)).decode().rstrip("=")),
        "casdoor_client_secret": required(config, "casdoorClientSecret"),
        "tunnel_token": required(config, "tunnelToken"),
    }
    if any(any(character in value for character in "\r\n\x00") for value in secrets.values()):
        raise ValueError("secret values must be single-line strings")
    if any("[REDACTED]" in value or "replace-me" in value.lower() for value in secrets.values()):
        raise ValueError("replace every configuration placeholder before sealing")
    ROOT.mkdir(mode=0o750, parents=True, exist_ok=True)
    server_values = {
        "FINFUSION_ENVIRONMENT": environment,
        "FINFUSION_SECRET_DIR": f"/run/finfusion/secrets/{slug}",
        "FINFUSION_PORT": "8080",
        "FINFUSION_BIND_HOST": "127.0.0.1",
        "FINFUSION_NODE_STATE_FILE": "/run/finfusion/node-state.json",
        "FINFUSION_NODE_STATE_STALE_SECONDS": "15",
        "FINFUSION_WEBULL_APP_KEY_FILE": "/run/finfusion/secrets/webull_app_key",
        "FINFUSION_WEBULL_APP_SECRET_FILE": "/run/finfusion/secrets/webull_app_secret",
        "FINFUSION_DATABASE_DSN_FILE": "/run/finfusion/secrets/database_dsn",
        "FINFUSION_ACCOUNT_KEY_FILE": "/run/finfusion/secrets/account_master_key",
        "FINFUSION_CASDOOR_CLIENT_SECRET_FILE": "/run/finfusion/secrets/casdoor_client_secret",
        "FINFUSION_TOKEN_DIR": "/var/lib/finfusion/webull_tokens",
        "FINFUSION_ADMIN_STATIC_DIR": "/opt/finfusion/current/server_admin",
        "FINFUSION_LIVE_ALLOWED": "true" if environment == "LIVE" else "false",
        "FINFUSION_CASDOOR_URL": "http://127.0.0.1:8000",
        "FINFUSION_CASDOOR_ISSUER": f"https://{domains[1]}",
        "FINFUSION_CASDOOR_JWKS_URL": "http://127.0.0.1:8000/api/certs",
        "FINFUSION_CASDOOR_CLIENT_ID": required(config, "casdoorClientId"),
        "FINFUSION_CASDOOR_ORGANIZATION": required(config, "casdoorOrganization"),
        "FINFUSION_CASDOOR_APPLICATION": required(config, "casdoorApplication"),
        "FINFUSION_CASDOOR_AUTHORIZATION_ENDPOINT": f"https://{domains[1]}/login/oauth/authorize",
        "FINFUSION_CASDOOR_TOKEN_ENDPOINT": f"https://{domains[1]}/api/login/oauth/access_token",
        "FINFUSION_ADMIN_REDIRECT_URI": f"https://{domains[2]}/admin/",
        "FINFUSION_MAX_ORDER_QTY": str(limits["maxOrderQty"]),
        "FINFUSION_MAX_ORDER_VALUE": str(limits["maxOrderValue"]),
        "FINFUSION_MAX_MARKET_QTY": str(limits["maxMarketQty"]),
        "FINFUSION_MAX_MARKET_ESTIMATED_VALUE": str(limits["maxMarketEstimatedValue"]),
        "FINFUSION_MAX_DAILY_GROSS_NOTIONAL": str(limits["maxDailyGrossNotional"]),
        "FINFUSION_MAX_OPEN_ORDERS": str(limits["maxOpenOrders"]),
        "FINFUSION_QUOTE_STALE_SECONDS": str(config.get("quoteStaleSeconds", 3)),
    }
    for key in ("FINFUSION_WEBULL_APP_KEY_FILE", "FINFUSION_WEBULL_APP_SECRET_FILE", "FINFUSION_DATABASE_DSN_FILE", "FINFUSION_ACCOUNT_KEY_FILE", "FINFUSION_CASDOOR_CLIENT_SECRET_FILE"):
        server_values[key] = server_values[key].replace("/secrets/", f"/secrets/{slug}/")
    server_values["FINFUSION_TOKEN_DIR"] = f"/var/lib/finfusion/webull_tokens/{slug}"
    if any(any(character in value for character in "\r\n\x00") for value in server_values.values()):
        raise ValueError("environment values must be single-line strings")
    if any("[REDACTED]" in value or "replace-me" in value.lower() for value in server_values.values()):
        raise ValueError("replace every configuration placeholder before sealing")
    env_path = ROOT / "server.env"
    env_path.write_text("".join(f"{key}={value}\n" for key, value in server_values.items()), encoding="utf-8")
    service_gid = __import__("grp").getgrnam("finfusion").gr_gid
    os.chown(env_path, 0, service_gid)
    os.chmod(env_path, 0o640)
    (ROOT / "domains.json").write_text(json.dumps({"api": domains[0], "auth": domains[1], "admin": domains[2]}, indent=2) + "\n", encoding="utf-8")
    os.chmod(ROOT / "domains.json", 0o640)
    os.chown(ROOT / "domains.json", 0, service_gid)
    (ROOT / "backup-recipient.txt").write_text(backup_recipient + "\n", encoding="ascii")
    os.chown(ROOT / "backup-recipient.txt", 0, 0)
    os.chmod(ROOT / "backup-recipient.txt", 0o644)
    database = urlparse(secrets["database_dsn"])
    if database.scheme not in {"postgres", "postgresql"} or database.hostname not in {"127.0.0.1", "localhost"}:
        raise ValueError("databaseDsn must use local PostgreSQL")
    if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", database.username or "") or not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", database.path.lstrip("/")):
        raise ValueError("databaseDsn user/database names are invalid")
    if not database.password:
        raise ValueError("databaseDsn must contain a password")
    def provision(role: str, dbname: str, password: str) -> None:
        if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", role) or not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", dbname):
            raise ValueError("PostgreSQL role/database name is invalid")
        quote = lambda value: value.replace("'", "''")
        sql = (
            f"DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='{quote(role)}') THEN CREATE ROLE {role} LOGIN; END IF; END $$;\n"
            f"ALTER ROLE {role} PASSWORD '{quote(password)}';\n"
            f"SELECT 'CREATE DATABASE {dbname} OWNER {role}' WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname='{quote(dbname)}')\\gexec\n"
        )
        subprocess.run(["sudo", "-u", "postgres", "psql", "--no-psqlrc", "--set", "ON_ERROR_STOP=1"], input=sql, text=True, check=True)
    provision(database.username or "", database.path.lstrip("/"), database.password)
    casdoor_parts = dict(item.split("=", 1) for item in shlex.split(secrets["casdoor_data_source"]) if "=" in item)
    if casdoor_parts.get("host") not in {"127.0.0.1", "localhost"} or not casdoor_parts.get("password"):
        raise ValueError("casdoorDataSourceName must contain a local host and password")
    provision(casdoor_parts.get("user", ""), casdoor_parts.get("dbname", ""), casdoor_parts["password"])
    with tempfile.NamedTemporaryFile("w", dir="/run", delete=False, encoding="utf-8") as stream:
        json.dump(secrets, stream)
        clear = Path(stream.name)
    os.chmod(clear, 0o600)
    try:
        subprocess.run(["/opt/finfusion/bin/vault.py", "seal", str(clear)], check=True)
    finally:
        clear.unlink(missing_ok=True)
    subprocess.run(["/opt/finfusion/bin/node_state.py", "deactivate", "--reason", "configuration-changed"], check=True)
    print("configuration sealed; node remains inactive")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
