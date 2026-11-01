"""Factiosi UI helpers for Tigo."""

from __future__ import annotations

import asyncio
import math
from typing import Callable

import flet as ft

from src.ui.theme import T

ANIM = ft.Animation(300, ft.AnimationCurve.EASE_IN_OUT)
ANIM_FAST = ft.Animation(100, ft.AnimationCurve.EASE_OUT)
MENU_IN = ft.Animation(200, ft.AnimationCurve.EASE_OUT)
CHEVRON_ANIM = ft.Animation(200, ft.AnimationCurve.EASE_OUT)
EXPAND_ANIM = ft.Animation(300, ft.AnimationCurve.EASE_IN_OUT)

MENU_MAX_HEIGHT = 280
MENU_ITEM_HEIGHT = 38
MENU_EDGE_INSET = 4
MENU_POPUP_VPAD = 8
MENU_ITEM_RADIUS = 4  # панель меню 8 минус поле 4: вложенный радиус не спорит с внешним
def lucide_icon(name: str, *, color: str, size: int = 18) -> ft.Image:
    """Lucide icon from assets/icons/lucide (ISC); the stroke takes ``color``."""
    return ft.Image(
        src=f"/assets/icons/lucide/{name}.svg",
        width=size,
        height=size,
        color=color,
        color_blend_mode=ft.BlendMode.SRC_IN,
    )


def menu_shadow() -> ft.BoxShadow:
    return ft.BoxShadow(
        blur_radius=16,
        color=T.SHADOW,
        offset=ft.Offset(0, 4),
    )
BUTTON_HEIGHT = T.BUTTON_HEIGHT
LOG_PANEL_HEIGHT_HOME = 280
LOG_PANEL_HEIGHT_TEST = 560

_active_select_close: Callable[[], None] | None = None
_page_keyboard_saved: Callable[[ft.KeyboardEvent], None] | None = None
_select_scroll_reposition: Callable[[float], None] | None = None
MENU_GAP = 8


def _select_menu_item_style(*, selected: bool) -> ft.ButtonStyle:
    """Выбранный пункт подсвечен так же тускло, как наведённый, и не меняет фон от фокуса:
    иначе Flutter, уводя фокус на наведённый пункт, зажигает выбранный ярче."""
    hover_bg = T.OVERLAY_HOVER
    text_color = T.MENU_SELECTED if selected else T.TEXT
    if selected:
        return ft.ButtonStyle(
            shape=ft.RoundedRectangleBorder(radius=MENU_ITEM_RADIUS),
            padding=ft.Padding.symmetric(horizontal=16, vertical=0),
            alignment=ft.Alignment(-1, 0),
            color={ft.ControlState.DEFAULT: text_color},
            text_style=ft.TextStyle(size=T.FONT_BODY, font_family=T.FONT_FAMILY, weight=ft.FontWeight.W_400),
            bgcolor={ft.ControlState.DEFAULT: hover_bg},
            overlay_color={ft.ControlState.DEFAULT: "#00000000"},
            mouse_cursor=ft.MouseCursor.CLICK,
            visual_density=ft.VisualDensity.COMPACT,
        )
    return ft.ButtonStyle(
        shape=ft.RoundedRectangleBorder(radius=MENU_ITEM_RADIUS),
        padding=ft.Padding.symmetric(horizontal=16, vertical=0),
        alignment=ft.Alignment(-1, 0),
        color={ft.ControlState.DEFAULT: text_color},
        text_style=ft.TextStyle(
            size=T.FONT_BODY,
            font_family=T.FONT_FAMILY,
            weight=ft.FontWeight.W_400,
        ),
        bgcolor={
            ft.ControlState.DEFAULT: T.SELECTED if selected else "#00000000",
            ft.ControlState.HOVERED: hover_bg,
            ft.ControlState.FOCUSED: hover_bg,
        },
        overlay_color={
            ft.ControlState.HOVERED: hover_bg,
            ft.ControlState.FOCUSED: hover_bg,
        },
        mouse_cursor=ft.MouseCursor.CLICK,
        visual_density=ft.VisualDensity.COMPACT,
    )


