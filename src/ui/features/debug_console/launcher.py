"""Launch the debug console in a separate process."""

from __future__ import annotations

import subprocess
import sys

from src.core.debug_log import info
from src.core.paths import packaged_app_executable, program_root

_process: subprocess.Popen[bytes] | None = None
_CONSOLE_TITLE_MARKER = "консоль отладки"


def _launch_command() -> list[str]:
    exe = packaged_app_executable()
    if exe is not None:
        return [str(exe), "--debug-console"]
    return [sys.executable, str(program_root() / "run.py"), "--debug-console"]


def open_debug_console() -> tuple[bool, str]:
    """Spawn the console window. Returns (ok, message)."""
    global _process

    if _process is not None and _process.poll() is not None:
        _process = None

    if _process is not None and _process.poll() is None:
        if sys.platform == "win32":
            from src.core.win32_window import raise_window_by_title

            if raise_window_by_title(_CONSOLE_TITLE_MARKER):
                return True, "Консоль отладки уже открыта."
        return True, "Консоль отладки уже открыта."

    if packaged_app_executable() is None:
        entrypoint = program_root() / "run.py"
        if not entrypoint.exists():
            return False, f"Не найден файл: {entrypoint}"

    popen_kwargs: dict = {"cwd": str(program_root())}
    if sys.platform == "win32":
        popen_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW | getattr(subprocess, "DETACHED_PROCESS", 0)
    if packaged_app_executable() is not None:
        from src.core.paths import frozen_subprocess_env

        popen_kwargs["env"] = frozen_subprocess_env()

    try:
        _process = subprocess.Popen(
            _launch_command(),
            **popen_kwargs,
        )
    except OSError as exc:
        return False, f"Не удалось открыть консоль: {exc}"

    info("debug_console", "debug console subprocess started")
    return True, "Консоль отладки открыта."
