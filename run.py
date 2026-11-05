"""2Wings entry point."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _require_dependencies(*, include_ui: bool = True) -> None:
    try:
        import httpx  # noqa: F401
        if include_ui:
            import PySide6  # noqa: F401
            import qfluentwidgets  # noqa: F401
    except ModuleNotFoundError as exc:
        missing = exc.name or "unknown"
        print(
            f"Не найден модуль '{missing}' для {sys.executable}\n\n"
            "Зависимости, скорее всего, установлены в другой версии Python.\n"
            "Используйте один из вариантов:\n"
            f"  {sys.executable} -m pip install -r requirements.txt\n"
            "  py -3.12 -m venv .venv && .venv\\Scripts\\python -m pip install -r requirements.txt\n"
            f"  {sys.executable} run.py\n",
            file=sys.stderr,
        )
        raise SystemExit(1) from exc


def _is_daemon_mode(argv: list[str]) -> bool:
    return "--daemon" in argv


def _is_debug_console_mode(argv: list[str]) -> bool:
    return "--debug-console" in argv


def _is_post_update_relaunch(argv: list[str]) -> bool:
    if os.environ.get("TWOWINGSRELAUNCH", "").strip() == "1":
        return True
    return any(
        part.strip().endswith("=1")
        for arg in argv
        for part in arg.split(":", 1)[-1].split("&")
        if "TWOWINGSRELAUNCH" in part.upper()
    )


def _signal_update_splash_done() -> None:
    try:
        from src.modules.updates.splash_launcher import signal_update_splash_done

        signal_update_splash_done()
    except Exception:
        pass


def main() -> None:
    from src.core.paths import migrate_legacy_app_data, verify_frozen_layout

    migrate_legacy_app_data()
    verify_frozen_layout()
    argv = sys.argv
    if _is_post_update_relaunch(argv):
        _signal_update_splash_done()
    if _is_debug_console_mode(argv):
        _require_dependencies()
        from src.ui.features.debug_console.app import main as debug_console_main

        sys.exit(debug_console_main())

    if _is_daemon_mode(argv):
        _require_dependencies(include_ui=False)
        try:
            import pystray  # noqa: F401
            from PIL import Image  # noqa: F401
        except ModuleNotFoundError as exc:
            print(
                f"Для daemon нужны pystray и Pillow: {exc.name}\n"
                f"  {sys.executable} -m pip install -r requirements.txt",
                file=sys.stderr,
            )
            raise SystemExit(1) from exc
        from src.core.admin import ensure_admin, is_admin
        from src.core.paths import APP_NAME
        from src.core.debug_log import info as log_info
        from src.core.process_label import set_process_description

        set_process_description("2Wings daemon")
        log_info("bootstrap", f"starting {APP_NAME} daemon")
        if not is_admin():
            if not ensure_admin():
                sys.exit(0)
            sys.exit(0)
        from src.daemon.main import run_daemon
        from src.daemon.singleton import acquire_daemon_mutex, release_daemon_mutex

        if not acquire_daemon_mutex():
            log_info("daemon", "existing daemon instance detected")
            return
        try:
            run_daemon()
        finally:
            release_daemon_mutex()
        return

    _require_dependencies()

    from src.core.admin import ensure_admin, is_admin
    from src.core.debug_log import info as log_info
    from src.core.paths import APP_NAME, ensure_layout
    from src.core.process_label import set_process_description
    from src.core.settings import get_settings
    from src.daemon.ipc import register_gui_with_daemon
    from src.modules.lifecycle.public import require_daemon_for_gui, should_launch_gui

    log_info("bootstrap", f"starting {APP_NAME} GUI")
    get_settings()
    ensure_layout()

    if not is_admin():
        log_info("bootstrap", "elevation required")
        if not ensure_admin():
            sys.exit(0)
        sys.exit(0)

    if not should_launch_gui():
        require_daemon_for_gui()
        log_info("bootstrap", "GUI suppressed by start_minimized_to_tray")
        sys.exit(0)

    require_daemon_for_gui()
    log_info("bootstrap", "daemon ready")
    register_gui_with_daemon(os.getpid())

    from src.modules.strategy_testing.results import load_cache

    load_cache()
    set_process_description(APP_NAME)
    log_info("bootstrap", "launching UI")
    from src.ui.app import main as ui_main

    sys.exit(ui_main())


if __name__ == "__main__":
    main()
