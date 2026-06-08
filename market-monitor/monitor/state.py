"""Tiny JSON state store: today's baseline + ratcheting alert references."""

from __future__ import annotations

import json
import os
from typing import Any


def load_state(path: str) -> dict[str, Any]:
    """Load the state dict from ``path``; return ``{}`` if missing or unreadable."""
    if not path or not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def save_state(path: str, state: dict[str, Any]) -> None:
    """Persist ``state`` to ``path`` as pretty-printed JSON."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, sort_keys=True)
