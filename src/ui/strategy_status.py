"""Shared presentation helpers for strategy test status."""

from __future__ import annotations

from PySide6.QtWidgets import QWidget

from src.modules.strategy_testing import results as tr
from src.ui.components import status_badge


def strategy_status(strategy_id: str) -> tuple[str, str]:
    item = tr.get_result(strategy_id)
    if not item:
        return "offline", "Не протестирована"
    mapping = {
        "full": ("active", "Полностью работает"),
        "partial": ("expiring", "Частично работает"),
        "failed": ("error", "Не работает"),
        "unknown": ("error", "Неизвестно"),
        "running": ("connecting", "Проверяется"),
    }
    return mapping.get(item.state, ("offline", "Не протестирована"))


def strategy_actions_disabled(
    strategy_id: str,
    *,
    selected_strategy: str | None,
    tests_running: bool,
) -> bool:
    return (
        tests_running
        or not tr.is_tested(strategy_id)
        or selected_strategy == strategy_id
    )


def strategy_badge(strategy_id: str, parent: QWidget | None = None) -> QWidget:
    key, label = strategy_status(strategy_id)
    return status_badge(key, label, parent)