def _raise_menu_overlay(page: ft.Page, menu_popup: ft.Control) -> None:
    """Keep the open menu last in page.overlay to win z-order."""
    if menu_popup in page.overlay:
        page.overlay.remove(menu_popup)
    page.overlay.append(menu_popup)


def _close_active_select(*, refresh: bool = True) -> None:
    global _active_select_close
    if _active_select_close is not None:
        close = _active_select_close
        _active_select_close = None
        close(refresh=refresh)


def close_active_select(*, refresh: bool = True) -> None:
    """Close the currently open custom select, if any."""
    _close_active_select(refresh=refresh)


def _global_keyboard_handler(e: ft.KeyboardEvent) -> None:
    if e.key == "Escape" and _active_select_close is not None:
        _active_select_close()
        return
    saved = _page_keyboard_saved
    if saved is not None and saved is not _global_keyboard_handler:
        saved(e)


def _attach_page_keyboard(page: ft.Page) -> None:
    global _page_keyboard_saved
    if _page_keyboard_saved is None:
        _page_keyboard_saved = page.on_keyboard_event  # type: ignore[assignment]
        page.on_keyboard_event = _global_keyboard_handler


def _detach_page_keyboard(page: ft.Page) -> None:
    global _page_keyboard_saved
    if _active_select_close is None and _page_keyboard_saved is not None:
        page.on_keyboard_event = _page_keyboard_saved  # type: ignore[assignment]
        _page_keyboard_saved = None


def _calc_menu_content_height(option_count: int) -> int:
    if option_count <= 0:
        return MENU_ITEM_HEIGHT
    spacing = max(0, option_count - 1) * 4
    inner = option_count * MENU_ITEM_HEIGHT + spacing
    return min(MENU_MAX_HEIGHT - MENU_POPUP_VPAD, inner)


def _calc_menu_height(option_count: int) -> int:
    return _calc_menu_content_height(option_count) + MENU_POPUP_VPAD


def _window_height(page: ft.Page) -> float:
    window = getattr(page, "window", None)
    if window is not None and window.height:
        return float(window.height)
    if page.height:
        return float(page.height)
    return 760.0


def _content_bottom(page: ft.Page) -> float:
    """Bottom edge of the scrollable body (window coords), excluding body padding."""
    return _window_height(page) - 8.0


def _global_from_tap(e: ft.TapEvent) -> tuple[float, float] | None:
    if e.global_position is None or e.local_position is None:
        return None
    field_left = e.global_position.x - e.local_position.x
    field_top = e.global_position.y - e.local_position.y
    return field_left, field_top


def _menu_height_for_options(option_count: int, resolved: int | None) -> float:
    if resolved is not None:
        return float(resolved)
    return float(_calc_menu_height(option_count))


def _placement_menu_height(option_count: int, resolved: int | None) -> float:
    """Height used for flip/placement (always known, even for short lists)."""
    return _menu_height_for_options(option_count, resolved or _calc_menu_height(option_count))


def _should_open_upward(
    field_top: float,
    menu_height: float,
    content_bottom: float,
) -> bool:
    space_below = content_bottom - (field_top + T.FIELD_HEIGHT + MENU_GAP)
    space_above = field_top - MENU_GAP
    if space_below >= menu_height:
        return False
    if space_above >= menu_height:
        return True
    return space_above > space_below


