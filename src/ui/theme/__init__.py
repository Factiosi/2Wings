"""Схема Tigo на Factiosi Umbrae. Числа — из umbrae.py (копия сборки Factiosi), второй палитры нет."""

from __future__ import annotations

import re
from typing import Literal, TypedDict

from src.ui.theme.umbrae import DARK as _UMBRAE_DARK
from src.ui.theme.umbrae import LIGHT as _UMBRAE_LIGHT
from src.ui.theme.umbrae import px

ThemeMode = Literal["dark", "light"]
# Поле settings.json со старых сборок. На экран не влияет: акцент Factiosi один — фиолетовый.
PortalHue = Literal[
    "purple",
    "green",
    "blue",
    "burgundy",
    "yellow",
    "brown",
    "orange",
    "mono",
]

_UMBRAE = {"dark": _UMBRAE_DARK, "light": _UMBRAE_LIGHT}
_RGB = re.compile(r"rgba?\(\s*(\d+)[ ,]+(\d+)[ ,]+(\d+)\s*(?:[/,]\s*([\d.]+))?\s*\)")


def flet_color(value: str) -> str:
    """Цвет токена (#rrggbb или rgb(r g b / a)) -> #AARRGGBB для Flet."""
    match = _RGB.fullmatch(value.strip())
    if not match:
        return value
    red, green, blue = (int(match.group(i)) for i in (1, 2, 3))
    alpha = float(match.group(4)) if match.group(4) else 1.0
    return f"#{round(alpha * 255):02x}{red:02x}{green:02x}{blue:02x}"


def argb(hex_color: str, alpha: int) -> str:
    """Flet берёт #AARRGGBB. Альфа в конце превращает цвет кнопки в оливковый."""
    return f"#{alpha:02x}{hex_color.removeprefix('#')}"


def ink(hex_color: str) -> str:
    """Чёрный или белый текст по яркости фона плашки."""
    raw = hex_color.removeprefix("#")
    red, green, blue = int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16)
    luminance = 0.2126 * red + 0.7152 * green + 0.0722 * blue
    return "#000000" if luminance > 150 else "#ffffff"


class PortalPalette(TypedDict):
    id: str
    mode: ThemeMode
    ground: str
    surface: str
    elevated: str
    overlay: str
    sunken: str
    accent: str
    accent_dim: str
    accent_soft: str
    overlay_hover: str
    selected: str
    text: str
    text_muted: str
    text_faint: str
    border: str
    border_strong: str
    button: str
    on_button: str
    focus: str
    success: str
    warning: str
    error: str
    success_bg: str
    warning_bg: str
    error_bg: str
    rail_active_bg: str
    rail_active_edge: str
    rail_sheen: str


def get_palette(*, mode: ThemeMode = "dark", hue: str | None = None) -> PortalPalette:
    del hue  # акцент дома один — фиолетовый Umbrae
    u = _UMBRAE[mode]
    return {
        "id": f"umbrae-{mode}",
        "mode": mode,
        "ground": u["surface-page"],
        "surface": u["surface-card"],
        "elevated": u["surface-raised"],
        "overlay": u["surface-card"],
        "sunken": u["surface-sunken"],
        "accent": u["action-primary"],
        "accent_dim": u["action-primary-active"],
        "accent_soft": argb(u["action-primary"], 0x1F),
        "overlay_hover": u["action-secondary-hover"],
        "selected": u["interactive-selected-bg"],
        "text": u["text-primary"],
        "text_muted": u["text-secondary"],
        "text_faint": u["text-tertiary"],
        "border": u["border-default"],
        "border_strong": u["border-strong"],
        "button": u["action-primary"],
        "on_button": u["text-on-action"],
        "focus": u["border-focus"],
        "success": u["feedback-success-text"],
        "warning": u["feedback-warning-text"],
        "error": u["feedback-error-text"],
        "success_bg": u["feedback-success-bg"],
        "warning_bg": u["feedback-warning-bg"],
        "error_bg": u["feedback-error-bg"],
        "rail_active_bg": flet_color(u["umbrae-rail-active-bg"]),
        "rail_active_edge": flet_color(u["umbrae-rail-active-edge"]),
        "rail_sheen": flet_color(u["umbrae-rail-sheen"]),
    }


