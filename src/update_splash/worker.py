"""Работа TwoWingsUpdate: скачать установщик, сверить SHA-256, поставить, дождаться новой 2Wings.

Без зависимостей кроме стандартной библиотеки: программа живёт вне Program Files\\2Wings
и не должна тянуть ничего из установки, которую сама заменяет.
"""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import re
import socket
import ssl
import threading
import time
import urllib.error
import urllib.request
from ctypes import wintypes
from dataclasses import dataclass, field
from pathlib import Path

_CHUNK = 256 * 1024
_DAEMON_PORT = 51731
_LAUNCH_TIMEOUT_S = 120
_LOG_LINES = 4


@dataclass
class Job:
    version: str
    from_version: str
    installer_url: str
    checksum_url: str
    work_dir: Path
    done_file: Path


@dataclass
class State:
    stage: str = "download"  # download, verify, install, launch, done, error
    caption: str = "Подготовка"
    progress: float | None = None
    detail: str = ""
    log: list[str] = field(default_factory=list)


class Worker:
    def __init__(self, job: Job) -> None:
        self.job = job
        self._state = State()
        self._lock = threading.Lock()

    def snapshot(self) -> State:
        with self._lock:
            s = self._state
            return State(s.stage, s.caption, s.progress, s.detail, list(s.log))

    def start(self) -> None:
        threading.Thread(target=self._run, name="twowings-update", daemon=True).start()

    def _set(self, *, log: str | None = None, **changes) -> None:
        with self._lock:
            for key, value in changes.items():
                setattr(self._state, key, value)
            if log:
                self._state.log = (self._state.log + [log])[-_LOG_LINES:]

    def _run(self) -> None:
        try:
            self._job()
        except Exception as exc:  # noqa: BLE001
            self._set(stage="error", caption="Обновление не удалось", detail=_reason(exc))

    def _job(self) -> None:
        job = self.job
        job.work_dir.mkdir(parents=True, exist_ok=True)
        job.done_file.unlink(missing_ok=True)
        name = job.installer_url.rsplit("/", 1)[-1]
        installer = job.work_dir / name
        checksum = job.work_dir / f"{name}.sha256"

        self._set(stage="download", caption="Скачивание обновления", log=f"2Wings {job.from_version} → {job.version}")
        _fetch(job.checksum_url, checksum)
        expected = _expected_sum(checksum)
        if installer.is_file() and _sha256(installer) == expected:
            self._set(progress=1.0, detail="", log="Установщик уже скачан")
        else:
            partial = installer.with_name(installer.name + ".part")
            self._download(job.installer_url, partial)
            self._set(stage="verify", caption="Проверка файла", progress=0.0, detail="SHA-256")
            if self._hash(partial) != expected:
                partial.unlink(missing_ok=True)
                raise ValueError("SHA-256 установщика не совпадает с опубликованной суммой")
            os.replace(partial, installer)
            self._set(log="SHA-256 совпадает")

        progress_file = job.work_dir / "install-progress.txt"
        progress_file.unlink(missing_ok=True)
        self._set(stage="install", caption="Установка файлов", progress=None, detail="Закрытие 2Wings", log="Запуск установщика")
        code = self._install(installer, progress_file)
        if code != 0:
            raise RuntimeError(f"установщик завершился с кодом {code}")
        self._set(stage="launch", caption="Запуск 2Wings", progress=None, detail="", log="Файлы установлены")
        self._wait_for_twowings()
        self._set(stage="done", caption=f"2Wings {job.version} запущен", progress=1.0, log=f"2Wings {job.version} запущен")

    def _download(self, url: str, destination: Path) -> None:
        with _open(url) as response:
            total = int(response.headers.get("Content-Length") or 0)
            got = 0
            started = time.monotonic()
            with destination.open("wb") as handle:
                while chunk := response.read(_CHUNK):
                    handle.write(chunk)
                    got += len(chunk)
                    speed = got / max(time.monotonic() - started, 0.001)
                    detail = f"{_mb(got)} из {_mb(total)} МБ · {_mb(speed)} МБ/с" if total else f"{_mb(got)} МБ"
                    self._set(progress=got / total if total else None, detail=detail)
        if total and got != total:
            raise OSError(f"скачано {_mb(got)} из {_mb(total)} МБ")
        self._set(log=f"Скачано {_mb(got)} МБ")

    def _hash(self, path: Path) -> str:
        total = max(path.stat().st_size, 1)
        digest = hashlib.sha256()
        done = 0
        with path.open("rb") as handle:
            while chunk := handle.read(_CHUNK * 4):
                digest.update(chunk)
                done += len(chunk)
                self._set(progress=done / total)
        return digest.hexdigest()

    def _install(self, installer: Path, progress_file: Path) -> int:
        params = (
            "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /CLOSEAPPLICATIONS /FORCECLOSEAPPLICATIONS "
            f'/TWOWINGSRELAUNCH=1 "/TWOWINGSPROGRESS={progress_file}"'
        )
        process = _shell_execute(installer, params)
        try:
            while _kernel32.WaitForSingleObject(process, 200) == _WAIT_TIMEOUT:
                fraction = _install_fraction(progress_file)
                if fraction is not None:
                    self._set(progress=fraction, detail="")
            code = wintypes.DWORD()
            _kernel32.GetExitCodeProcess(process, ctypes.byref(code))
            return int(code.value)
        finally:
            _kernel32.CloseHandle(process)

    def _wait_for_twowings(self) -> None:
        deadline = time.monotonic() + _LAUNCH_TIMEOUT_S
        while time.monotonic() < deadline:
            if _twowings_done(self.job.done_file) or _daemon_reachable():
                return
            time.sleep(0.4)
        raise TimeoutError("2Wings установлен, но не запустился. Откройте его из меню «Пуск»")


