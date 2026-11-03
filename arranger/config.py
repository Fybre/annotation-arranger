"""Explicit configuration with deterministic .env discovery for source and frozen apps."""

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import dotenv_values


def application_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    source = Path(__file__).resolve().parents[1]
    return source if (source / "pyproject.toml").is_file() else Path.cwd()


@dataclass(frozen=True)
class Settings:
    base_url: str
    tenant: str = ""
    backup_dir: Path | None = None
    max_bytes: int = 20 * 1024 * 1024
    deadline_seconds: int = 120
    debug_logging: bool = False
    host: str = "127.0.0.1"
    port: int = 8765

    @classmethod
    def from_env(cls, env_file=None, overrides=None):
        path = Path(env_file).resolve() if env_file is not None else application_dir() / ".env"
        if env_file is not None and not path.is_file():
            raise ValueError(f"Environment file does not exist: {path}")
        values = {
            **(
                {k: v for k, v in dotenv_values(path).items() if v is not None}
                if path.is_file()
                else {}
            ),
            **os.environ,
            **{k: str(v) for k, v in (overrides or {}).items() if v is not None},
        }
        url = values.get("THEREFORE_BASE_URL", "").strip().rstrip("/")
        if not url:
            raise ValueError("Set THEREFORE_BASE_URL in .env, the environment, or --base-url.")
        parsed = urlsplit(url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("THEREFORE_BASE_URL must use HTTPS and contain no credentials.")
        if parsed.query or parsed.fragment:
            raise ValueError("THEREFORE_BASE_URL must not contain a query or fragment.")
        tenant = values.get("THEREFORE_TENANT", "").strip()
        if not tenant and parsed.hostname.endswith(".thereforeonline.com"):
            tenant = parsed.hostname.split(".")[0]
        enabled = values.get("BACKUP_ENABLED", "false").strip().lower()
        if enabled not in ("true", "false", "1", "0", "yes", "no", "on", "off"):
            raise ValueError("BACKUP_ENABLED must be true or false.")
        debug = values.get("DEBUG_LOGGING", "false").strip().lower()
        if debug not in ("true", "false", "1", "0", "yes", "no", "on", "off"):
            raise ValueError("DEBUG_LOGGING must be true or false.")
        backup_dir = None
        if enabled in ("true", "1", "yes", "on"):
            backup_dir = Path(values.get("BACKUP_DIR", "var/backups").strip() or "var/backups")
            if not backup_dir.is_absolute():
                backup_dir = path.parent / backup_dir
            backup_dir = backup_dir.resolve()
        try:
            port = int(values.get("PORT", "8765"))
            timeout = int(values.get("PROCESSING_TIMEOUT_SECONDS", "120"))
        except ValueError as exc:
            raise ValueError("PORT and PROCESSING_TIMEOUT_SECONDS must be integers.") from exc
        if not 1 <= port <= 65535 or timeout <= 0:
            raise ValueError(
                "PORT must be 1–65535 and PROCESSING_TIMEOUT_SECONDS must be positive."
            )
        return cls(
            url,
            tenant,
            backup_dir,
            deadline_seconds=timeout,
            debug_logging=debug in ("true", "1", "yes", "on"),
            host=values.get("HOST", "127.0.0.1"),
            port=port,
        )
