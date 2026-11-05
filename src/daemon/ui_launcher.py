"""Spawn 2Wings GUI process and track instances for shutdown."""

from __future__ import annotations

import os
import subprocess
import sys
import time

from src.core.debug_log import debug
from src.core.paths import (
    APP_NAME,
    frozen_subprocess_env,
    packaged_app_executable,
    program_root,
    windowless_python_executable,
)

_gui_pids: set[int] = set()
_gui_processes: list[subprocess.Popen] = []
_last_gui_spawn = 0.0
# A new window takes a moment to appear; repeated clicks must not start more of them.
_SPAWN_GRACE_SECONDS = 4.0


def register_gui_pid(pid: int | None = None) -> None:
    value = pid if pid is not None else os.getpid()
    if value > 0:
        _gui_pids.add(value)
        debug("daemon", f"registered GUI pid={value}")


def unregister_gui_pid(pid: int | None = None) -> None:
    value = pid if pid is not None else os.getpid()
    _gui_pids.discard(value)


def _prune_gui_processes() -> None:
    global _gui_processes
    _gui_processes = [proc for proc in _gui_processes if proc.poll() is None]


def _kill_pid(pid: int) -> None:
    if pid <= 0:
        return
    try:
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                capture_output=True,
                check=False,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        else:
            os.kill(pid, 15)
    except OSError as exc:
        debug("daemon", f"failed to kill pid={pid}: {exc}", level="error")


def close_all_gui() -> None:
    _prune_gui_processes()
    targets = set(_gui_pids)
    for proc in _gui_processes:
        if proc.poll() is None:
            targets.add(proc.pid)
    for pid in targets:
        _kill_pid(pid)
    _gui_processes.clear()
    _gui_pids.clear()
    debug("daemon", "all GUI processes closed")


def _spawn_args(*extra: str, hide_first_window: bool = True) -> tuple[list[str], dict]:
    root = program_root()
    cwd = str(root)
    kwargs: dict = {"cwd": cwd}
    if sys.platform == "win32":
        if hide_first_window:
            # Windows applies this to the first window the process shows, so it is
            # only for processes without a window of their own.
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE
            kwargs["startupinfo"] = startupinfo
        # CREATE_NO_WINDOW вместе с DETACHED_PROCESS Windows игнорирует, и python.exe
        # получает отдельное чёрное окно консоли.
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
        kwargs["stdin"] = subprocess.DEVNULL
        kwargs["stdout"] = subprocess.DEVNULL
        kwargs["stderr"] = subprocess.DEVNULL

    exe = packaged_app_executable()
    if exe is not None:
        kwargs["env"] = frozen_subprocess_env()
        return [str(exe), *extra], kwargs

    run_py = root / "run.py"
    if not run_py.is_file():
        raise FileNotFoundError(
            f"Не найден 2Wings.exe или run.py в {root}. "
            "Запускайте приложение из полной папки dist\\2Wings\\."
        )
    return [windowless_python_executable(), str(run_py), *extra], kwargs


def _raise_existing_gui() -> bool:
    _prune_gui_processes()
    pids = set(_gui_pids) | {proc.pid for proc in _gui_processes}
    if not pids or sys.platform != "win32":
        return False
    from src.core.win32_window import raise_window_of_processes

    return raise_window_of_processes(pids)


def launch_gui(*, hidden: bool = False) -> tuple[bool, str]:
    global _last_gui_spawn
    args = ["--ui"]
    if hidden:
        args.append("--tray")
    elif _raise_existing_gui():
        return True, "Окно открыто."
    elif time.monotonic() - _last_gui_spawn < _SPAWN_GRACE_SECONDS:
        return True, "Окно открывается."
    try:
        cmd, kwargs = _spawn_args(*args, hide_first_window=False)
        proc = subprocess.Popen(cmd, **kwargs)
        _last_gui_spawn = time.monotonic()
    except OSError as exc:
        return False, str(exc)
    except FileNotFoundError as exc:
        return False, str(exc)
    _gui_processes.append(proc)
    debug("daemon", f"GUI launched: {' '.join(cmd)} pid={proc.pid}")
    return True, "Окно открыто."


def launch_daemon() -> tuple[bool, str]:
    try:
        cmd, kwargs = _spawn_args("--daemon")
        subprocess.Popen(cmd, **kwargs)
    except OSError as exc:
        return False, str(exc)
    except FileNotFoundError as exc:
        return False, str(exc)
    debug("daemon", f"daemon process spawned: {' '.join(cmd)}")
    return True, "Фоновый процесс запущен."


def notify_spawn_error(message: str) -> None:
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, message, APP_NAME, 0x10)
    except OSError:
        pass
