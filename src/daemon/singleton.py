"""Windows singleton guard for the privileged 2Wings daemon."""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

_MUTEX_NAME = "Local\\TwoWings.Daemon.v1"
_ERROR_ALREADY_EXISTS = 183
_handle: int | None = None


def acquire_daemon_mutex() -> bool:
    """Return False when another daemon owns the per-session mutex."""
    global _handle
    if sys.platform != "win32":
        return True
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_mutex = kernel32.CreateMutexW
    create_mutex.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
    create_mutex.restype = wintypes.HANDLE
    handle = create_mutex(None, False, _MUTEX_NAME)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    if ctypes.get_last_error() == _ERROR_ALREADY_EXISTS:
        kernel32.CloseHandle(handle)
        return False
    _handle = int(handle)
    return True


def release_daemon_mutex() -> None:
    global _handle
    if _handle is None or sys.platform != "win32":
        return
    ctypes.windll.kernel32.CloseHandle(_handle)
    _handle = None
