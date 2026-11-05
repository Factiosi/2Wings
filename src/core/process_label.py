"""Set human-readable process description visible in Task Manager."""

from __future__ import annotations

import sys

_PROCESS_SET_LIMITED_INFORMATION = 0x0002_0000


def _apply_process_description(process_handle: int, label: str) -> bool:
    import ctypes
    from ctypes import wintypes

    kernelbase = ctypes.WinDLL("kernelbase", use_last_error=True)
    set_desc = getattr(kernelbase, "SetProcessDescription", None)
    if set_desc is None:
        return False

    set_desc.argtypes = [wintypes.HANDLE, wintypes.LPCWSTR]
    set_desc.restype = wintypes.HRESULT
    result = set_desc(process_handle, label.strip())
    return result == 0


def set_process_description(label: str) -> bool:
    if sys.platform != "win32" or not label.strip():
        return False
    try:
        import ctypes

        process = ctypes.windll.kernel32.GetCurrentProcess()
        return _apply_process_description(process, label)
    except (AttributeError, OSError, TypeError, ValueError):
        return False


def set_process_description_for_pid(pid: int, label: str) -> bool:
    if sys.platform != "win32" or pid <= 0 or not label.strip():
        return False
    try:
        import ctypes

        handle = ctypes.windll.kernel32.OpenProcess(_PROCESS_SET_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        try:
            return _apply_process_description(handle, label)
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    except (AttributeError, OSError, TypeError, ValueError):
        return False
