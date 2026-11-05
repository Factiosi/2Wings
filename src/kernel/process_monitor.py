"""Background winws process monitor (low resource, emit-on-change)."""

from __future__ import annotations

import threading
import time

from src.core.paths import bin_dir
from src.core.debug_log import debug
from src.kernel import runtime_state
from src.kernel.process_probe import is_canonical_winws_running

INTERVAL_SECONDS = 2.0
DEBOUNCE_MISSES = 3


class ProcessMonitor:
    def __init__(self, *, interval: float = INTERVAL_SECONDS) -> None:
        self._interval = interval
        self._thread: threading.Thread | None = None
        self._running = False
        self._last_running: bool | None = None
        self._last_pid: int | None = None
        self._miss_count = 0

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True, name="twowings-process-monitor")
        self._thread.start()

    def stop(self) -> None:
        self._running = False

    def _loop(self) -> None:
        while self._running:
            sys_present = bin_dir().exists() and any(bin_dir().glob("*.sys"))
            runtime_state.set_windivert_present(sys_present)

            running, pid = is_canonical_winws_running()

            if running:
                self._miss_count = 0
                if running != self._last_running or pid != self._last_pid:
                    self._last_running = running
                    self._last_pid = pid
                    status = runtime_state.get_status()
                    runtime_state.sync_probe(True, pid, strategy_name=status.strategy_name)
                    debug("kernel", f"monitor: winws running pid={pid}")
            else:
                if self._last_running:
                    self._miss_count += 1
                    if self._miss_count >= DEBOUNCE_MISSES:
                        self._last_running = False
                        self._last_pid = None
                        self._miss_count = 0
                        runtime_state.sync_probe(False, None)
                        debug("kernel", "monitor: winws stopped")
                else:
                    self._last_running = False
                    self._last_pid = None

            time.sleep(self._interval)


_monitor = ProcessMonitor()


def get_monitor() -> ProcessMonitor:
    return _monitor


def start_monitor() -> None:
    get_monitor().start()


def stop_monitor() -> None:
    get_monitor().stop()