def _pill_style(*, primary: bool = False, destructive: bool = False) -> ft.ButtonStyle:
    shape = ft.RoundedRectangleBorder(radius=T.RADIUS_PILL)
    text_style = ft.TextStyle(
        size=T.FONT_BODY,
        font_family=T.FONT_UI,
        weight=ft.FontWeight.W_600,
    )
    padding = ft.Padding.symmetric(horizontal=12, vertical=0)
    hover_overlay = T.OUTLINE_HOVER
    disabled_bg = T.ELEVATED
    disabled_fg = T.TEXT_MUTED
    disabled_side = T.BORDER
    if destructive:
        return ft.ButtonStyle(
            color={
                ft.ControlState.DEFAULT: T.STATUS_ERROR,
                ft.ControlState.DISABLED: disabled_fg,
            },
            side={
                ft.ControlState.DEFAULT: ft.BorderSide(1, T.STATUS_ERROR),
                ft.ControlState.DISABLED: ft.BorderSide(1, disabled_side),
            },
            bgcolor={
                ft.ControlState.DISABLED: disabled_bg,
            },
            shape=shape,
            padding=padding,
            text_style=text_style,
            elevation=0,
            overlay_color={
                ft.ControlState.HOVERED: T.HOVER_SCRIM,
                ft.ControlState.PRESSED: T.PRESS_SCRIM,
            },
        )
    if primary:
        return ft.ButtonStyle(
            bgcolor={
                ft.ControlState.DEFAULT: T.BUTTON,
                ft.ControlState.DISABLED: disabled_bg,
            },
            color={
                ft.ControlState.DEFAULT: T.ON_BUTTON,
                ft.ControlState.DISABLED: disabled_fg,
            },
            shape=shape,
            padding=padding,
            text_style=text_style,
            elevation=0,
            overlay_color={
                ft.ControlState.HOVERED: T.HOVER_SCRIM,
                ft.ControlState.FOCUSED: T.HOVER_SCRIM,
                ft.ControlState.PRESSED: T.PRESS_SCRIM,
            },
        )
    return ft.ButtonStyle(
        color={
            ft.ControlState.DEFAULT: T.BUTTON,
            ft.ControlState.DISABLED: disabled_fg,
        },
        side={
            ft.ControlState.DEFAULT: ft.BorderSide(1, T.BUTTON),
            ft.ControlState.DISABLED: ft.BorderSide(1, disabled_side),
        },
        bgcolor={
            ft.ControlState.DISABLED: disabled_bg,
        },
        shape=shape,
        padding=padding,
        text_style=text_style,
        elevation=0,
        overlay_color={
            ft.ControlState.HOVERED: hover_overlay,
            ft.ControlState.FOCUSED: hover_overlay,
            ft.ControlState.PRESSED: hover_overlay,
        },
    )


def ui_text(
    value: str,
    *,
    size: float | None = None,
    color: str | None = None,
    weight: ft.FontWeight | None = None,
    family: str | None = None,
    **kwargs,
) -> ft.Text:
    return ft.Text(
        value,
        size=size if size is not None else T.FONT_BODY,
        color=color if color is not None else T.TEXT,
        weight=weight,
        font_family=family or T.FONT_FAMILY,
        **kwargs,
    )


class LeoSwitch:
    """Переключатель Umbrae: 52×32, бегунок 24, ход 20px за 100 мс, радиус переключателя из шкалы."""

    def __init__(self, *, label: str, value: bool, on_change: Callable[[bool], None]) -> None:
        self.value = value
        self._on_change = on_change
        self.thumb = ft.Container(
            width=24,
            height=24,
            border_radius=max(T.RADIUS_TOGGLE - 2, 1),
            left=24 if value else 4,
            top=4,
            animate_position=ft.Animation(100, ft.AnimationCurve.EASE_IN_OUT),
        )
        self.track = ft.Container(
            width=52,
            height=32,
            border_radius=T.RADIUS_TOGGLE,
            content=ft.Stack([self.thumb], width=52, height=32),
            on_click=self._toggle,
        )
        self.label = ui_text(label)
        self.control = ft.Row(
            [
                self.track,
                ft.Container(content=self.label, on_click=self._toggle),
            ],
            spacing=8,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            tight=True,
        )
        self.paint()

    def paint(self) -> None:
        self.track.bgcolor = T.BUTTON if self.value else T.TRACK_OFF
        self.thumb.bgcolor = T.ON_BUTTON if self.value else T.TEXT
        self.thumb.left = 24 if self.value else 4

    def set_value(self, value: bool) -> None:
        self.value = value
        self.paint()
        if self.track.page:
            self.track.update()

    def _toggle(self, _event: ft.ControlEvent) -> None:
        self.set_value(not self.value)
        self._on_change(self.value)


def quiet_checkbox(**kwargs) -> ft.Checkbox:
    """Чекбокс без материального круга: при наведении меняется сам знак, не пятно вокруг. Радиус — из шкалы Umbrae."""
    kwargs.setdefault("hover_color", "#00000000")
    kwargs.setdefault("shape", ft.RoundedRectangleBorder(radius=T.RADIUS_CHECKBOX))
    kwargs.setdefault("splash_radius", 0)
    kwargs.setdefault("active_color", T.BUTTON)
    kwargs.setdefault("check_color", T.ON_BUTTON)
    return ft.Checkbox(**kwargs)