DEFAULT_THEME_MODE: ThemeMode = "dark"


class ThemeTokens:
    def __init__(self, palette: PortalPalette) -> None:
        self._p = palette
        self.mode = palette["mode"]
        self.hue = "umbrae"

        self.GROUND = palette["ground"]
        self.SURFACE = palette["surface"]
        self.ELEVATED = palette["elevated"]
        self.OVERLAY = palette["overlay"]
        self.SUNKEN = palette["sunken"]
        self.ACCENT = palette["accent"]
        self.ACCENT_DIM = palette["accent_dim"]
        self.ACCENT_SOFT = palette["accent_soft"]
        self.OVERLAY_HOVER = palette["overlay_hover"]
        self.SELECTED = palette["selected"]
        self.MENU_SELECTED = palette["button"]
        self.TEXT = palette["text"]
        self.TEXT_MUTED = palette["text_muted"]
        self.TEXT_FAINT = palette["text_faint"]
        self.BORDER = palette["border"]
        self.BORDER_STRONG = palette["border_strong"]
        self.BUTTON = palette["button"]
        self.ON_BUTTON = palette["on_button"]
        self.ON_ACCENT = palette["ground"] if self.mode == "dark" else "#ffffff"
        self.FOCUS = palette["focus"]

        self.PURPLE = self.ACCENT
        self.PURPLE_DIM = self.ACCENT_DIM
        self.PURPLE_SOFT = self.ACCENT_SOFT

        self.STATUS_ACTIVE = palette["success"]
        self.STATUS_ACTIVE_BG = palette["success_bg"]
        self.STATUS_CONNECTING = palette["button"]
        self.STATUS_CONNECTING_BG = palette["selected"]
        self.STATUS_EXPIRING = palette["warning"]
        self.STATUS_EXPIRING_BG = palette["warning_bg"]
        self.STATUS_ERROR = palette["error"]
        self.STATUS_ERROR_BG = palette["error_bg"]
        self.STATUS_OFFLINE = palette["text_faint"]
        self.STATUS_OFFLINE_BG = palette["sunken"]
        self.TRACK_OFF = palette["border_strong"]
        # Рельс Umbrae: активный пункт — плашка с обводкой, по ней раз в период проходит блик.
        self.RAIL_ACTIVE_BG = palette["rail_active_bg"]
        self.RAIL_ACTIVE_EDGE = palette["rail_active_edge"]
        self.RAIL_SHEEN = palette["rail_sheen"]
        self.RAIL_SHEEN_PERIOD = px("umbrae-rail-sheen-period")
        self.HOVER_SCRIM = "#29000000" if self.mode == "dark" else "#29ffffff"
        self.PRESS_SCRIM = "#47000000" if self.mode == "dark" else "#47ffffff"
        self.OUTLINE_HOVER = argb(palette["button"], 0x1A)

        self.FONT_FAMILY = "Segoe UI"
        self.FONT_DISPLAY = "Cormorant"
        self.FONT_UI = "Inter"
        self.FONT_MONO = "JetBrains Mono"
        self.FONT_BODY = 14
        self.FONT_LABEL = 14
        self.FONT_CAPTION = px("text-2xs")
        self.FONT_TITLE = px("text-2xl")
        self.FONT_SECTION = px("text-md")

        self.SPACE_LABEL = 4
        self.SPACE_FIELD = 16
        self.SPACE_SECTION = 16
        self.SPACE_ROW = 12
        self.FIELD_HEIGHT = px("size-control-lg")
        self.BUTTON_HEIGHT = px("size-control-lg")
        self.CONTROL_SLOT = px("size-control-lg")
        # Одна роль — один радиус (Factiosi Umbrae): контрол и карточка 6, панель и меню 8, бейдж 4.
        self.RADIUS = px("radius-button")
        self.RADIUS_L = px("radius-panel")
        # Пилюль в Umbrae нет: бывшие капсулы кнопок — обычный радиус контрола.
        self.RADIUS_PILL = px("radius-button")
        self.RADIUS_BADGE = px("radius-badge")
        self.RADIUS_TOGGLE = px("radius-toggle")
        self.RADIUS_CHECKBOX = px("radius-checkbox")
        self.SECTION_PAD = px("space-card-padding-sm")
        self.SHADOW = flet_color(_UMBRAE[self.mode]["effect-shadow"])

        self.SIDEBAR_WIDTH = px("size-layout-sidebar")
        self.RAIL_EDGE = px("space-rail-edge")
        self.RAIL_ITEM_GAP = px("space-rail-item")


