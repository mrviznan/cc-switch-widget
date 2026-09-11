"""Read CC Switch usage data without modifying the CC Switch database."""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from urllib.parse import quote


SUPPORTED_APPS = ("codex", "claude")
DEFAULT_DB_PATH = Path.home() / ".cc-switch" / "cc-switch.db"


@dataclass(frozen=True)
class Provider:
    app_type: str
    provider_id: str
    name: str
    settings_config: dict[str, Any]
    meta: dict[str, Any]

    @property
    def usage_script(self) -> dict[str, Any] | None:
        script = self.meta.get("usage_script")
        return script if isinstance(script, dict) and script.get("enabled") else None


@dataclass(frozen=True)
class SessionUsage:
    app_type: str
    session_id: str
    request_count: int
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_creation_tokens: int
    total_cost_usd: Decimal
    first_at: int
    last_at: int

    @property
    def last_datetime(self) -> datetime:
        timestamp = self.last_at / 1000 if self.last_at > 10**12 else self.last_at
        return datetime.fromtimestamp(timestamp).astimezone()


@dataclass(frozen=True)
class Snapshot:
    providers: dict[str, Provider]
    latest_session: SessionUsage | None
    error: str | None = None


def default_database_path() -> Path:
    configured = os.environ.get("CCSWITCH_DB_PATH", "").strip()
    return Path(configured).expanduser() if configured else DEFAULT_DB_PATH


def find_node() -> str | None:
    configured = os.environ.get("CCSWITCH_NODE_PATH", "").strip()
    candidates = [configured] if configured else []
    bundled_root = getattr(sys, "_MEIPASS", "")
    if bundled_root:
        candidates.append(str(Path(bundled_root) / "runtime" / "node.exe"))
        candidates.append(str(Path(bundled_root) / "node.exe"))
    candidates.extend(
        [
            shutil.which("node") or "",
            r"D:\study\nodejs\node.exe",
            r"C:\Program Files\nodejs\node.exe",
        ]
    )
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    return None


def _parse_json(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value or "0"))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _db_uri(path: Path) -> str:
    # SQLite's immutable read-only URI prevents accidental writes by this app.
    return f"file:{quote(path.resolve().as_posix(), safe='/:')}?mode=ro"


def _connect(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(_db_uri(path), uri=True, timeout=1)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    return connection


def _read_current_providers(connection: sqlite3.Connection) -> dict[str, Provider]:
    providers: dict[str, Provider] = {}
    rows = connection.execute(
        """
        SELECT id, app_type, name, settings_config, meta
        FROM providers
        WHERE is_current = 1 AND app_type IN ('codex', 'claude')
        """
    ).fetchall()
    for row in rows:
        providers[row["app_type"]] = Provider(
            app_type=row["app_type"],
            provider_id=row["id"],
            name=row["name"],
            settings_config=_parse_json(row["settings_config"]),
            meta=_parse_json(row["meta"]),
        )
    return providers


def _read_latest_session(connection: sqlite3.Connection) -> SessionUsage | None:
    latest = connection.execute(
        """
        SELECT app_type, session_id, MAX(created_at) AS last_at
        FROM proxy_request_logs
        WHERE app_type IN ('codex', 'claude')
          AND session_id IS NOT NULL
          AND TRIM(session_id) <> ''
        GROUP BY app_type, session_id
        ORDER BY last_at DESC
        LIMIT 1
        """
    ).fetchone()
    if latest is None:
        return None

    row = connection.execute(
        """
        SELECT
          COUNT(*) AS request_count,
          COALESCE(SUM(input_tokens), 0) AS input_tokens,
          COALESCE(SUM(output_tokens), 0) AS output_tokens,
          COALESCE(SUM(cache_read_tokens), 0) AS cache_read_tokens,
          COALESCE(SUM(cache_creation_tokens), 0) AS cache_creation_tokens,
          MIN(created_at) AS first_at,
          MAX(created_at) AS last_at
        FROM proxy_request_logs
        WHERE app_type = ? AND session_id = ?
        """,
        (latest["app_type"], latest["session_id"]),
    ).fetchone()
    cost_row = connection.execute(
        """
        SELECT total_cost_usd
        FROM proxy_request_logs
        WHERE app_type = ? AND session_id = ?
        """,
        (latest["app_type"], latest["session_id"]),
    ).fetchall()
    total_cost = sum((_decimal(item["total_cost_usd"]) for item in cost_row), Decimal("0"))
    return SessionUsage(
        app_type=latest["app_type"],
        session_id=latest["session_id"],
        request_count=int(row["request_count"] or 0),
        input_tokens=int(row["input_tokens"] or 0),
        output_tokens=int(row["output_tokens"] or 0),
        cache_read_tokens=int(row["cache_read_tokens"] or 0),
        cache_creation_tokens=int(row["cache_creation_tokens"] or 0),
        total_cost_usd=total_cost,
        first_at=int(row["first_at"] or 0),
        last_at=int(row["last_at"] or 0),
    )


def read_snapshot(database_path: str | Path | None = None) -> Snapshot:
    path = Path(database_path).expanduser() if database_path else default_database_path()
    if not path.exists():
        return Snapshot({}, None, f"未找到 CC Switch 数据库：{path}")
    connection: sqlite3.Connection | None = None
    try:
        connection = _connect(path)
        return Snapshot(_read_current_providers(connection), _read_latest_session(connection))
    except (OSError, sqlite3.Error) as exc:
        return Snapshot({}, None, f"读取 CC Switch 数据失败：{exc}")
    finally:
        if connection is not None:
            connection.close()