def status_pill(status: str, label: str | None = None, *, dense: bool = False) -> ft.Container:
    """Бейдж статуса Umbrae: фон и текст одного статуса, радиус бейджа, без пилюли."""
    colors = {
        "active": (T.STATUS_ACTIVE_BG, T.STATUS_ACTIVE, "Активно"),
        "connecting": (T.STATUS_CONNECTING_BG, T.STATUS_CONNECTING, "Подключение"),
        "expiring": (T.STATUS_EXPIRING_BG, T.STATUS_EXPIRING, "Предупреждение"),
        "error": (T.STATUS_ERROR_BG, T.STATUS_ERROR, "Ошибка"),
        "offline": (T.STATUS_OFFLINE_BG, T.STATUS_OFFLINE, "Отключено"),
    }
    bg, fg, default = colors.get(status, colors["offline"])
    dot_size = 5 if dense else 6
    text_size = 11 if dense else 12
    padding = (
        ft.Padding.symmetric(horizontal=8, vertical=2)
        if dense
        else ft.Padding.symmetric(horizontal=12, vertical=4)
    )
    return ft.Container(
        content=ft.Row(
            [
                ft.Container(width=dot_size, height=dot_size, bgcolor=fg, border_radius=dot_size / 2),
                ui_text(label or default, size=text_size, color=fg, weight=ft.FontWeight.W_500),
            ],
            spacing=4 if dense else 6,
            tight=True,
        ),
        bgcolor=bg,
        padding=padding,
        border_radius=T.RADIUS_BADGE,
    )


def block_section(title: str | None, *controls: ft.Control) -> ft.Container:
    header: list[ft.Control] = []
    if title:
        header.append(
            ui_text(title, size=T.FONT_SECTION, weight=ft.FontWeight.W_600, family=T.FONT_DISPLAY)
        )
    return ft.Container(
        content=ft.Column(
            [
                *header,
                ft.Container(
                    content=ft.Column(
                        list(controls),
                        spacing=T.SPACE_FIELD,
                        tight=True,
                        horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
                    ),
                    bgcolor=T.SURFACE,
                    border=ft.Border.all(1, T.BORDER),
                    border_radius=T.RADIUS,
                    padding=T.SECTION_PAD,
                ),
            ],
            spacing=8,
            tight=True,
        ),
        animate_opacity=ANIM,
    )


def _register_page_scroll(page: ft.Page, view: ft.ListView) -> None:
    page._tigo_page_scroll = view  # type: ignore[attr-defined]
    page._tigo_page_scroll_offset = 0  # type: ignore[attr-defined]

    def track_scroll(e: ft.OnScrollEvent) -> None:
        page._tigo_page_scroll_offset = e.pixels  # type: ignore[attr-defined]
        if _select_scroll_reposition is not None:
            _select_scroll_reposition(e.pixels)

    view.on_scroll = track_scroll


def scroll_page(*controls: ft.Control, page: ft.Page | None = None) -> ft.ListView:
    def on_background_click(e: ft.ControlEvent) -> None:
        _close_active_select(refresh=False)
        if e.page:
            e.page.update()

    view = ft.ListView(
        controls=[
            ft.Container(
                content=ft.Column(
                    [*controls, ft.Container(height=24)],
                    spacing=T.SPACE_SECTION,
                    tight=True,
                    horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
                ),
                padding=ft.Padding.only(right=28),
                on_click=on_background_click,
            )
        ],
        expand=True,
        spacing=0,
        padding=0,
        scroll=ft.ScrollMode.ADAPTIVE,
    )
    if page is not None:
        _register_page_scroll(page, view)
    return view


def set_pill_disabled(btn: ft.Control, disabled: bool) -> None:
    """Update pill button disabled state (Material shows forbidden cursor when disabled)."""
    if isinstance(btn, (ft.FilledButton, ft.OutlinedButton)):
        btn.disabled = disabled


