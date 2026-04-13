"""SQLite-backed cache with TTL support for provider responses.

Dataclass instances are round-tripped via type tags so that cache.get()
returns the same type that was stored, not a plain dict.
"""

import dataclasses
import importlib
import json
import logging
import os
import sqlite3
import time
from typing import Any, Optional

logger = logging.getLogger(__name__)

_DEFAULT_DB_PATH = os.path.join(os.path.dirname(__file__), "..", "..", ".cache", "provider_cache.db")

# Resolved-type cache: "module.ClassName" -> class
_TYPE_CACHE: dict[str, type] = {}


class Cache:
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
            "CREATE TABLE IF NOT EXISTS cache ("
            "key TEXT PRIMARY KEY, value TEXT NOT NULL, expires_at REAL NOT NULL)"
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_expires ON cache(expires_at)")
        conn.commit()

    async def get(self, key: str) -> Optional[Any]:
        try:
            conn = self._get_conn()
            row = conn.execute(
                "SELECT value, expires_at FROM cache WHERE key = ?", (key,)
            ).fetchone()
            if row is None:
                return None
            value_json, expires_at = row
            if time.time() > expires_at:
                conn.execute("DELETE FROM cache WHERE key = ?", (key,))
                conn.commit()
                return None
            return _deserialize(json.loads(value_json))
        except Exception as e:
            logger.debug("Cache get(%s) error: %s", key, e)
            return None

    async def set(self, key: str, value: Any, ttl_seconds: int) -> None:
        try:
            conn = self._get_conn()
            conn.execute(
                "INSERT OR REPLACE INTO cache(key, value, expires_at) VALUES (?, ?, ?)",
                (key, json.dumps(_serialize(value)), time.time() + ttl_seconds),
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
        try:
            conn = self._get_conn()
            cursor = conn.execute("DELETE FROM cache WHERE expires_at < ?", (time.time(),))
            conn.commit()
            return cursor.rowcount
        except Exception as e:
            logger.debug("Cache clear_expired error: %s", e)
            return 0

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None


def _serialize(obj: Any) -> Any:
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        tag = f"{type(obj).__module__}.{type(obj).__qualname__}"
        fields = {f.name: _serialize(getattr(obj, f.name)) for f in dataclasses.fields(obj)}
        return {"__type__": tag, **fields}
    if isinstance(obj, list):
        return [_serialize(i) for i in obj]
    if isinstance(obj, dict):
        return {k: _serialize(v) for k, v in obj.items()}
    if hasattr(obj, "isoformat"):
        return {"__datetime__": obj.isoformat()}
    return obj


def _deserialize(obj: Any) -> Any:
    if isinstance(obj, dict):
        if "__datetime__" in obj:
            from datetime import datetime, timezone
            dt = datetime.fromisoformat(obj["__datetime__"])
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        if "__type__" in obj:
            cls = _resolve_type(obj["__type__"])
            fields = {k: _deserialize(v) for k, v in obj.items() if k != "__type__"}
            if cls is not None:
                try:
                    return cls(**fields)
                except Exception as e:
                    logger.debug("Cache: failed to reconstruct %s: %s", obj["__type__"], e)
            return fields
        return {k: _deserialize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_deserialize(i) for i in obj]
    return obj


def _resolve_type(type_tag: str) -> Optional[type]:
    if type_tag in _TYPE_CACHE:
        return _TYPE_CACHE[type_tag]
    try:
        module_path, class_name = type_tag.rsplit(".", 1)
        cls = getattr(importlib.import_module(module_path), class_name)
        _TYPE_CACHE[type_tag] = cls
        return cls
    except Exception:
        return None
