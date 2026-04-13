"""SQLite-backed cache with TTL support for provider responses.

Values are stored as JSON. Dataclass instances are round-tripped via a type
registry so that `cache.get(key)` returns the same type that was stored, not
a plain dict.  Any type that should survive a cache round-trip must be
registered with `register_type`.
"""

import dataclasses
import importlib
import json
import logging
import os
import sqlite3
import time
from typing import Any, Optional, Type

logger = logging.getLogger(__name__)

_DEFAULT_DB_PATH = os.path.join(os.path.dirname(__file__), "..", "..", ".cache", "provider_cache.db")

# Registry: qualified name → class (populated lazily via register_type)
_TYPE_REGISTRY: dict[str, type] = {}


def register_type(cls: type) -> type:
    """Register a dataclass (or plain class) for cache round-tripping."""
    _TYPE_REGISTRY[f"{cls.__module__}.{cls.__qualname__}"] = cls
    return cls




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
        """Return cached value or None if expired / not found.

        Dataclass values stored via set() are reconstructed to their original
        type using the type registry, so callers always get the same type back.
        """
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
            raw = json.loads(value_json)
            return _deserialize(raw)
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


def _serialize(obj: Any) -> Any:
    """Recursively convert to a JSON-compatible structure, tagging dataclasses."""
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        tag = f"{type(obj).__module__}.{type(obj).__qualname__}"
        fields = {
            f.name: _serialize(getattr(obj, f.name))
            for f in dataclasses.fields(obj)
        }
        return {"__type__": tag, **fields}
    if isinstance(obj, list):
        return [_serialize(i) for i in obj]
    if isinstance(obj, dict):
        return {k: _serialize(v) for k, v in obj.items()}
    if hasattr(obj, "isoformat"):  # datetime, date
        return {"__datetime__": obj.isoformat()}
    return obj


def _deserialize(obj: Any) -> Any:
    """Recursively reconstruct typed objects from the serialized form.

    Uses importlib to resolve type tags — no circular import, no registry
    setup required. Unknown types fall back to plain dicts.
    """
    if isinstance(obj, dict):
        if "__datetime__" in obj:
            from datetime import datetime, timezone
            dt = datetime.fromisoformat(obj["__datetime__"])
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        if "__type__" in obj:
            type_tag: str = obj["__type__"]
            cls = _TYPE_REGISTRY.get(type_tag) or _resolve_type(type_tag)
            fields = {k: _deserialize(v) for k, v in obj.items() if k != "__type__"}
            if cls is not None:
                try:
                    return cls(**fields)
                except Exception as e:
                    logger.debug("Cache: failed to reconstruct %s: %s", type_tag, e)
            return fields  # fall back to plain dict
        return {k: _deserialize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_deserialize(i) for i in obj]
    return obj


def _resolve_type(type_tag: str) -> Optional[type]:
    """Resolve 'module.ClassName' to a class via importlib, cache result."""
    try:
        # type_tag is "src.models.market.StockQuote" style
        module_path, class_name = type_tag.rsplit(".", 1)
        mod = importlib.import_module(module_path)
        cls = getattr(mod, class_name)
        _TYPE_REGISTRY[type_tag] = cls  # cache for next time
        return cls
    except Exception:
        return None


def _safe_json_dumps(obj: Any) -> str:
    """JSON-serialise, tagging dataclasses for type-safe round-tripping."""
    return json.dumps(_serialize(obj))
