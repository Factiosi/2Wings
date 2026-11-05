"""Окно TwoWingsUpdate в духе Fluent: заголовок, подпись этапа и тонкая шкала WinUI.

Чистый Win32 и GDI+ без библиотек интерфейса: программа должна оставаться маленькой.
Рамка обычная, от Windows. Тема и акцент берутся из системы, шрифт системный.
"""

from __future__ import annotations

import ctypes
import math
import sys
import time
import winreg
from ctypes import wintypes
from pathlib import Path

from src.update_splash.worker import State, Worker

if sys.platform != "win32":
    raise RuntimeError("TwoWingsUpdate работает только в Windows.")

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_gdi32 = ctypes.WinDLL("gdi32")
_kernel32 = ctypes.WinDLL("kernel32")
_dwmapi = ctypes.WinDLL("dwmapi")
_gdip = ctypes.WinDLL("gdiplus")

# Окно в логических пикселях: шкала DPI применяется при рисовании.
_W, _H = 460, 176
_PAD = 24.0
_FRAME_MS = 16
_CLOSE_AFTER_DONE_S = 1.6
_INDETERMINATE_PERIOD_S = 2.0
_ERROR_HEIGHT = 236

_WS_CAPTION = 0x00C00000
_WS_SYSMENU = 0x00080000
_WS_MINIMIZEBOX = 0x00020000
_WINDOW_STYLE = _WS_CAPTION | _WS_SYSMENU | _WS_MINIMIZEBOX
_SWP_NOMOVE = 0x0002
_SWP_NOZORDER = 0x0004
APP_TITLE = "2Wings"
_WM_DESTROY = 0x0002
_WM_PAINT = 0x000F
_WM_CLOSE = 0x0010
_WM_ERASEBKGND = 0x0014
_WM_SETICON = 0x0080
_WM_TIMER = 0x0113
_WM_MOUSEMOVE = 0x0200
_WM_LBUTTONUP = 0x0202
_SRCCOPY = 0x00CC0020


# Палитра WinUI; окно живёт отдельно от Qt и не тянет библиотек интерфейса.
_DARK = {
    "page": 0x202020,
    "text": 0xffffff,
    "text-secondary": 0xc5c5c5,
    "track": 0x5a5a5a,
    "button": 0x2d2d2d,
    "button-hover": 0x323232,
    "button-border": 0x3d3d3d,
    "error": 0xff99a4,
}
_LIGHT = {
    "page": 0xf3f3f3,
    "text": 0x1a1a1a,
    "text-secondary": 0x5c5c5c,
    "track": 0x8a8a8a,
    "button": 0xfbfbfb,
    "button-hover": 0xf6f6f6,
    "button-border": 0xd0d0d0,
    "error": 0xc42b1c,
}
_FALLBACK_ACCENT = 0x005fb8


def _read_personalization(path: str, name: str) -> int | None:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as key:
            return int(winreg.QueryValueEx(key, name)[0])
    except (OSError, ValueError):
        return None


