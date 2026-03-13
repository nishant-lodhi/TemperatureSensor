"""Client registry — loads clients.yaml, resolves env vars, provides per-client config.

The registry is loaded once at import time and cached. Each client entry
contains DB credentials, data-source preference, isolation mode, and
Parquet/alert settings. Environment variable placeholders (``${VAR}``) in
string values are resolved at load time.

Usage:
    from app.data.client_registry import get_client_config, list_clients

    cfg = get_client_config("14")
    # cfg.db_host, cfg.db_user, cfg.isolation, ...
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_ENV_RE = re.compile(r"\$\{(\w+)}")


def _resolve_env(value: str) -> str:
    """Replace ``${VAR}`` placeholders with environment variable values."""
    def _sub(m: re.Match) -> str:
        return os.environ.get(m.group(1), "")
    return _ENV_RE.sub(_sub, value) if isinstance(value, str) else value


@dataclass(frozen=True)
class ClientConfig:
    """Immutable configuration for a single client/tenant."""
    client_id: str
    name: str
    isolation: str = "shared"
    data_source: str = "mysql"

    db_host: str = "localhost"
    db_port: int = 3306
    db_user: str = "root"
    db_password: str = ""
    db_database: str = ""
    db_connect_timeout: int = 5
    db_read_timeout: int = 15
    db_write_timeout: int = 10

    parquet_bucket: str = ""
    parquet_prefix: str = "sensor-data/"

    alerts_table: str = ""

    @property
    def needs_client_filter(self) -> bool:
        """True when the client shares a DB and queries must filter by client_id."""
        return self.isolation == "shared"


# ── Registry (loaded once) ──────────────────────────────────────────────────

_registry: dict[str, ClientConfig] = {}
_loaded = False


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge *override* into a copy of *base*."""
    merged = {**base}
    for k, v in override.items():
        if k in merged and isinstance(merged[k], dict) and isinstance(v, dict):
            merged[k] = _deep_merge(merged[k], v)
        else:
            merged[k] = v
    return merged


def _load_yaml_file(path: Path) -> dict:
    """Load YAML, falling back to a safe subset parser if PyYAML is absent."""
    try:
        import yaml
        with open(path) as f:
            return yaml.safe_load(f) or {}
    except ImportError:
        import json
        text = path.read_text()
        text = re.sub(r"#.*$", "", text, flags=re.MULTILINE)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            logger.warning("Could not parse %s (install PyYAML for YAML support)", path)
            return {}


def load_registry(path: Optional[str] = None) -> dict[str, ClientConfig]:
    """Parse ``clients.yaml`` and return {client_id: ClientConfig}."""
    global _registry, _loaded

    if path is None:
        candidates = [
            Path(os.environ.get("CLIENTS_YAML", "")),
            Path(__file__).resolve().parents[3] / "clients.yaml",
            Path.cwd().parent / "clients.yaml",
            Path.cwd() / "clients.yaml",
        ]
        for p in candidates:
            if p.is_file():
                path = str(p)
                break

    if not path or not Path(path).is_file():
        logger.info("No clients.yaml found — using env-var based defaults")
        _loaded = True
        return _registry

    data = _load_yaml_file(Path(path))
    defaults = data.get("defaults", {})
    clients_raw = data.get("clients", {})

    for cid, client_data in clients_raw.items():
        cid = str(cid)
        merged = _deep_merge(defaults, client_data)
        db = merged.get("db", {})
        pq = merged.get("parquet", {})

        _registry[cid] = ClientConfig(
            client_id=cid,
            name=_resolve_env(str(merged.get("name", cid))),
            isolation=merged.get("isolation", defaults.get("isolation", "shared")),
            data_source=merged.get("data_source", defaults.get("data_source", "mysql")),
            db_host=_resolve_env(str(db.get("host", "localhost"))),
            db_port=int(db.get("port", 3306)),
            db_user=_resolve_env(str(db.get("user", "root"))),
            db_password=_resolve_env(str(db.get("password", ""))),
            db_database=_resolve_env(str(db.get("database", ""))),
            db_connect_timeout=int(db.get("connect_timeout", 5)),
            db_read_timeout=int(db.get("read_timeout", 15)),
            db_write_timeout=int(db.get("write_timeout", 10)),
            parquet_bucket=_resolve_env(str(pq.get("bucket", ""))),
            parquet_prefix=_resolve_env(str(pq.get("prefix", "sensor-data/"))),
            alerts_table=_resolve_env(str(merged.get("alerts_table", ""))),
        )

    _loaded = True
    logger.info("Loaded %d client(s) from %s", len(_registry), path)
    return _registry


def get_client_config(client_id: str) -> Optional[ClientConfig]:
    """Return config for *client_id*, or None if not found.

    Falls back to an auto-generated config from env vars if the registry
    is empty or the client_id is not registered (backward compatibility).
    """
    if not _loaded:
        load_registry()

    if client_id in _registry:
        return _registry[client_id]

    if client_id in ("default", None, ""):
        return _default_config(client_id or "default")

    if _registry:
        return None

    return _default_config(client_id)


def _default_config(client_id: str) -> ClientConfig:
    """Build a ClientConfig from environment variables (legacy / local mode)."""
    from app import config as cfg
    return ClientConfig(
        client_id=client_id,
        name=os.environ.get("CLIENT_NAME", "Local Facility"),
        isolation="shared" if client_id != "default" else "shared",
        data_source=cfg.DATA_SOURCE,
        db_host=cfg.MYSQL_HOST,
        db_port=cfg.MYSQL_PORT,
        db_user=cfg.MYSQL_USER,
        db_password=cfg.MYSQL_PASSWORD,
        db_database=cfg.MYSQL_DATABASE,
        db_connect_timeout=cfg.MYSQL_CONNECT_TIMEOUT,
        db_read_timeout=cfg.MYSQL_READ_TIMEOUT,
        db_write_timeout=cfg.MYSQL_WRITE_TIMEOUT,
        parquet_bucket=cfg.PARQUET_BUCKET,
        parquet_prefix=cfg.PARQUET_PREFIX,
        alerts_table=cfg.ALERTS_TABLE,
    )


def list_clients() -> list[ClientConfig]:
    """Return all registered clients."""
    if not _loaded:
        load_registry()
    return list(_registry.values())
