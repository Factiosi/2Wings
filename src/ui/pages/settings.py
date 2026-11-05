"""Settings page."""

from __future__ import annotations

from PySide6.QtWidgets import QFileDialog
from qfluentwidgets import PrimaryPushButton, PushButton

from src.core.paths import APP_NAME, default_app_data_root
from src.core.version import __version__
from src.core.settings import get_settings, save_settings
from src.kernel.public import get_effective_runtime_status, restart_if_running
from src.modules.lifecycle.public import apply_autostart_setting
from src.modules.storage.migrate import apply_storage_root, current_storage_display
from src.modules.strategies.repository import (
    apply_version_retention,
    flowseal_version_select_options,
    list_strategies,
    purge_stale_versions,
    set_active_version,
)
from src.modules.updates.app import check_and_install_app, check_app_only
from src.modules.updates.github import check_for_update
from src.modules.updates.service import (
    MSG_DOWNLOADING,
    MSG_STALE_REMOVED,
    check_and_apply,
    check_only,
)
from src.ui.components import Lucide, Group, OptionCard, Page, Panel, apply_theme, caption, row, select_card, spinner, switch_card, text_field
from src.ui.dispatch import run_bg, ui_call
from src.ui.features.debug_console.launcher import open_debug_console
from src.ui.notifications import present_app_update_result, show_toast