def make_text_field(
    label: str,
    value: str = "",
    *,
    on_change: Callable[[ft.ControlEvent], None] | None = None,
    read_only: bool = False,
    expand: bool = True,
    border_radius: float = 12,
    field_ref: ft.Ref[ft.TextField] | None = None,
) -> ft.Column:
    field = ft.TextField(
        ref=field_ref,
        value=value,
        height=T.FIELD_HEIGHT,
        text_size=T.FONT_BODY,
        text_style=ft.TextStyle(font_family=T.FONT_FAMILY, color=T.TEXT),
        content_padding=ft.Padding.symmetric(horizontal=12, vertical=0),
        border_radius=border_radius,
        filled=True,
        bgcolor=T.SURFACE,
        border_color=T.BORDER,
        focused_border_color=T.FOCUS,
        focused_border_width=2,
        cursor_color=T.BUTTON,
        selection_color=T.SELECTED,
        expand=expand,
        read_only=read_only,
        on_change=on_change,
        on_focus=lambda _: _close_active_select(refresh=False),
    )
    return ft.Column(
        [
            ui_text(label, size=T.FONT_LABEL, color=T.TEXT_MUTED, weight=ft.FontWeight.W_500),
            field,
        ],
        spacing=T.SPACE_LABEL,
        tight=True,
        expand=expand,
    )


def pill_button(
    text: str,
    *,
    primary: bool = False,
    destructive: bool = False,
    on_click=None,
    disabled: bool = False,
) -> ft.Control:
    style = _pill_style(primary=primary, destructive=destructive)
    if primary:
        return ft.FilledButton(
            text,
            disabled=disabled,
            height=BUTTON_HEIGHT,
            style=style,
            on_click=_wrap_click(on_click),
        )
    return ft.OutlinedButton(
        text,
        disabled=disabled,
        height=BUTTON_HEIGHT,
        style=style,
        on_click=_wrap_click(on_click),
    )


def _wrap_click(handler):
    if handler is None:
        return None

    def wrapped(e: ft.ControlEvent) -> None:
        _close_active_select(refresh=False)
        page = None
        try:
            page = e.page
        except RuntimeError:
            pass
        handler(e)
        if page is not None:
            try:
                page.update()
            except RuntimeError:
                pass

    return wrapped


def bind_select_dismiss(handler):
    """Close an open select, then run the control handler (one page.update at the end)."""
    return _wrap_click(handler)


