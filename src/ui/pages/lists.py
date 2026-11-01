"""List editing page — opens files in the system editor."""

from __future__ import annotations

import flet as ft

from src.core.settings import get_settings
from src.modules.lists.catalog import list_user_entries, list_versioned_entries
from src.modules.lists.editor import open_in_default_editor
from src.modules.strategies.repository import bootstrap_user_lists
from src.ui.theme import T
from src.ui.components import block_section, pill_button, scroll_page, ui_text
from src.ui.notifications import show_toast


class ListsPage:
    def __init__(self, page: ft.Page) -> None:
        self.page = page

    def build(self) -> ft.Control:
        bootstrap_user_lists()
        settings = get_settings()
        version_label = settings.active_version or "—"

        user_rows = [
            self._list_row(entry.name, entry.path)
            for entry in list_user_entries()
        ]
        version_rows = [
            self._list_row(entry.name, entry.path)
            for entry in list_versioned_entries()
        ] or [ui_text("Нет листов для активной версии", color=T.TEXT_MUTED, size=T.FONT_CAPTION)]

        strategy_section_title = (
            f"Листы стратегий (не рекомендуется к редактированию) · flowseal {version_label}"
        )

        return scroll_page(
            block_section(
                "Пользовательские листы (общие для всех версий стратегий)",
                *user_rows,
            ),
            block_section(
                strategy_section_title,
                *version_rows,
            ),
            page=self.page,
        )

    def _list_row(self, name: str, path) -> ft.Row:
        def on_open(_: ft.ControlEvent) -> None:
            ok, message = open_in_default_editor(path)
            show_toast(self.page, message, kind="error" if not ok else "success")

        return ft.Row(
            [
                ui_text(name, expand=True),
                pill_button("Открыть", on_click=on_open),
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