def _system_palette() -> tuple[bool, dict[str, int]]:
    """(тема тёмная, цвета). Акцент как его задал пользователь Windows."""
    light = _read_personalization(r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize", "AppsUseLightTheme")
    dark = light == 0
    abgr = _read_personalization(r"Software\Microsoft\Windows\DWM", "AccentColor")
    accent = _FALLBACK_ACCENT
    if abgr is not None:
        accent = ((abgr & 0xFF) << 16) | (abgr & 0xFF00) | ((abgr >> 16) & 0xFF)
    r, g, b = (accent >> 16) & 0xFF, (accent >> 8) & 0xFF, accent & 0xFF
    bright = 0.2126 * r + 0.7152 * g + 0.0722 * b
    if dark and bright < 110:
        # Тёмный акцент теряется на тёмном фоне: WinUI берёт его светлый оттенок.
        r, g, b = (min(255, c + (255 - c) // 2) for c in (r, g, b))
    elif not dark and bright > 150:
        r, g, b = (c * 3 // 5 for c in (r, g, b))
    return dark, {**(_DARK if dark else _LIGHT), "accent": (r << 16) | (g << 8) | b}


_IS_DARK, _COLORS = _system_palette()


def _argb(token: str, alpha: float = 1.0) -> int:
    return (round(alpha * 255) << 24) | _COLORS[token]


def _asset(name: str) -> Path | None:
    """Рядом с exe в сборке, в assets репозитория при запуске из исходников."""
    exe_dir = Path(sys.executable).resolve().parent
    repo = Path(__file__).resolve().parents[2] / "assets"
    for candidate in (exe_dir / name, repo / "icons" / name):
        if candidate.is_file():
            return candidate
    return None


class _RectF(ctypes.Structure):
    _fields_ = [("x", ctypes.c_float), ("y", ctypes.c_float), ("w", ctypes.c_float), ("h", ctypes.c_float)]


class _StartupInput(ctypes.Structure):
    _fields_ = [
        ("version", ctypes.c_uint32),
        ("callback", ctypes.c_void_p),
        ("suppress_thread", wintypes.BOOL),
        ("suppress_codecs", wintypes.BOOL),
    ]


class _Paint(ctypes.Structure):
    _fields_ = [
        ("hdc", wintypes.HDC),
        ("erase", wintypes.BOOL),
        ("rc", wintypes.RECT),
        ("restore", wintypes.BOOL),
        ("inc_update", wintypes.BOOL),
        ("reserved", ctypes.c_byte * 32),
    ]


class _WndClass(ctypes.Structure):
    _fields_ = [
        ("style", wintypes.UINT),
        ("wndproc", ctypes.c_void_p),
        ("cls_extra", ctypes.c_int),
        ("wnd_extra", ctypes.c_int),
        ("instance", wintypes.HINSTANCE),
        ("icon", wintypes.HICON),
        ("cursor", wintypes.HANDLE),
        ("background", wintypes.HBRUSH),
        ("menu", wintypes.LPCWSTR),
        ("class_name", wintypes.LPCWSTR),
    ]


_WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
_P = ctypes.c_void_p
_F = ctypes.c_float
_user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
_user32.DefWindowProcW.restype = ctypes.c_ssize_t
_user32.CreateWindowExW.restype = wintypes.HWND
_user32.CreateWindowExW.argtypes = [
    wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, _P,
]
_user32.BeginPaint.restype = wintypes.HDC
_user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
_user32.AdjustWindowRectExForDpi.argtypes = [ctypes.POINTER(wintypes.RECT), wintypes.DWORD, wintypes.BOOL, wintypes.DWORD, wintypes.UINT]
_gdi32.CreateCompatibleDC.restype = wintypes.HDC
_gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
_gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
_gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
_gdi32.SelectObject.restype = wintypes.HGDIOBJ
_gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
_gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
_gdi32.DeleteDC.argtypes = [wintypes.HDC]
_gdi32.BitBlt.argtypes = [wintypes.HDC] + [ctypes.c_int] * 4 + [wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.DWORD]
_kernel32.GetModuleHandleW.restype = wintypes.HMODULE
_user32.LoadImageW.restype = wintypes.HANDLE
_user32.LoadImageW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT, ctypes.c_int, ctypes.c_int, wintypes.UINT]

for _name, _args in {
    "GdiplusStartup": [ctypes.POINTER(ctypes.c_size_t), ctypes.POINTER(_StartupInput), _P],
    "GdipCreateFromHDC": [wintypes.HDC, ctypes.POINTER(_P)],
    "GdipDeleteGraphics": [_P],
    "GdipSetSmoothingMode": [_P, ctypes.c_int],
    "GdipSetTextRenderingHint": [_P, ctypes.c_int],
    "GdipSetInterpolationMode": [_P, ctypes.c_int],
    "GdipSetPixelOffsetMode": [_P, ctypes.c_int],
    "GdipScaleWorldTransform": [_P, _F, _F, ctypes.c_int],
    "GdipGraphicsClear": [_P, ctypes.c_uint32],
    "GdipCreateSolidFill": [ctypes.c_uint32, ctypes.POINTER(_P)],
    "GdipDeleteBrush": [_P],
    "GdipCreatePen1": [ctypes.c_uint32, _F, ctypes.c_int, ctypes.POINTER(_P)],
    "GdipDeletePen": [_P],
    "GdipCreatePath": [ctypes.c_int, ctypes.POINTER(_P)],
    "GdipAddPathArc": [_P, _F, _F, _F, _F, _F, _F],
    "GdipClosePathFigure": [_P],
    "GdipDeletePath": [_P],
    "GdipFillPath": [_P, _P, _P],
    "GdipDrawPath": [_P, _P, _P],
    "GdipDrawLine": [_P, _P, _F, _F, _F, _F],
    "GdipLoadImageFromFile": [wintypes.LPCWSTR, ctypes.POINTER(_P)],
    "GdipDrawImageRect": [_P, _P, _F, _F, _F, _F],
    "GdipCreateFontFamilyFromName": [wintypes.LPCWSTR, _P, ctypes.POINTER(_P)],
    "GdipCreateFont": [_P, _F, ctypes.c_int, ctypes.c_int, ctypes.POINTER(_P)],
    "GdipCreateStringFormat": [ctypes.c_int, ctypes.c_uint16, ctypes.POINTER(_P)],
    "GdipSetStringFormatAlign": [_P, ctypes.c_int],
    "GdipSetStringFormatLineAlign": [_P, ctypes.c_int],
    "GdipSetStringFormatTrimming": [_P, ctypes.c_int],
    "GdipSetStringFormatFlags": [_P, ctypes.c_int],
    "GdipDrawString": [_P, wintypes.LPCWSTR, ctypes.c_int, _P, ctypes.POINTER(_RectF), _P, _P],
}.items():
    getattr(_gdip, _name).argtypes = _args


class _Painter:
    """GDI+ поверх буфера окна: заливки, скругления и текст."""

    def __init__(self) -> None:
        token = ctypes.c_size_t()
        _gdip.GdiplusStartup(ctypes.byref(token), ctypes.byref(_StartupInput(1, None, False, False)), None)
        self._fonts: dict[tuple[bool, float], _P] = {}
        self._mark = _P()
        mark = _asset("mark-dark.png")
        if mark:
            _gdip.GdipLoadImageFromFile(str(mark), ctypes.byref(self._mark))
        self._formats: dict[tuple[int, bool], _P] = {}
        self.g = _P()

    def begin(self, hdc, scale: float) -> None:
        _gdip.GdipCreateFromHDC(hdc, ctypes.byref(self.g))
        _gdip.GdipSetSmoothingMode(self.g, 4)
        _gdip.GdipSetTextRenderingHint(self.g, 5)
        _gdip.GdipSetInterpolationMode(self.g, 7)
        _gdip.GdipSetPixelOffsetMode(self.g, 4)
        _gdip.GdipScaleWorldTransform(self.g, scale, scale, 0)

    def end(self) -> None:
        _gdip.GdipDeleteGraphics(self.g)

    def clear(self, argb: int) -> None:
        _gdip.GdipGraphicsClear(self.g, argb)

    @staticmethod
    def _rounded(x: float, y: float, w: float, h: float, r: float) -> _P:
        path = _P()
        _gdip.GdipCreatePath(0, ctypes.byref(path))
        r = max(0.01, min(r, w / 2, h / 2))
        d = 2 * r
        _gdip.GdipAddPathArc(path, x, y, d, d, 180, 90)
        _gdip.GdipAddPathArc(path, x + w - d, y, d, d, 270, 90)
        _gdip.GdipAddPathArc(path, x + w - d, y + h - d, d, d, 0, 90)
        _gdip.GdipAddPathArc(path, x, y + h - d, d, d, 90, 90)
        _gdip.GdipClosePathFigure(path)
        return path

    def fill(self, x, y, w, h, r, argb: int) -> None:
        if w <= 0:
            return
        brush = _P()
        _gdip.GdipCreateSolidFill(argb, ctypes.byref(brush))
        path = self._rounded(x, y, w, h, r)
        _gdip.GdipFillPath(self.g, brush, path)
        _gdip.GdipDeletePath(path)
        _gdip.GdipDeleteBrush(brush)

    def outline(self, x, y, w, h, r, argb: int) -> None:
        pen = _P()
        _gdip.GdipCreatePen1(argb, 1.0, 0, ctypes.byref(pen))
        path = self._rounded(x + 0.5, y + 0.5, w - 1, h - 1, r)
        _gdip.GdipDrawPath(self.g, pen, path)
        _gdip.GdipDeletePath(path)
        _gdip.GdipDeletePen(pen)

    def line(self, x1, y1, x2, y2, argb: int) -> None:
        pen = _P()
        _gdip.GdipCreatePen1(argb, 1.0, 0, ctypes.byref(pen))
        _gdip.GdipDrawLine(self.g, pen, x1, y1, x2, y2)
        _gdip.GdipDeletePen(pen)

    def mark(self, x, y, size) -> None:
        if self._mark:
            _gdip.GdipDrawImageRect(self.g, self._mark, x, y, size, size)

    def _font(self, heading: bool, size: float) -> _P:
        key = (heading, size)
        if key not in self._fonts:
            family = _P()
            name = "Segoe UI Semibold" if heading else "Segoe UI"
            if _gdip.GdipCreateFontFamilyFromName(name, None, ctypes.byref(family)) != 0:
                _gdip.GdipCreateFontFamilyFromName("Segoe UI", None, ctypes.byref(family))
            font = _P()
            _gdip.GdipCreateFont(family, size, 0, 2, ctypes.byref(font))
            self._fonts[key] = font
        return self._fonts[key]

    def _format(self, align: int, wrap: bool) -> _P:
        key = (align, wrap)
        if key not in self._formats:
            fmt = _P()
            _gdip.GdipCreateStringFormat(0, 0, ctypes.byref(fmt))
            _gdip.GdipSetStringFormatAlign(fmt, align)
            _gdip.GdipSetStringFormatLineAlign(fmt, 0)
            _gdip.GdipSetStringFormatTrimming(fmt, 3)
            if not wrap:
                _gdip.GdipSetStringFormatFlags(fmt, 0x1000)
            self._formats[key] = fmt
        return self._formats[key]

    def text(self, value, x, y, w, h, *, size, argb, heading=False, align=0, wrap=False) -> None:
        brush = _P()
        _gdip.GdipCreateSolidFill(argb, ctypes.byref(brush))
        rect = _RectF(x, y, w, h)
        _gdip.GdipDrawString(
            self.g, value, -1, self._font(heading, size), ctypes.byref(rect), self._format(align, wrap), brush
        )
        _gdip.GdipDeleteBrush(brush)


class UpdateWindow:
    def __init__(self, worker: Worker) -> None:
        self.worker = worker
        self.painter = _Painter()
        self.started = time.monotonic()
        self.done_at = 0.0
        self.hover_close = False
        self.scale = 1.0
        self.height = _H
        self.hwnd = None
        self._proc = _WNDPROC(self._wndproc)

    def _close_rect(self) -> tuple[float, float, float, float]:
        w, h = 120, 32
        return _W - _PAD - w, _ERROR_HEIGHT - _PAD - h, w, h

    def _in_close(self, x: float, y: float) -> bool:
        if self.worker.snapshot().stage != "error":
            return False
        cx, cy, cw, ch = self._close_rect()
        return cx <= x <= cx + cw and cy <= y <= cy + ch

    def _client_point(self, lparam) -> tuple[float, float]:
        x = ctypes.c_short(lparam & 0xFFFF).value
        y = ctypes.c_short((lparam >> 16) & 0xFFFF).value
        return x / self.scale, y / self.scale

    def _wndproc(self, hwnd, msg, wparam, lparam):
        if msg == _WM_MOUSEMOVE:
            self.hover_close = self._in_close(*self._client_point(lparam))
            return 0
        if msg == _WM_LBUTTONUP:
            if self._in_close(*self._client_point(lparam)):
                _user32.PostMessageW(hwnd, _WM_CLOSE, 0, 0)
            return 0
        if msg == _WM_TIMER:
            state = self.worker.snapshot()
            if state.stage == "done":
                self.done_at = self.done_at or time.monotonic()
                if time.monotonic() - self.done_at >= _CLOSE_AFTER_DONE_S:
                    _user32.PostMessageW(hwnd, _WM_CLOSE, 0, 0)
            _user32.InvalidateRect(hwnd, None, False)
            return 0
        if msg == _WM_ERASEBKGND:
            return 1
        if msg == _WM_PAINT:
            self._paint(hwnd)
            return 0
        if msg == _WM_DESTROY:
            _user32.PostQuitMessage(0)
            return 0
        return _user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _fit_to_stage(self, hwnd) -> None:
        """Ошибке нужно больше места: окно растёт, а не держит пустоту всё остальное время."""
        height = _ERROR_HEIGHT if self.worker.snapshot().stage == "error" else _H
        if height == self.height:
            return
        self.height = height
        frame = wintypes.RECT(0, 0, round(_W * self.scale), round(height * self.scale))
        _user32.AdjustWindowRectExForDpi(ctypes.byref(frame), _WINDOW_STYLE, False, 0, round(self.scale * 96))
        _user32.SetWindowPos(hwnd, None, 0, 0, frame.right - frame.left, frame.bottom - frame.top, _SWP_NOMOVE | _SWP_NOZORDER)

    def _paint(self, hwnd) -> None:
        self._fit_to_stage(hwnd)
        ps = _Paint()
        hdc = _user32.BeginPaint(hwnd, ctypes.byref(ps))
        width, height = round(_W * self.scale), round(self.height * self.scale)
        mem = _gdi32.CreateCompatibleDC(hdc)
        bitmap = _gdi32.CreateCompatibleBitmap(hdc, width, height)
        old = _gdi32.SelectObject(mem, bitmap)
        p = self.painter
        p.begin(mem, self.scale)
        self._draw(p, self.worker.snapshot())
        p.end()
        _gdi32.BitBlt(hdc, 0, 0, width, height, mem, 0, 0, _SRCCOPY)
        _gdi32.SelectObject(mem, old)
        _gdi32.DeleteObject(bitmap)
        _gdi32.DeleteDC(mem)
        _user32.EndPaint(hwnd, ctypes.byref(ps))

    def _draw(self, p: _Painter, s: State) -> None:
        job = self.worker.job
        error = s.stage == "error"
        p.clear(_argb("page"))

        # Заголовок: знак, что ставим и с какой версии.
        p.mark(_PAD, _PAD, 32)
        title_x = _PAD + 44
        title_w = _W - title_x - _PAD
        p.text(f"Обновление до {APP_TITLE} {job.version}", title_x, _PAD - 4, title_w, 24, size=16, argb=_argb("text"), heading=True)
        if job.from_version:
            p.text(f"Текущая версия {job.from_version}", title_x, _PAD + 18, title_w, 18, size=12, argb=_argb("text-secondary"))

        # Подпись этапа и процент.
        top = _PAD + 50
        text_w = _W - 2 * _PAD
        p.text(s.caption, _PAD, top, text_w - 56, 20, size=14, argb=_argb("error" if error else "text"))
        if s.progress is not None and s.stage in {"download", "verify", "install"}:
            p.text(f"{math.floor(s.progress * 100)}%", _W - _PAD - 56, top, 56, 20, size=14, argb=_argb("text-secondary"), align=2)

        # Шкала WinUI: дорожка в один пиксель, поверх неё акцент толщиной три.
        bar_y = top + 30
        p.fill(_PAD, bar_y + 1, text_w, 1, 0.5, _argb("track"))
        color = _argb("error" if error else "accent")
        if s.stage == "done" or error:
            p.fill(_PAD, bar_y, text_w, 3, 1.5, color)
        elif s.progress is None:
            self._draw_indeterminate(p, bar_y, text_w, color)
        else:
            p.fill(_PAD, bar_y, text_w * max(s.progress, 0.0), 3, 1.5, color)

        # Подробности под шкалой; в ошибке — причина, последний шаг и кнопка.
        detail_y = bar_y + 12
        if error:
            p.text(s.detail, _PAD, detail_y, text_w, 38, size=12, argb=_argb("text-secondary"), wrap=True)
            if s.log:
                p.text(s.log[-1], _PAD, _ERROR_HEIGHT - _PAD - 24, text_w - 132, 18, size=12, argb=_argb("text-secondary"))
            x, y, w, h = self._close_rect()
            p.fill(x, y, w, h, 4, _argb("button-hover" if self.hover_close else "button"))
            p.outline(x, y, w, h, 4, _argb("button-border"))
            p.text("Закрыть", x, y + (h - 19) / 2, w, 20, size=14, argb=_argb("text"), align=1)
        elif s.detail:
            p.text(s.detail, _PAD, detail_y, text_w, 18, size=12, argb=_argb("text-secondary"))

    def _draw_indeterminate(self, p: _Painter, bar_y: float, width: float, color: int) -> None:
        """Отрезок проходит по шкале с замедлением к концам, как у неопределённой шкалы WinUI."""
        phase = ((time.monotonic() - self.started) % _INDETERMINATE_PERIOD_S) / _INDETERMINATE_PERIOD_S
        eased = (1 - math.cos(math.pi * phase)) / 2
        span = width * 0.3
        head = -span + (width + span) * eased
        start, end = max(head, 0.0), min(head + span, width)
        if end > start:
            p.fill(_PAD + start, bar_y, end - start, 3, 1.5, color)

    def run(self) -> None:
        _user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        self.scale = _user32.GetDpiForSystem() / 96
        instance = _kernel32.GetModuleHandleW(None)
        wndclass = _WndClass()
        wndclass.wndproc = ctypes.cast(self._proc, ctypes.c_void_p)
        wndclass.instance = instance
        wndclass.cursor = _user32.LoadCursorW(None, 32512)
        wndclass.class_name = "TwoWingsUpdate"
        _user32.RegisterClassW(ctypes.byref(wndclass))

        style = _WINDOW_STYLE
        frame = wintypes.RECT(0, 0, round(_W * self.scale), round(_H * self.scale))
        _user32.AdjustWindowRectExForDpi(ctypes.byref(frame), style, False, 0, round(self.scale * 96))
        width, height = frame.right - frame.left, frame.bottom - frame.top
        x = max(0, (_user32.GetSystemMetrics(0) - width) // 2)
        y = max(0, (_user32.GetSystemMetrics(1) - height) // 2)
        self.hwnd = _user32.CreateWindowExW(
            0, "TwoWingsUpdate", f"Обновление {APP_TITLE}", style, x, y, width, height, None, None, instance, None,
        )
        if not self.hwnd:
            raise OSError(f"CreateWindowExW: {ctypes.get_last_error()}")
        self._style_frame()
        self._set_icon()
        _user32.ShowWindow(self.hwnd, 5)
        _user32.SetForegroundWindow(self.hwnd)
        _user32.SetTimer(self.hwnd, 1, _FRAME_MS, None)
        self.worker.start()

        msg = wintypes.MSG()
        while _user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            _user32.TranslateMessage(ctypes.byref(msg))
            _user32.DispatchMessageW(ctypes.byref(msg))

    def _set_icon(self) -> None:
        """Значок рамки и панели задач из app.ico рядом с exe, в обоих размерах для текущего DPI."""
        ico = _asset("app.ico")
        if ico is None:
            return
        dpi = round(self.scale * 96)
        for kind, metric in ((0, 49), (1, 11)):  # ICON_SMALL: SM_CXSMICON, ICON_BIG: SM_CXICON
            size = _user32.GetSystemMetricsForDpi(metric, dpi)
            icon = _user32.LoadImageW(None, str(ico), 1, size, size, 0x10)  # IMAGE_ICON, LR_LOADFROMFILE
            if icon:
                _user32.SendMessageW(self.hwnd, _WM_SETICON, kind, icon)

    def _style_frame(self) -> None:
        """Заголовок окна рисует Windows; ему нужно только сказать, какая тема."""
        dark = ctypes.c_int(1 if _IS_DARK else 0)
        _dwmapi.DwmSetWindowAttribute(self.hwnd, 20, ctypes.byref(dark), ctypes.sizeof(dark))  # DWMWA_USE_IMMERSIVE_DARK_MODE


def run_update_window(worker: Worker) -> None:
    UpdateWindow(worker).run()
