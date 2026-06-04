"""Persistent dedupe state.

Tracks two things per product key so the monitor behaves well across restarts:
  - `seen`:    the last-known in-stock flag, so we only alert on a genuine
               out -> available transition and don't re-spam on restart.
  - `alerted`: the epoch time we last sent an alert, so re-notify reminders can
               re-ping a still-available preorder/pickup after an interval.

State is a JSON object with those two sub-maps:
    {"seen": {"<key>": true, ...}, "alerted": {"<key>": 1735700000.0, ...}}

Older files are a flat {"<key>": true/false} seen-map; those are migrated on
load into the new shape. Writes are atomic (temp file + os.replace) so a crash
mid-write can't corrupt the file.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile

log = logging.getLogger(__name__)


def _empty() -> dict:
    return {"seen": {}, "alerted": {}}


def load(path: str) -> dict:
    """Return {"seen": {key: bool}, "alerted": {key: float}}.

    Tolerates a legacy flat {key: bool} file (wraps it as the seen-map) and any
    corrupt/missing file (returns empty state) so startup never crashes.
    """
    if not path or not os.path.exists(path):
        return _empty()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and "seen" in data and "alerted" in data:
            seen = data.get("seen") or {}
            alerted = data.get("alerted") or {}
            return {
                "seen": {str(k): bool(v) for k, v in seen.items()},
                "alerted": {str(k): float(v) for k, v in alerted.items()},
            }
        if isinstance(data, dict):
            # Legacy flat seen-map: migrate to the two-section shape.
            return {"seen": {str(k): bool(v) for k, v in data.items()}, "alerted": {}}
        log.warning("state file %s is not an object; ignoring", path)
    except Exception as e:  # noqa: BLE001 - corrupt state shouldn't crash startup
        log.warning("could not read state file %s: %s", path, e)
    return _empty()


def save(path: str, state: dict) -> None:
    if not path:
        return
    try:
        directory = os.path.dirname(os.path.abspath(path))
        os.makedirs(directory, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=directory, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(state, f)
        os.replace(tmp, path)  # atomic on Windows and POSIX
    except Exception as e:  # noqa: BLE001 - persistence is best-effort
        log.warning("could not write state file %s: %s", path, e)