class SettingsPage(Page):
    title = "Настройки"

    def __init__(self, on_settings_change, parent=None) -> None:
        super().__init__(parent)
        self._on_settings_change = on_settings_change
        self._saved_storage_path = current_storage_display()
        self._update_buttons: list[PushButton] = []
        self._update_rings: dict[str, object] = {}
        self._updates_busy = False
        self._build()

    def _bool_card(self, title: str, field: str, *, description: str = "", icon=None, autostart: bool = False) -> OptionCard:
        return switch_card(
            title,
            description,
            bool(getattr(get_settings(), field)),
            lambda value: self._on_bool_setting(field, value, autostart=autostart),
            icon=icon,
        )

    def _update_button(self, role: str, text: str, on_click, *, primary: bool = False) -> PushButton:
        button = (PrimaryPushButton if primary else PushButton)(text)
        button.clicked.connect(on_click)
        ring = spinner(16)
        ring.setVisible(False)
        self._update_buttons.append(button)
        self._update_rings[role] = ring
        return button

    def _build(self) -> None:
        settings = get_settings()
        self.add(
            Group(
                "Оформление",
                select_card(
                    "Тема оформления",
                    [("auto", "Как в Windows"), ("dark", "Тёмная"), ("light", "Светлая")],
                    settings.theme_mode,
                    self._on_theme_mode_change,
                    icon=Lucide("palette"),
                ),
            ),
            Group(
                "Поведение",
                self._bool_card("Добавить в автозапуск", "autostart_enabled", autostart=True, icon=Lucide("power")),
                self._bool_card(
                    "Запускать последнюю активную стратегию вместе с запуском программы",
                    "launch_last_strategy_on_startup",
                    icon=Lucide("play"),
                ),
                self._bool_card("Запускать в свёрнутом виде (в трее)", "start_minimized_to_tray", icon=Lucide("minimize-2")),
                select_card(
                    "Реакция на кнопку закрытия (крестик)",
                    [("exit", "Закрыть программу"), ("minimize_tray", "Свернуть в трей")],
                    settings.close_action,
                    self._on_close_action_change,
                    icon=Lucide("x"),
                ),
                switch_card(
                    "Настройки для продвинутых пользователей",
                    "Открывает «Изменение DNS», «Редактирование hosts» и выбор источника стратегий, в том числе свою стратегию.",
                    settings.advanced_mode,
                    self._on_advanced_mode,
                    icon=Lucide("wrench"),
                ),
            ),
        )

        strategies = Group("Стратегии")
        if settings.advanced_mode:
            strategies.add(
                select_card(
                    "Источник стратегий",
                    [("flowseal", "Стратегии Flowseal"), ("custom", "Своя стратегия")],
                    settings.strategy_source,
                    self._on_strategy_source_change,
                    icon=Lucide("waypoints"),
                )
            )
        strategies.add(
            switch_card(
                "Автоматическое внесение доменов и IP в исключения при ошибке TLS",
                "Если сервер отвергает изменённое обходом TLS-рукопожатие (в браузере — ERR_SSL_PROTOCOL_ERROR), "
                "домен попадает в list-exclude-user.txt, а для игровых и IP-профилей — адрес в ipset-exclude-user.txt. "
                "Сайт откроется со следующей попытки.",
                settings.tls_auto_exclude,
                self._on_tls_auto_exclude,
                icon=Lucide("shield-check"),
            )
        )
        self.add(strategies)

        if settings.strategy_source == "flowseal":
            self._build_flowseal(settings)
        self._build_storage()
        console = PushButton(Lucide("square-terminal"), "Открыть консоль отладки")
        console.clicked.connect(self._open_console)
        self.add(
            Group(
                "Консоль",
                OptionCard(
                    "Консоль отладки",
                    "Пишет все действия приложения подробно. Записи старше 1 часа удаляются автоматически.",
                    console,
                    icon=Lucide("square-terminal"),
                ),
            )
        )
        check = self._update_button("app:check", "Проверить обновления", self._check_app_updates_only)
        install = self._update_button(
            "app:install", "Проверить обновления и установить", self._check_and_install_app_updates, primary=True
        )
        self.add(
            Group(
                f"Обновления {APP_NAME}",
                self._bool_card("Автоматически проверять обновления при запуске", "auto_check_app_updates_on_startup", icon=Lucide("refresh-cw")),
                self._bool_card("Автоматически скачивать обновления и устанавливать", "auto_install_app_updates", icon=Lucide("download")),
                Panel(
                    caption(f"{APP_NAME} v{__version__}"),
                    row(check, install, self._update_rings["app:check"], self._update_rings["app:install"]),
                ),
            )
        )

    def _build_flowseal(self, settings) -> None:
        check = self._update_button("flowseal:check", "Проверить обновления", self._check_updates_only)
        apply = self._update_button(
            "flowseal:apply", "Проверить обновления и применить", self._check_and_apply, primary=True
        )
        self.add(
            Group(
                "Обновление стратегий Flowseal",
                self._bool_card("Автоматически проверять обновления при запуске", "auto_check_updates_on_startup", icon=Lucide("refresh-cw")),
                self._bool_card("Автоматически скачивать обновления и применять", "auto_promote_updates", icon=Lucide("download")),
                select_card(
                    "Версия flowseal",
                    flowseal_version_select_options(settings),
                    settings.active_version or "",
                    self._on_version_change,
                    icon=Lucide("tag"),
                ),
                Panel(row(check, apply, self._update_rings["flowseal:check"], self._update_rings["flowseal:apply"])),
            )
        )
        purge = PushButton(Lucide("trash-2"), "Удалить неактуальные версии (принудительно)")
        purge.clicked.connect(self._purge_versions)
        self.add(
            Group(
                "Flowseal",
                select_card(
                    "Хранение версий стратегий",
                    [
                        ("all", "Хранить все версии"),
                        ("latest_only", "Хранить только актуальную версию"),
                        ("keep_previous", "Хранить актуальную и предыдущую"),
                    ],
                    settings.version_retention,
                    self._on_retention_change,
                    icon=Lucide("history"),
                ),
                Panel(row(purge)),
            )
        )

    def _build_storage(self) -> None:
        self._storage_field = text_field(self._saved_storage_path)
        self._storage_field.textChanged.connect(lambda _text: self._update_storage_apply_state())
        browse = PushButton(Lucide("folder-open"), "Выбрать папку")
        browse.clicked.connect(self._pick_folder)
        self._storage_apply_btn = PrimaryPushButton("Применить")
        self._storage_apply_btn.setEnabled(False)
        self._storage_apply_btn.clicked.connect(self._apply_storage)
        self.add(
            Group(
                "Место хранения",
                Panel(
                    caption(f"По умолчанию: {default_app_data_root()}"),
                    self._storage_field,
                    row(browse, self._storage_apply_btn),
                ),
            )
        )

    # updates -------------------------------------------------------------------
    def _set_updates_loading(self, loading: bool, active: str | None = None) -> None:
        self._updates_busy = loading
        for button in self._update_buttons:
            button.setEnabled(not loading)
        for role, ring in self._update_rings.items():
            ring.setVisible(loading and role == active)

    def _run_updates_bg(self, work, on_done, *, active: str) -> None:
        if self._updates_busy:
            return
        self._set_updates_loading(True, active)

        def task():
            if active == "flowseal:apply" and check_for_update(get_settings().active_version).update_available:
                ui_call(lambda: show_toast(MSG_DOWNLOADING, kind="warning", duration=6.0))
            return work()

        def finish(result) -> None:
            self._set_updates_loading(False)
            on_done(result)

        run_bg(task, finish, name="twowings-updates", on_error=lambda exc: exc)

    @staticmethod
    def _show_triple(result) -> None:
        if isinstance(result, Exception):
            show_toast(str(result), kind="error")
            return
        ok, msg, kind = result
        show_toast(msg, kind=kind if ok else "error")

    def _check_updates_only(self) -> None:
        self._run_updates_bg(check_only, self._show_triple, active="flowseal:check")

    def _check_and_apply(self) -> None:
        def done(result) -> None:
            if isinstance(result, Exception):
                show_toast(str(result), kind="error")
                return
            show_toast(result.message, kind=result.toast_kind)
            if result.ok and result.version_changed:
                self._on_settings_change()

        self._run_updates_bg(check_and_apply, done, active="flowseal:apply")

    def _check_app_updates_only(self) -> None:
        def done(result) -> None:
            if isinstance(result, Exception):
                show_toast(str(result), kind="error")
                return
            present_app_update_result(*result)

        self._run_updates_bg(check_app_only, done, active="app:check")

    def _check_and_install_app_updates(self) -> None:
        def done(result) -> None:
            if isinstance(result, Exception):
                show_toast(str(result), kind="error")
                return
            ok, msg, kind = result
            if ok and kind == "success":
                return
            show_toast(msg, kind=kind if ok else "error")

        self._run_updates_bg(check_and_install_app, done, active="app:install")

    # settings ------------------------------------------------------------------
    def _on_version_change(self, version: str) -> None:
        if not version:
            return
        set_active_version(version)
        strategies = list_strategies()
        settings = get_settings()
        if settings.selected_strategy not in {s.id for s in strategies}:
            settings.selected_strategy = strategies[0].id if strategies else ""
            save_settings(settings)
        if get_effective_runtime_status().running:
            self._restart(lambda ok, msg: show_toast(msg or f"Версия {version}. Перезапущено.", kind="info" if ok else "error"))
        else:
            show_toast(f"Версия flowseal: {version}.")

    def _on_bool_setting(self, field: str, value: bool, *, autostart: bool = False) -> None:
        settings = get_settings()
        setattr(settings, field, value)
        save_settings(settings)
        if autostart:
            ok, msg = apply_autostart_setting(value)
            if not ok and msg:
                show_toast(msg, kind="error")

    @staticmethod
    def _restart(report) -> None:
        run_bg(restart_if_running, lambda result: report(*result), name="twowings-restart")

    def _on_tls_auto_exclude(self, value: bool) -> None:
        self._on_bool_setting("tls_auto_exclude", value)
        if get_effective_runtime_status().running:
            self._restart(
                lambda ok, msg: show_toast(msg if not ok else "Обход перезапущен с новой настройкой.", kind="info" if ok else "error")
            )

    def _on_close_action_change(self, value: str) -> None:
        settings = get_settings()
        settings.close_action = value  # type: ignore[assignment]
        save_settings(settings)

    def _on_theme_mode_change(self, mode: str) -> None:
        settings = get_settings()
        settings.theme_mode = mode  # type: ignore[assignment]
        save_settings(settings)
        apply_theme(mode)

    def _on_advanced_mode(self, value: bool) -> None:
        settings = get_settings()
        settings.advanced_mode = value
        # Without the advanced settings the strategy source is always Flowseal.
        back_to_flowseal = not value and settings.strategy_source != "flowseal"
        if back_to_flowseal:
            settings.strategy_source = "flowseal"
        save_settings(settings)
        if back_to_flowseal and get_effective_runtime_status().running:
            self._restart(lambda ok, msg: None if ok else show_toast(msg, kind="error"))
        self._on_settings_change()

    def _on_strategy_source_change(self, value: str) -> None:
        settings = get_settings()
        settings.strategy_source = value  # type: ignore[assignment]
        save_settings(settings)
        self._on_settings_change()

    def _on_retention_change(self, value: str) -> None:
        settings = get_settings()
        settings.version_retention = value  # type: ignore[assignment]
        if value == "keep_previous":
            settings.keep_version_count = 2
        save_settings(settings)
        if apply_version_retention():
            show_toast(MSG_STALE_REMOVED)

    def _update_storage_apply_state(self) -> None:
        dirty = self._storage_field.text().strip() != self._saved_storage_path
        self._storage_apply_btn.setEnabled(dirty)
        if dirty:
            self._storage_apply_btn.setText("Применить")

    def _pick_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(self, f"Выберите папку для данных {APP_NAME}", self._storage_field.text())
        if path:
            self._storage_field.setText(path.replace("/", "\\"))

    def _apply_storage(self) -> None:
        path = self._storage_field.text()

        def done(result) -> None:
            ok, msg = result
            if ok:
                self._saved_storage_path = current_storage_display()
                self._storage_field.setText(self._saved_storage_path)
                self._storage_apply_btn.setText("Применено")
                self._storage_apply_btn.setEnabled(False)
            show_toast(msg, kind="info" if ok else "error")

        run_bg(lambda: apply_storage_root(path), done, name="twowings-storage")

    def _purge_versions(self) -> None:
        def done(removed) -> None:
            if isinstance(removed, Exception):
                show_toast(str(removed), kind="error")
            else:
                show_toast(MSG_STALE_REMOVED if removed else "Нет версий для удаления")

        run_bg(lambda: purge_stale_versions(keep=1), done, name="twowings-purge", on_error=lambda exc: exc)

    def _open_console(self) -> None:
        ok, message = open_debug_console()
        show_toast(message, kind="info" if ok else "error")
