"""Top toast banners — Factiosi feedback pattern for Tigo."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable

import flet as ft

from src.ui.theme import T
from src.ui.components import ui_text

_active_toast: ft.Container | None = None
_dismiss_timer: threading.Timer | None = None
_dismiss_lock = threading.Lock()

TOAST_TOP = 52
TOAST_WIDTH = 460
TOAST_SHOW_SECONDS = 4.0
TOAST_DURATION_CLICKABLE = 12.0

TOAST_ANIM_ENTER = ft.Animation(300, ft.AnimationCurve.EASE_OUT)
TOAST_ANIM_EXIT = ft.Animation(200, ft.AnimationCurve.EASE_IN)
TOAST_ANIM_DISMISS = ft.Animation(200, ft.AnimationCurve.EASE_OUT)

def _kind_style(kind: str) -> tuple[str, str]:
    """Тост Umbrae: фон статуса и текст того же статуса (цвет, фон)."""
    styles = {
        "info": (T.BUTTON, T.SELECTED),
        "success": (T.STATUS_ACTIVE, T.STATUS_ACTIVE_BG),
        "warning": (T.STATUS_EXPIRING, T.STATUS_EXPIRING_BG),
        "error": (T.STATUS_ERROR, T.STATUS_ERROR_BG),
    }
    return styles.get(kind, styles["info"])


def _toast_left(_page: ft.Page) -> float:
    return float(T.SIDEBAR_WIDTH + 28)


def _cancel_timer() -> None:
    global _dismiss_timer
    with _dismiss_lock:
        if _dismiss_timer is not None:
            _dismiss_timer.cancel()
            _dismiss_timer = None


def _detach_toast(page: ft.Page) -> None:
    global _active_toast
    _cancel_timer()
    if _active_toast is not None and _active_toast in page.overlay:
        page.overlay.remove(_active_toast)
    _active_toast = None


def _schedule_on_page(page: ft.Page, callback: Callable[[], None]) -> None:
    try:
        page.run_thread(callback)
    except AttributeError:
        callback()


async def _sleep(seconds: float) -> None:
    await asyncio.sleep(seconds)


async def _animate_toast_out(page: ft.Page, banner: ft.Container, *, fast: bool) -> None:
    banner.animate_opacity = TOAST_ANIM_DISMISS if fast else TOAST_ANIM_EXIT
    banner.animate_offset = None if fast else TOAST_ANIM_EXIT
    banner.opacity = 0
    if not fast:
        banner.offset = ft.Offset(0, -0.35)
    try:
        page.update()
    except RuntimeError:
        return
    await _sleep(0.3 if fast else 0.6)
    _detach_toast(page)
    try:
        page.update()
    except RuntimeError:
        pass


async def _toast_lifecycle(
    page: ft.Page,
    banner: ft.Container,
    *,
    show_seconds: float,
) -> None:
    banner.opacity = 0
    banner.offset = ft.Offset(0, -1)
    banner.animate_opacity = TOAST_ANIM_ENTER
    banner.animate_offset = TOAST_ANIM_ENTER
    try:
        page.update()
    except RuntimeError:
        return

    await _sleep(0.05)
    banner.opacity = 1
    banner.offset = ft.Offset(0, 0)
    try:
        page.update()
    except RuntimeError:
        return

    await _sleep(show_seconds)
    if banner is not _active_toast:
        return
    await _animate_toast_out(page, banner, fast=False)


def show_toast(
    page: ft.Page,
    message: str,
    *,
    kind: str = "info",
    duration: float | None = None,
    on_click: Callable[[], None] | None = None,
) -> None:
    """Show a compact animated banner below the page header."""
    global _active_toast

    text = message.strip()
    if not text:
        return

    fg, bg = _kind_style(kind)
    show_seconds = (
        duration
        if duration is not None
        else (TOAST_DURATION_CLICKABLE if on_click else TOAST_SHOW_SECONDS)
    )

    async def dismiss_manual(_: ft.ControlEvent | None = None) -> None:
        if banner is not _active_toast:
            return
        _cancel_timer()
        await _animate_toast_out(page, banner, fast=True)

    def handle_body_click(e: ft.ControlEvent) -> None:
        if on_click is None:
            return
        _cancel_timer()
        _schedule_on_page(page, lambda: on_click())
        page.run_task(dismiss_manual)

    message_row = ft.Row(
        [
            ft.Container(width=6, height=6, bgcolor=fg, border_radius=99),
            ft.Container(
                content=ui_text(text, size=T.FONT_BODY, color=fg, text_align=ft.TextAlign.CENTER),
                expand=True,
                alignment=ft.Alignment.CENTER,
            ),
        ],
        spacing=8,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
        expand=True,
    )

    inner = ft.Container(
        content=ft.Row(
            [
                ft.Container(content=message_row, expand=True),
                ft.IconButton(
                    icon=ft.Icons.CLOSE,
                    icon_size=18,
                    icon_color=fg,
                    tooltip="Закрыть",
                    style=ft.ButtonStyle(padding=4),
                    on_click=dismiss_manual,
                ),
            ],
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=4,
        ),
        bgcolor=bg,
        border=ft.Border.all(1, T.BORDER),
        border_radius=T.RADIUS_L,
        padding=ft.Padding.only(left=16, right=4, top=12, bottom=12),
        shadow=ft.BoxShadow(
            blur_radius=18,
            spread_radius=0,
            color=T.SHADOW,
            offset=ft.Offset(0, 6),
        ),
        ink=on_click is not None,
        on_click=handle_body_click if on_click is not None else None,
    )
    banner = ft.Container(
        content=inner,
        top=TOAST_TOP,
        left=_toast_left(page),
        width=TOAST_WIDTH,
        opacity=0,
        offset=ft.Offset(0, -1),
    )

    _detach_toast(page)
    _active_toast = banner
    page.overlay.append(banner)
    page.update()

    async def lifecycle() -> None:
        await _toast_lifecycle(page, banner, show_seconds=show_seconds)

    page.run_task(lifecycle)


def _start_app_update_install(page: ft.Page) -> None:
    from src.modules.updates.app import check_and_install_app

    def work() -> None:
        ok, message, kind = check_and_install_app()

        def notify() -> None:
            if ok and kind == "success":
                return
            show_toast(page, message, kind=kind if ok else "error")

        _schedule_on_page(page, notify)

    threading.Thread(target=work, daemon=True, name="tigo-app-update-install").start()


def show_app_update_toast(page: ft.Page) -> None:
    from src.modules.updates.app import MSG_APP_UPDATE_CLICKABLE

    show_toast(
        page,
        MSG_APP_UPDATE_CLICKABLE,
        kind="warning",
        on_click=lambda: _start_app_update_install(page),
    )


def present_app_update_result(
    page: ft.Page,
    ok: bool,
    message: str,
    kind: str,
) -> None:
    from src.modules.updates.app import MSG_APP_UP_TO_DATE

    if ok and message == MSG_APP_UP_TO_DATE:
        show_toast(page, message, kind="success")
        return
    if ok and kind == "warning":
        show_app_update_toast(page)
        return
    show_toast(page, message, kind=kind if ok else "error")
