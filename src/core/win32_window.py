"""Win32 helpers for raising existing top-level windows."""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

if sys.platform != "win32":
    raise RuntimeError("Win32 window helpers are only supported on Windows.")

_user32 = ctypes.windll.user32
SW_RESTORE = 9


def raise_window_of_processes(pids: set[int]) -> bool:
    """Bring a visible titled top-level window of one of the processes to front."""
    found: list[int] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def _enum_proc(hwnd: int, _lparam: int) -> bool:
        owner = wintypes.DWORD()
        _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value in pids and _user32.IsWindowVisible(hwnd) and _user32.GetWindowTextLengthW(hwnd) > 0:
            found.append(hwnd)
            return False
        return True

    _user32.EnumWindows(_enum_proc, 0)
    if not found:
        return False
    _user32.ShowWindow(found[0], SW_RESTORE)
    _user32.SetForegroundWindow(found[0])
    return True


def raise_window_by_title(title_substring: str) -> bool:
    """Bring the first top-level window whose title contains *title_substring* to front."""
    needle = title_substring.casefold()
    found: list[int] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def _enum_proc(hwnd: int, _lparam: int) -> bool:
        if not _user32.IsWindowVisible(hwnd):
            return True
        length = _user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        buffer = ctypes.create_unicode_buffer(length + 1)
        _user32.GetWindowTextW(hwnd, buffer, length + 1)
        if needle in buffer.value.casefold():
            found.append(hwnd)
            return False
        return True

    _user32.EnumWindows(_enum_proc, 0)
    if not found:
        return False

    hwnd = found[0]
    _user32.ShowWindow(hwnd, SW_RESTORE)
    _user32.SetForegroundWindow(hwnd)
    return True