def build_theme_tokens(mode: ThemeMode = DEFAULT_THEME_MODE, hue: str | None = None) -> ThemeTokens:
    return ThemeTokens(get_palette(mode=mode, hue=hue))


_active_tokens = build_theme_tokens(DEFAULT_THEME_MODE)


class ThemeProxy:
    """Stable import target; always reflects the active token set."""

    def __getattr__(self, name: str):
        return getattr(_active_tokens, name)

    def __repr__(self) -> str:
        return f"ThemeProxy(mode={_active_tokens.mode!r})"


T = ThemeProxy()


def apply_theme(mode: ThemeMode, hue: str | None = None) -> ThemeTokens:
    global _active_tokens
    _active_tokens = build_theme_tokens(mode, hue)
    return _active_tokens


def set_theme_mode(mode: ThemeMode) -> ThemeTokens:
    return apply_theme(mode)


def build_flet_theme(tokens: ThemeTokens):
    """Build a Flet Theme for the given token set (light or dark)."""
    import flet as ft

    menu_item_style = ft.ButtonStyle(
        shape=ft.RoundedRectangleBorder(radius=tokens.RADIUS),
        color=tokens.TEXT,
        overlay_color={
            ft.ControlState.HOVERED: tokens.OVERLAY_HOVER,
            ft.ControlState.FOCUSED: tokens.OVERLAY_HOVER,
            ft.ControlState.PRESSED: tokens.OVERLAY_HOVER,
        },
        bgcolor={
            ft.ControlState.SELECTED: tokens.SELECTED,
        },
        padding=ft.Padding.symmetric(horizontal=16, vertical=8),
        visual_density=ft.VisualDensity.COMPACT,
    )
    outlined_style = ft.ButtonStyle(
        color=tokens.BUTTON,
        overlay_color={
            ft.ControlState.HOVERED: tokens.OUTLINE_HOVER,
            ft.ControlState.FOCUSED: tokens.OUTLINE_HOVER,
            ft.ControlState.PRESSED: tokens.OUTLINE_HOVER,
        },
        shape=ft.RoundedRectangleBorder(radius=tokens.RADIUS_PILL),
        padding=ft.Padding.symmetric(horizontal=12, vertical=12),
        text_style=ft.TextStyle(
            size=tokens.FONT_BODY,
            font_family=tokens.FONT_UI,
            weight=ft.FontWeight.W_600,
        ),
    )
    filled_style = ft.ButtonStyle(
        bgcolor=tokens.BUTTON,
        color=tokens.ON_BUTTON,
        overlay_color={
            ft.ControlState.HOVERED: tokens.HOVER_SCRIM,
            ft.ControlState.FOCUSED: tokens.HOVER_SCRIM,
            ft.ControlState.PRESSED: tokens.PRESS_SCRIM,
        },
        shape=ft.RoundedRectangleBorder(radius=tokens.RADIUS_PILL),
        padding=ft.Padding.symmetric(horizontal=12, vertical=12),
        text_style=ft.TextStyle(
            size=tokens.FONT_BODY,
            font_family=tokens.FONT_UI,
            weight=ft.FontWeight.W_600,
        ),
    )
    menu_style = ft.MenuStyle(
        bgcolor=tokens.OVERLAY,
        elevation=8,
        shadow_color="#54000000" if tokens.mode == "dark" else "#14000000",
        shape=ft.RoundedRectangleBorder(radius=tokens.RADIUS_L),
        side=ft.BorderSide(1, tokens.BORDER),
        padding=4,
    )

    return ft.Theme(
        color_scheme=ft.ColorScheme(
            primary=tokens.BUTTON,
            on_primary=tokens.ON_BUTTON,
            primary_container=tokens.SELECTED,
            on_primary_container=tokens.BUTTON,
            secondary=tokens.ACCENT,
            on_secondary=tokens.ON_ACCENT,
            surface=tokens.SURFACE,
            on_surface=tokens.TEXT,
            on_surface_variant=tokens.TEXT_MUTED,
            outline=tokens.BORDER,
            outline_variant=tokens.BORDER_STRONG,
            error=tokens.STATUS_ERROR,
            on_error=tokens.ON_BUTTON,
            surface_container_highest=tokens.OVERLAY,
        ),
        font_family=tokens.FONT_FAMILY,
        text_theme=ft.TextTheme(
            body_large=ft.TextStyle(
                size=tokens.FONT_BODY, font_family=tokens.FONT_FAMILY, color=tokens.TEXT
            ),
            body_medium=ft.TextStyle(
                size=tokens.FONT_BODY, font_family=tokens.FONT_FAMILY, color=tokens.TEXT
            ),
            body_small=ft.TextStyle(
                size=tokens.FONT_CAPTION, font_family=tokens.FONT_FAMILY, color=tokens.TEXT_MUTED
            ),
            label_large=ft.TextStyle(
                size=tokens.FONT_BODY, font_family=tokens.FONT_UI, color=tokens.TEXT, weight=ft.FontWeight.W_600
            ),
            label_medium=ft.TextStyle(
                size=tokens.FONT_CAPTION, font_family=tokens.FONT_FAMILY, color=tokens.TEXT_MUTED
            ),
            title_large=ft.TextStyle(
                size=tokens.FONT_TITLE, font_family=tokens.FONT_DISPLAY, color=tokens.TEXT, weight=ft.FontWeight.W_600
            ),
        ),
        splash_color="#00000000",
        hover_color=tokens.OVERLAY_HOVER,
        highlight_color=tokens.OVERLAY_HOVER,
        focus_color=tokens.FOCUS,
        scaffold_bgcolor=tokens.GROUND,
        canvas_color=tokens.GROUND,
        checkbox_theme=ft.CheckboxTheme(
            fill_color={
                ft.ControlState.SELECTED: tokens.BUTTON,
                ft.ControlState.DEFAULT: tokens.SURFACE,
            },
            check_color=tokens.ON_BUTTON,
            overlay_color={
                ft.ControlState.HOVERED: "#00000000",
                ft.ControlState.FOCUSED: "#00000000",
                ft.ControlState.PRESSED: "#00000000",
            },
        ),
        radio_theme=ft.RadioTheme(
            fill_color={
                ft.ControlState.SELECTED: tokens.BUTTON,
                ft.ControlState.DEFAULT: tokens.BORDER_STRONG,
            },
            overlay_color={
                ft.ControlState.HOVERED: "#00000000",
                ft.ControlState.FOCUSED: "#00000000",
                ft.ControlState.PRESSED: "#00000000",
            },
        ),
        popup_menu_theme=ft.PopupMenuTheme(
            color=tokens.OVERLAY,
            shadow_color="#54000000" if tokens.mode == "dark" else "#14000000",
            icon_color=tokens.TEXT_MUTED,
            label_text_style=ft.TextStyle(color=tokens.TEXT, size=tokens.FONT_BODY, font_family=tokens.FONT_FAMILY),
            elevation=8,
            shape=ft.RoundedRectangleBorder(radius=tokens.RADIUS_L),
            menu_padding=4,
        ),
        dropdown_theme=ft.DropdownTheme(
            menu_style=menu_style,
            text_style=ft.TextStyle(color=tokens.TEXT, size=tokens.FONT_BODY, font_family=tokens.FONT_FAMILY),
        ),
        text_button_theme=ft.TextButtonTheme(style=menu_item_style),
        outlined_button_theme=ft.OutlinedButtonTheme(style=outlined_style),
        filled_button_theme=ft.FilledButtonTheme(style=filled_style),
    )