def make_select(
    page: ft.Page,
    label: str,
    options: list[tuple[str, str]],
    value: str,
    on_change=None,
    *,
    menu_height: int | None = None,
    disabled: bool = False,
    option_trailing: Callable[[str], ft.Control | None] | None = None,
) -> ft.Column:
    if menu_height is not None:
        # An explicit height is a ceiling: a short list must not leave an empty tail.
        natural = len(options) * MENU_ITEM_HEIGHT + max(0, len(options) - 1) * 4 + MENU_POPUP_VPAD
        resolved_menu_height: int = min(menu_height, max(natural, MENU_ITEM_HEIGHT + MENU_POPUP_VPAD))
    else:
        resolved_menu_height = _calc_menu_height(len(options))
    menu_content_height = max(MENU_ITEM_HEIGHT, resolved_menu_height - MENU_POPUP_VPAD)

    state: dict[str, object] = {"value": value or "", "open": False, "field_width": None}
    chevron_ref = ft.Ref[ft.Icon]()
    field_ref = ft.Ref[ft.Container]()

    selected_label = next((t for k, t in options if k == state["value"]), "")
    value_text = ui_text(
        selected_label or state["value"] or "Выбрать",
        size=T.FONT_BODY,
        color=T.TEXT if selected_label or state["value"] else T.TEXT_FAINT,
        expand=True,
    )

    menu_col = ft.Column(
        spacing=4,
        tight=True,
        scroll=ft.ScrollMode.ADAPTIVE if len(options) > 6 else None,
        height=menu_content_height,
        horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
    )

    menu_popup = ft.Container(
        content=menu_col,
        bgcolor=T.OVERLAY,
        border=ft.Border.all(1, T.BORDER),
        border_radius=T.RADIUS_L,
        padding=ft.Padding.symmetric(horizontal=MENU_EDGE_INSET, vertical=4),
        height=resolved_menu_height,
        clip_behavior=ft.ClipBehavior.HARD_EDGE,
        visible=False,
        opacity=0,
        scale=ft.Scale(0.95, alignment=ft.Alignment.TOP_CENTER),
        animate_opacity=MENU_IN,
        animate_scale=MENU_IN,
        shadow=menu_shadow(),
    )

    def set_chevron(opened: bool) -> None:
        icon = chevron_ref.current
        if icon is None:
            return
        icon.rotate = ft.Rotate(math.pi if opened else 0, alignment=ft.Alignment.CENTER)

    def set_field_border(opened: bool) -> None:
        field = field_ref.current
        if field is None:
            return
        field.border = ft.Border.all(2 if opened else 1, T.FOCUS if opened else T.BORDER)

    def remove_overlay() -> None:
        if menu_popup in page.overlay:
            page.overlay.remove(menu_popup)

    def _freeze_menu_animations() -> None:
        menu_popup.animate_opacity = None
        menu_popup.animate_scale = None
        menu_popup.opacity = 1

    def _resolve_field_width() -> float:
        field_width = state.get("field_width")
        if isinstance(field_width, (int, float)) and field_width > 0:
            return float(field_width)
        field = field_ref.current
        if field is not None and field.width:
            return float(field.width)
        return 280.0

    def close_menu(*, refresh: bool = True) -> None:
        global _select_scroll_reposition
        if not state["open"]:
            return
        state["open"] = False
        menu_popup.visible = False
        menu_popup.opacity = 0
        menu_popup.shadow = menu_shadow()
        menu_popup.top = None
        menu_popup.bottom = None
        menu_popup.width = None
        menu_popup.animate_opacity = MENU_IN
        menu_popup.animate_scale = MENU_IN
        scale_origin = (
            ft.Alignment.BOTTOM_CENTER
            if state.get("open_upward")
            else ft.Alignment.TOP_CENTER
        )
        menu_popup.scale = ft.Scale(0.95, alignment=scale_origin)
        set_chevron(False)
        set_field_border(False)
        remove_overlay()
        global _active_select_close
        if _active_select_close is close_menu:
            _active_select_close = None
        if _select_scroll_reposition is reposition_menu:
            _select_scroll_reposition = None
        _detach_page_keyboard(page)
        if refresh:
            page.update()

    def _sync_menu_item_widths() -> None:
        width = _resolve_field_width()
        inner = max(0.0, width - 2 * MENU_EDGE_INSET)
        menu_col.width = inner
        content_width = max(0.0, inner - 24)
        for ctrl in menu_col.controls:
            ctrl.width = inner
            content = ctrl.content
            if isinstance(content, ft.Container):
                content.width = content_width

    def _menu_item_content(text: str, trailing_controls: list[ft.Control], *, active: bool) -> ft.Container:
        row_controls: list[ft.Control] = [
            ft.Text(
                text,
                no_wrap=True,
                expand=True,
                overflow=ft.TextOverflow.ELLIPSIS,
                size=T.FONT_BODY,
                color=T.MENU_SELECTED if active else T.TEXT,
                weight=ft.FontWeight.W_600 if active else ft.FontWeight.W_400,
            ),
        ]
        if trailing_controls:
            row_controls.append(
                ft.Row(trailing_controls, spacing=4, tight=True)
            )
        return ft.Container(
            content=ft.Row(
                row_controls,
                spacing=8,
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            expand=True,
        )

    def rebuild_menu() -> None:
        menu_col.controls.clear()
        for key, text in options:
            active = key == state["value"]
            trailing_controls: list[ft.Control] = []
            if option_trailing:
                extra = option_trailing(key)
                if extra is not None:
                    trailing_controls.append(extra)
            elif active:
                trailing_controls.append(
                    ft.Icon(ft.Icons.CHECK, size=16, color=T.ACCENT)
                )
            item = ft.MenuItemButton(
                content=_menu_item_content(text, trailing_controls, active=active),
                height=MENU_ITEM_HEIGHT,
                style=_select_menu_item_style(selected=active),
                on_click=lambda _e, k=key, t=text: choose(k, t),
            )
            menu_col.controls.append(item)

    def _apply_overlay_position(
        field_top: float,
        field_left: float,
        open_upward: bool,
    ) -> bool:
        menu_height = float(state.get("anchor_menu_height", 0))
        content_bottom = _content_bottom(page)
        if (
            not open_upward
            and field_top + T.FIELD_HEIGHT + MENU_GAP + menu_height > content_bottom - 4
            and field_top - MENU_GAP >= menu_height
        ):
            open_upward = True

        if open_upward:
            top = max(4.0, field_top - menu_height - MENU_GAP)
        else:
            top = field_top + T.FIELD_HEIGHT + MENU_GAP
            if top + menu_height > content_bottom - 4:
                top = max(4.0, content_bottom - menu_height - 4)

        menu_popup.bottom = None
        menu_popup.top = top
        menu_popup.left = field_left
        return open_upward

    def reposition_menu(scroll_pixels: float) -> None:
        if not state.get("open"):
            return
        delta = scroll_pixels - float(state.get("anchor_scroll", 0))
        field_top = float(state["anchor_field_top"]) - delta
        field_left = float(state["anchor_field_left"])
        open_upward = bool(state.get("open_upward"))
        state["open_upward"] = _apply_overlay_position(field_top, field_left, open_upward)
        _raise_menu_overlay(page, menu_popup)
        if menu_popup.page:
            menu_popup.update()

    def _menu_position(e: ft.TapEvent) -> tuple[float, float, bool, float] | None:
        global_coords = _global_from_tap(e)
        if global_coords is None:
            return None

        field_left, field_top = global_coords
        menu_height = _placement_menu_height(len(options), resolved_menu_height)
        content_bottom = _content_bottom(page)
        open_upward = _should_open_upward(field_top, menu_height, content_bottom)
        return field_left, field_top, open_upward, menu_height

    def open_menu(e: ft.TapEvent) -> None:
        global _select_scroll_reposition
        _close_active_select(refresh=False)
        rebuild_menu()
        placement = _menu_position(e)
        if placement is None:
            return
        field_left, field_top, open_upward, menu_height = placement
        # Меню не выходит за окно: на нехватку места оно становится ниже и прокручивается.
        content_bottom = _content_bottom(page)
        if open_upward:
            room = field_top - MENU_GAP - 4
        else:
            room = content_bottom - (field_top + T.FIELD_HEIGHT + MENU_GAP) - 4
        fitted = min(menu_height, max(float(2 * MENU_ITEM_HEIGHT + MENU_POPUP_VPAD), room))
        menu_popup.height = fitted
        menu_col.height = max(MENU_ITEM_HEIGHT, fitted - MENU_POPUP_VPAD)
        menu_col.scroll = ft.ScrollMode.ADAPTIVE if fitted < menu_height or len(options) > 6 else None
        menu_height = fitted
        state["anchor_field_top"] = field_top
        state["anchor_field_left"] = field_left
        state["anchor_scroll"] = getattr(page, "_tigo_page_scroll_offset", 0) or 0
        state["anchor_menu_height"] = menu_height
        open_upward = _apply_overlay_position(field_top, field_left, open_upward)
        scale_origin = (
            ft.Alignment.BOTTOM_CENTER if open_upward else ft.Alignment.TOP_CENTER
        )
        menu_popup.width = _resolve_field_width()
        _sync_menu_item_widths()
        menu_popup.animate_opacity = MENU_IN
        menu_popup.animate_scale = MENU_IN
        menu_popup.visible = True
        menu_popup.opacity = 0
        menu_popup.shadow = menu_shadow()
        menu_popup.scale = ft.Scale(0.95, alignment=scale_origin)
        state["open"] = True
        state["open_upward"] = open_upward
        set_chevron(True)
        set_field_border(True)

        remove_overlay()
        _raise_menu_overlay(page, menu_popup)

        global _active_select_close
        _active_select_close = close_menu
        _select_scroll_reposition = reposition_menu

        _attach_page_keyboard(page)
        page.update()

        async def reveal() -> None:
            await asyncio.sleep(0.05)
            if not state.get("open"):
                return
            menu_popup.animate_opacity = MENU_IN
            menu_popup.animate_scale = MENU_IN
            menu_popup.opacity = 1
            menu_popup.scale = ft.Scale(1, alignment=scale_origin)
            try:
                menu_popup.update()
            except RuntimeError:
                return
            await asyncio.sleep(0.32)
            if state.get("open"):
                _freeze_menu_animations()

        page.run_task(reveal)

    def on_field_tap(e: ft.TapEvent) -> None:
        if disabled:
            return
        if state["open"]:
            close_menu()
        else:
            open_menu(e)

    def choose(key: str, text: str) -> None:
        state["value"] = key
        value_text.value = text
        value_text.color = T.TEXT
        close_menu(refresh=False)
        page.update()
        if on_change:
            on_change(key)

    def on_field_size(e: ft.LayoutSizeChangeEvent) -> None:
        if e.width > 0:
            state["field_width"] = e.width

    chevron = ft.Icon(
        ft.Icons.EXPAND_MORE,
        ref=chevron_ref,
        color=T.TEXT_MUTED,
        size=18,
        animate_rotation=CHEVRON_ANIM,
        rotate=ft.Rotate(0, alignment=ft.Alignment.CENTER),
    )

    field = ft.Container(
        ref=field_ref,
        content=ft.Row(
            [value_text, chevron],
            spacing=8,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        height=T.FIELD_HEIGHT,
        bgcolor=T.SURFACE,
        border=ft.Border.all(1, T.BORDER),
        border_radius=T.RADIUS,
        padding=ft.Padding.symmetric(horizontal=12, vertical=0),
        on_size_change=on_field_size,
        opacity=0.72 if disabled else 1.0,
    )

    rebuild_menu()

    return ft.Column(
        [
            ui_text(label, size=T.FONT_LABEL, color=T.TEXT_MUTED, weight=ft.FontWeight.W_500),
            ft.GestureDetector(
                content=field,
                on_tap=on_field_tap,
            ),
        ],
        spacing=T.SPACE_LABEL,
        tight=True,
    )


def _log_panel(content: ft.Control, *, height: int) -> ft.Container:
    return ft.Container(
        content=content,
        bgcolor=T.SUNKEN,
        border=ft.Border.all(1, T.BORDER),
        border_radius=T.RADIUS,
        padding=12,
        height=height,
        expand=True,
        clip_behavior=ft.ClipBehavior.HARD_EDGE,
    )


def _refresh_control(control: ft.Control) -> None:
    """Update a control only when it is mounted on the page."""
    if not getattr(control, "page", None):
        return
    try:
        control.update()
    except RuntimeError as exc:
        if "must be added to the page first" not in str(exc):
            raise


def test_log_console(page: ft.Page) -> tuple[ft.Container, Callable[[], None]]:
    """Read-only colored log for strategy testing."""
    from src.modules.strategy_testing import journal as tls

    log_text = ft.Text(
        spans=[],
        size=T.FONT_CAPTION,
        color=T.TEXT,
        font_family=T.FONT_MONO,
        selectable=True,
    )

    log_column = ft.Column(
        [log_text],
        expand=True,
        scroll=ft.ScrollMode.ALWAYS,
    )

    def _build_spans() -> list[ft.TextSpan]:
        lines = tls.get_lines()
        if not lines:
            return [
                ft.TextSpan(
                    " ",
                    style=ft.TextStyle(
                        color=T.TEXT_MUTED,
                        font_family=T.FONT_MONO,
                        size=T.FONT_CAPTION,
                    ),
                )
            ]
        layout = tls.compute_table_layout(lines)
        spans: list[ft.TextSpan] = []
        mono = ft.TextStyle(font_family=T.FONT_MONO, size=T.FONT_CAPTION)
        for index, line in enumerate(lines):
            if index:
                spans.append(ft.TextSpan("\n", style=mono))
            for chunk, color in tls.line_text_spans(line, layout=layout):
                if not chunk:
                    continue
                spans.append(
                    ft.TextSpan(
                        chunk,
                        style=ft.TextStyle(color=color, font_family=T.FONT_MONO, size=T.FONT_CAPTION),
                    )
                )
        return spans

    def rebuild() -> None:
        log_text.value = ""
        log_text.spans = _build_spans()
        _refresh_control(log_text)

    tls.subscribe(rebuild)

    def unsubscribe() -> None:
        tls.unsubscribe(rebuild)

    return (
        _log_panel(
            ft.SelectionArea(content=log_column),
            height=LOG_PANEL_HEIGHT_TEST,
        ),
        unsubscribe,
    )

section = block_section
