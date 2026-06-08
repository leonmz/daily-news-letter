"""State store for the day's baseline + ratcheting alert references.

Supports two backends, chosen by the ``STATE_PATH``:
  * a local JSON file (default, e.g. ``monitor_state.json``)
  * a Google Cloud Storage object (``gs://bucket/key``) — used on Cloud Run,
    whose filesystem is ephemeral between scheduled invocations.

``google-cloud-storage`` is imported lazily, so local/unit-test usage never
needs it installed.
"""

from __future__ import annotations

import json
import os
from typing import Any


def _is_gcs(path: str) -> bool:
    return path.startswith("gs://")


def _gcs_split(path: str) -> tuple[str, str]:
    """'gs://bucket/a/b.json' -> ('bucket', 'a/b.json')."""
    rest = path[len("gs://"):]
    bucket, _, key = rest.partition("/")
    return bucket, key


def load_state(path: str) -> dict[str, Any]:
    """Load the state dict from ``path``; return ``{}`` if missing or unreadable."""
    if not path:
        return {}
    if _is_gcs(path):
        try:
            from google.cloud import storage

            bucket, key = _gcs_split(path)
            blob = storage.Client().bucket(bucket).blob(key)
            if not blob.exists():
                return {}
            return json.loads(blob.download_as_text())
        except Exception as e:  # noqa: BLE001 - treat any read failure as "no state"
            print(f"[state] GCS load failed ({path}): {e}")
            return {}

    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def save_state(path: str, state: dict[str, Any]) -> None:
    """Persist ``state`` to ``path`` (local file or gs:// object) as JSON."""
    payload = json.dumps(state, indent=2, sort_keys=True)
    if _is_gcs(path):
        from google.cloud import storage

        bucket, key = _gcs_split(path)
        storage.Client().bucket(bucket).blob(key).upload_from_string(
            payload, content_type="application/json"
        )
        return

    with open(path, "w", encoding="utf-8") as f:
        f.write(payload)
