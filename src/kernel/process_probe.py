"""Lightweight winws process probe (canonical path).

2Wings's engine is bin/winws2.exe. bin/winws.exe left by 2Wings before the winws2
switch still counts as 2Wings's own, so stop() can clean it up; winws/winws2
from anywhere else is foreign and blocks the launch (WinDivert is shared).
"""

from __future__ import annotations

import ctypes
import os
from ctypes import wintypes
from src.core.paths import ENGINE_EXE, LEGACY_ENGINE_EXE, bin_dir

_ENGINE_NAMES = frozenset({ENGINE_EXE, LEGACY_ENGINE_EXE})

TH32CS_SNAPPROCESS = 0x00000002
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
MAX_PATH = 32768


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * 260),
    ]


def _normalize_path(path: str) -> str:
    text = str(path or "").strip()
    if text.startswith("\\\\?\\"):
        text = text[4:]
    try:
        text = os.path.abspath(text)
    except OSError:
        pass
    return os.path.normcase(text)


def _canonical_paths() -> frozenset[str]:
    return frozenset(_normalize_path(str((bin_dir() / name).resolve())) for name in _ENGINE_NAMES)


def _query_image_path(pid: int) -> str:
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(MAX_PATH)
        size = wintypes.DWORD(len(buf))
        if not kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return ""
        return _normalize_path(buf.value)
    finally:
        kernel32.CloseHandle(handle)


def find_canonical_winws_pids() -> list[int]:
    expected = _canonical_paths()

    kernel32 = ctypes.windll.kernel32
    snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snapshot in (-1, 0xFFFFFFFF):
        return []

    entry = PROCESSENTRY32W()
    entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
    pids: list[int] = []

    try:
        if not kernel32.Process32FirstW(snapshot, ctypes.byref(entry)):
            return []
        while True:
            name = entry.szExeFile.lower()
            if name in _ENGINE_NAMES:
                pid = int(entry.th32ProcessID)
                image = _query_image_path(pid)
                if image in expected:
                    pids.append(pid)
            if not kernel32.Process32NextW(snapshot, ctypes.byref(entry)):
                break
    finally:
        kernel32.CloseHandle(snapshot)

    return pids


def find_foreign_winws_processes() -> list[tuple[int, str]]:
    """Return queryable winws/winws2 processes launched outside 2Wings's bin directory."""
    expected = _canonical_paths()
    kernel32 = ctypes.windll.kernel32
    snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snapshot in (-1, 0xFFFFFFFF):
        return []

    entry = PROCESSENTRY32W()
    entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
    foreign: list[tuple[int, str]] = []
    try:
        if not kernel32.Process32FirstW(snapshot, ctypes.byref(entry)):
            return []
        while True:
            if entry.szExeFile.lower() in _ENGINE_NAMES:
                pid = int(entry.th32ProcessID)
                image = _query_image_path(pid)
                if image and image not in expected:
                    foreign.append((pid, image))
            if not kernel32.Process32NextW(snapshot, ctypes.byref(entry)):
                break
    finally:
        kernel32.CloseHandle(snapshot)
    return foreign


def is_canonical_winws_running() -> tuple[bool, int | None]:
    pids = find_canonical_winws_pids()
    if not pids:
        return False, None
    return True, pids[0]
