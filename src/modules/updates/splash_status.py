"""Файл, которым новая 2Wings после обновления говорит TwoWingsUpdate «я запущена»."""

from __future__ import annotations

import json
from typing import Any

from src.core.paths import temp_dir

_STATUS_NAME = "update-status.json"


def status_path():
    return temp_dir() / _STATUS_NAME


def write_update_status(phase: str, message: str, *, target_version: str = "") -> None:
    path = status_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "phase": phase.strip(),
        "message": message.strip(),
        "target_version": target_version.strip(),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def read_update_status() -> dict[str, Any]:
    path = status_path()
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def clear_update_status() -> None:
    path = status_path()
    path.unlink(missing_ok=True)
