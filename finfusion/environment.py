from dataclasses import dataclass
from pathlib import PurePosixPath as Path
from urllib.parse import urlsplit
from typing import Mapping


@dataclass(frozen=True)
class Environment:
    name: str
    api_host: str
    data_host: str
    events_host: str
    token_dir: Path
    secret_dir: Path

    @classmethod
    def load(cls, env: Mapping[str, str]) -> "Environment":
        name = env.get("FINFUSION_ENVIRONMENT", "SANDBOX").upper()
        if name not in {"SANDBOX", "LIVE"}:
            raise ValueError("FINFUSION_ENVIRONMENT 必须是 SANDBOX 或 LIVE")
        if name == "LIVE" and env.get("FINFUSION_LIVE_ALLOWED", "false").lower() != "true":
            raise ValueError("LIVE 必须显式允许")
        suffix = "sandbox.webull.hk" if name == "SANDBOX" else "webull.hk"
        slug = name.lower()
        token = Path(env.get("FINFUSION_TOKEN_DIR", f"/var/lib/finfusion/webull_tokens/{slug}"))
        secrets = Path(env.get("FINFUSION_SECRET_DIR", f"/run/finfusion/secrets/{slug}"))
        for path in (token, secrets):
            if not path.is_absolute() or slug not in path.parts or ".." in path.parts:
                raise ValueError("令牌及密钥目录必须为包含环境名称的绝对路径")
        return cls(name, f"api.{suffix}", f"data-api.{suffix}", f"events-api.{suffix}", token, secrets)

    def validate_dsn(self, dsn: str) -> None:
        parsed = urlsplit(dsn)
        if parsed.scheme not in {"postgres", "postgresql"} or parsed.path != f"/finfusion_{self.name.lower()}":
            raise ValueError("必须使用 finfusion_sandbox 或 finfusion_live 对应环境的独立数据库")