def _reason(exc: Exception) -> str:
    if isinstance(exc, urllib.error.HTTPError):
        return f"Сервер обновлений ответил {exc.code}"
    if isinstance(exc, urllib.error.URLError):
        return f"Нет связи с сервером обновлений: {exc.reason}"
    text = str(exc).strip() or type(exc).__name__
    return text[0].upper() + text[1:]


def _mb(value: float) -> str:
    return f"{value / 1_048_576:.1f}".replace(".", ",")


def _open(url: str):
    request = urllib.request.Request(url, headers={"User-Agent": "TwoWingsUpdate", "Cache-Control": "no-cache"})
    return urllib.request.urlopen(request, timeout=60, context=ssl.create_default_context())


def _fetch(url: str, destination: Path) -> None:
    with _open(url) as response:
        destination.write_bytes(response.read())


def _expected_sum(path: Path) -> str:
    words = path.read_text(encoding="utf-8", errors="replace").split()
    if not words or not re.fullmatch(r"[0-9a-fA-F]{64}", words[0]):
        raise ValueError("файл контрольной суммы релиза повреждён")
    return words[0].lower()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_CHUNK * 4):
            digest.update(chunk)
    return digest.hexdigest()


def _install_fraction(path: Path) -> float | None:
    """Inno Setup пишет «текущее максимум» из CurInstallProgressChanged, см. twowings_installer.iss."""
    try:
        cur, top = (int(v) for v in path.read_text(encoding="ascii").split()[:2])
    except (OSError, ValueError):
        return None
    return min(cur / top, 1.0) if top > 0 else None


def _twowings_done(path: Path) -> bool:
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("phase") == "done"
    except (OSError, ValueError, AttributeError):
        return False


def _daemon_reachable() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", _DAEMON_PORT), timeout=0.4):
            return True
    except OSError:
        return False


_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_shell32 = ctypes.WinDLL("shell32", use_last_error=True)
_WAIT_TIMEOUT = 0x102
_SEE_MASK_NOCLOSEPROCESS = 0x40


class _SHELLEXECUTEINFOW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("fMask", wintypes.ULONG),
        ("hwnd", wintypes.HWND),
        ("lpVerb", wintypes.LPCWSTR),
        ("lpFile", wintypes.LPCWSTR),
        ("lpParameters", wintypes.LPCWSTR),
        ("lpDirectory", wintypes.LPCWSTR),
        ("nShow", ctypes.c_int),
        ("hInstApp", wintypes.HINSTANCE),
        ("lpIDList", ctypes.c_void_p),
        ("lpClass", wintypes.LPCWSTR),
        ("hkeyClass", wintypes.HKEY),
        ("dwHotKey", wintypes.DWORD),
        ("hIconOrMonitor", wintypes.HANDLE),
        ("hProcess", wintypes.HANDLE),
    ]


_kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
_kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
_kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
_shell32.ShellExecuteExW.argtypes = [ctypes.POINTER(_SHELLEXECUTEINFOW)]


def _shell_execute(path: Path, params: str) -> wintypes.HANDLE:
    """ShellExecute, а не CreateProcess: установщику нужны права администратора, при надобности спросит UAC."""
    info = _SHELLEXECUTEINFOW()
    info.cbSize = ctypes.sizeof(info)
    info.fMask = _SEE_MASK_NOCLOSEPROCESS
    info.lpVerb = "open"
    info.lpFile = str(path)
    info.lpParameters = params
    info.lpDirectory = str(path.parent)
    info.nShow = 0
    if not _shell32.ShellExecuteExW(ctypes.byref(info)) or not info.hProcess:
        raise OSError(f"не удалось запустить установщик (ошибка {ctypes.get_last_error()})")
    return info.hProcess
