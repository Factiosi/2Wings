"""List editing page — opens files in the system editor."""

from __future__ import annotations

from pathlib import Path

from qfluentwidgets import BodyLabel, PushButton

from src.core.settings import get_settings
from src.modules.lists.catalog import list_user_entries, list_versioned_entries
from src.modules.lists.editor import open_in_default_editor
from src.modules.strategies.repository import bootstrap_user_lists
from src.ui.components import Lucide, Group, OptionCard, Page
from src.ui.notifications import show_toast


class ListsPage(Page):
    title = "Редактирование листов"

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        bootstrap_user_lists()
        version_label = get_settings().active_version or "—"
        user_cards = [self._list_card(entry.name, entry.path) for entry in list_user_entries()]
        version_cards = [self._list_card(entry.name, entry.path) for entry in list_versioned_entries()]
        self.add(
            Group("Пользовательские листы (общие для всех версий стратегий)", *user_cards),
            Group(
                f"Листы стратегий (не рекомендуется к редактированию) · flowseal {version_label}",
                *(version_cards or [BodyLabel("Нет листов для активной версии")]),
            ),
        )

    def _list_card(self, name: str, path: Path) -> OptionCard:
        def on_open() -> None:
            ok, message = open_in_default_editor(path)
            show_toast(message, kind="success" if ok else "error")

        button = PushButton("Открыть")
        button.clicked.connect(on_open)
        return OptionCard(name, "", button, icon=Lucide("file-text"))
