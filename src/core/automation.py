"""Guard for development and explicitly enabled automation interfaces."""

from __future__ import annotations

import os

from src.core.paths import is_packaged_app

_TRUE_VALUES = {"1", "true", "yes", "on"}


def automation_enabled() -> bool:
    """Enable automatically in source runs, explicitly in packaged test builds."""
    if not is_packaged_app():
        return True
    return os.environ.get("TWOWINGS_AUTOMATION", "").strip().lower() in _TRUE_VALUES
