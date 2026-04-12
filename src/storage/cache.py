"""SQLite-backed cache with TTL support for provider responses."""

import json
import logging
import os
import sqlite3
import time
from typing import Any, Optional

logger = logging.getLogger(__name__)

_DEFAULT_DB_PATH = os.path.join(os.path.dirname(__file__), "..", "..", ".cache", "provider_cache.db")


class Cache:
    """
    Synchronous SQLite cache wrapped in async interface.

    Schema:
        key TEXT PRIMARY KEY
        value TEXT (JSON-serialised)
        expires_at REAL (unix timestamp)
    """

    def __init__(self, db_path: Optional[str] = None):
        self._db_path = db_path or _DEFAULT_DB_PATH
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        self._conn: Optional[sqlite3.Connection] = None
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        return self._conn

    def _init_db(self) -> None:
        conn = self._get_conn()
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS cache (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                expires_at REAL NOT NULL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_expires ON cache(expires_at)")
        conn.commit()

    async def get(self, key: str) -> Optional[Any]:
        """Return cached value or None if expired / not found."""
        try:
            conn = self._get_conn()
            cursor = conn.execute(
                "SELECT value, expires_at FROM cache WHERE key = ?", (key,)
            )
            row = cursor.fetchone()
            if row is None:
                return None
            value_json, expires_at = row
            if time.time() > expires_at:
                conn.execute("DELETE FROM cache WHERE key = ?", (key,))
                conn.commit()
                return None
            return json.loads(value_json)
        except Exception as e:
            logger.debug("Cache get(%s) error: %s", key, e)
            return None

    async def set(self, key: str, value: Any, ttl_seconds: int) -> None:
        """Store value with TTL. Value must be JSON-serialisable."""
        try:
            value_json = _safe_json_dumps(value)
            expires_at = time.time() + ttl_seconds
            conn = self._get_conn()
            conn.execute(
                "INSERT OR REPLACE INTO cache(key, value, expires_at) VALUES (?, ?, ?)",
                (key, value_json, expires_at),
            )
            conn.commit()
        except Exception as e:
            logger.debug("Cache set(%s) error: %s", key, e)

    async def delete(self, key: str) -> None:
        try:
            conn = self._get_conn()
            conn.execute("DELETE FROM cache WHERE key = ?", (key,))
            conn.commit()
        except Exception as e:
            logger.debug("Cache delete(%s) error: %s", key, e)

    async def clear_expired(self) -> int:
        """Delete all expired entries. Returns count removed."""
        try:
            conn = self._get_conn()
            cursor = conn.execute(
                "DELETE FROM cache WHERE expires_at < ?", (time.time(),)
            )
            conn.commit()
            return cursor.rowcount
        except Exception as e:
            logger.debug("Cache clear_expired error: %s", e)
            return 0

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None


def _safe_json_dumps(obj: Any) -> str:
    """JSON-serialise with fallback for datetime and dataclass objects."""
    import dataclasses

    def default(o):
        if dataclasses.is_dataclass(o) and not isinstance(o, type):
            return dataclasses.asdict(o)
        if hasattr(o, "isoformat"):
            return o.isoformat()
        if hasattr(o, "__dict__"):
            return o.__dict__
        raise TypeError(f"Object of type {type(o)} is not JSON serializable")

    return json.dumps(obj, default=default)
