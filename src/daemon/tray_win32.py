"""Win32 tray icon whose native menu follows the Windows theme and shows Lucide icons."""

from __future__ import annotations

import ctypes
import sys
import winreg
from ctypes import wintypes

import pystray
from PIL import Image

if sys.platform != "win32":
    raise RuntimeError("Win32 tray icons are only supported on Windows.")

from pystray._util import win32

from src.core.branding import load_tray_menu_icon

# Unnamed exports of uxtheme.dll: the only way to get a dark native menu in a Win32
# program. Present since Windows 10 1903; on older systems the menu simply stays light.
_ALLOW_DARK_FOR_WINDOW = 133
_SET_PREFERRED_APP_MODE = 135
_FLUSH_MENU_THEMES = 136
_APP_MODE_ALLOW_DARK = 1
_SM_CXMENUCHECK = 71
_DISABLED_ICON_ALPHA = 0.4

_gdi32 = ctypes.windll.gdi32
_gdi32.CreateDIBSection.restype = wintypes.HBITMAP
_gdi32.CreateDIBSection.argtypes = [
    wintypes.HDC,
    ctypes.c_void_p,
    wintypes.UINT,
    ctypes.POINTER(ctypes.c_void_p),
    wintypes.HANDLE,
    wintypes.DWORD,
]
_gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


def _uxtheme_call(ordinal: int, *args) -> None:
    try:
        ctypes.WinDLL("uxtheme")[ordinal](*args)
    except (AttributeError, OSError, ValueError):
        pass


def windows_uses_dark_apps() -> bool:
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
        ) as key:
            return winreg.QueryValueEx(key, "AppsUseLightTheme")[0] == 0
    except OSError:
        return False


def pil_to_hbitmap(image: Image.Image) -> int:
    """32-bit premultiplied bitmap: the form in which a native menu honours transparency."""
    premultiplied = image.convert("RGBa")
    width, height = premultiplied.size
    header = _BITMAPINFOHEADER()
    header.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
    header.biWidth = width
    header.biHeight = -height  # top-down
    header.biPlanes = 1
    header.biBitCount = 32
    bits = ctypes.c_void_p()
    hbitmap = _gdi32.CreateDIBSection(None, ctypes.byref(header), 0, ctypes.byref(bits), None, 0)
    if not hbitmap:
        raise OSError("CreateDIBSection failed")
    raw = premultiplied.tobytes("raw", "BGRa")
    ctypes.memmove(bits, raw, len(raw))
    return hbitmap


def menu_item(text: str, action, *, icon: str | None = None, **kwargs) -> pystray.MenuItem:
    """Tray menu item with an optional Lucide icon, by name."""
    item = pystray.MenuItem(text, action, **kwargs)
    item.menu_icon = icon
    return item


class TwoWingsTrayIcon(pystray._win32.Icon):
    WM_LBUTTONDBLCLK = 0x0203

    def __init__(self, *args, on_double_click=None, **kwargs) -> None:
        _uxtheme_call(_SET_PREFERRED_APP_MODE, _APP_MODE_ALLOW_DARK)
        self._menu_bitmaps: list[int] = []
        self._menu_dark = windows_uses_dark_apps()
        super().__init__(*args, **kwargs)
        self._on_double_click = on_double_click

    def _on_notify(self, wparam, lparam):
        if lparam == self.WM_LBUTTONDBLCLK and self._on_double_click is not None:
            self._on_double_click(self, None)
            return
        if lparam == win32.WM_LBUTTONUP:
            return
        if lparam == win32.WM_RBUTTONUP:
            # pystray creates its windows only on run. The flush picks up a change of
            # the Windows theme since the menu was last opened; icons follow it.
            _uxtheme_call(_ALLOW_DARK_FOR_WINDOW, ctypes.c_void_p(self._menu_hwnd), True)
            _uxtheme_call(_FLUSH_MENU_THEMES)
            if windows_uses_dark_apps() != self._menu_dark:
                self._update_menu()
        super()._on_notify(wparam, lparam)

    def _release_menu_bitmaps(self) -> None:
        for hbitmap in self._menu_bitmaps:
            _gdi32.DeleteObject(hbitmap)
        self._menu_bitmaps.clear()

    def _update_menu(self) -> None:
        self._menu_dark = windows_uses_dark_apps()
        self._release_menu_bitmaps()
        super()._update_menu()

    def _create_menu_item(self, descriptor, callbacks):
        item = super()._create_menu_item(descriptor, callbacks)
        name = getattr(descriptor, "menu_icon", None)
        image = name and load_tray_menu_icon(
            name, dark=self._menu_dark, size=ctypes.windll.user32.GetSystemMetrics(_SM_CXMENUCHECK)
        )
        if image:
            if not descriptor.enabled:
                image.putalpha(image.getchannel("A").point(lambda value: int(value * _DISABLED_ICON_ALPHA)))
            hbitmap = pil_to_hbitmap(image)
            self._menu_bitmaps.append(hbitmap)
            item.fMask |= win32.MIIM_BITMAP
            item.hbmpItem = hbitmap
        return item

    def stop(self) -> None:
        self._release_menu_bitmaps()
        super().stop()
