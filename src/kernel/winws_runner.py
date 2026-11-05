"""Start/stop winws2.exe via subprocess (shared by home and tests)."""

from __future__ import annotations

import subprocess
import threading
import time
from dataclasses import dataclass
from enum import Enum

from src.core.debug_log import debug
from src.kernel import runtime_state
from src.kernel.launch_spec import WinwsLaunchSpec
from src.kernel.process_probe import find_canonical_winws_pids, is_canonical_winws_running
from src.kernel.windows_errors import describe_windows_error

CREATE_NO_WINDOW = 0x08000000
KILL_TIMEOUT = 4.0
STARTUP_WAIT = 3.0
COOLDOWN_SECONDS = 0.5


class RunnerPhase(str, Enum):
    IDLE = "idle"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    FAILED = "failed"


@dataclass(frozen=True)
class RunnerSnapshot:
    phase: RunnerPhase
    pid: int | None
    strategy_name: str | None
    error: str | None


DRIVER_RETRIES = 2
DRIVER_RETRY_SECONDS = 2.0
_DRIVER_BUSY = "windivert: error opening filter"


class WinwsRunner:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._proc: subprocess.Popen[bytes] | None = None
        self._strategy_name: str | None = None
        self._phase = RunnerPhase.IDLE
        self._error: str | None = None

    def snapshot(self) -> RunnerSnapshot:
        with self._lock:
            pid = self._proc.pid if self._proc and self._proc.poll() is None else None
            if pid is None:
                running, probed = is_canonical_winws_running()
                pid = probed if running else None
            return RunnerSnapshot(
                phase=self._phase,
                pid=pid,
                strategy_name=self._strategy_name,
                error=self._error,
            )

    def is_managed_running(self) -> bool:
        with self._lock:
            if self._proc is not None and self._proc.poll() is None:
                return True
        running, _ = is_canonical_winws_running()
        return running

    def start(self, spec: WinwsLaunchSpec, *, wait_seconds: float = STARTUP_WAIT) -> tuple[bool, str]:
        """The driver service may still be on its way out after the previous engine: try again."""
        for attempt in range(DRIVER_RETRIES + 1):
            ok, message = self._start_once(spec, wait_seconds=wait_seconds)
            if ok or attempt == DRIVER_RETRIES or _DRIVER_BUSY not in message:
                break
            debug("kernel", f"windivert driver busy, retry {attempt + 1}")
            time.sleep(DRIVER_RETRY_SECONDS)
        return ok, message

    def _start_once(self, spec: WinwsLaunchSpec, *, wait_seconds: float) -> tuple[bool, str]:
        with self._lock:
            self.stop_locked(cooldown=False)
            self._phase = RunnerPhase.STARTING
            self._strategy_name = spec.strategy_name
            self._error = None
            runtime_state.mark_starting(spec.strategy_name)

            try:
                self._proc = subprocess.Popen(
                    [str(spec.exe), *spec.argv],
                    cwd=str(spec.cwd),
                    creationflags=CREATE_NO_WINDOW,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                )
            except OSError as exc:
                self._phase = RunnerPhase.FAILED
                self._error = str(exc)
                runtime_state.mark_failed(str(exc), strategy_name=spec.strategy_name)
                debug("kernel", f"winws spawn failed: {exc}", level="error")
                return False, str(exc)

        time.sleep(wait_seconds)

        with self._lock:
            if self._proc and self._proc.poll() is None:
                if self._proc.stderr:
                    self._proc.stderr.close()
                self._phase = RunnerPhase.RUNNING
                runtime_state.mark_running(spec.strategy_name, self._proc.pid)
                debug("kernel", f"winws running pid={self._proc.pid} strategy={spec.strategy_name}")
                return True, f"Запущено: {spec.strategy_name}"

            code = self._proc.returncode if self._proc else None
            detail = self._read_startup_error(self._proc)
            message = f"winws завершился сразу после запуска (код {code})."
            if detail:
                message = f"{message} {detail}"
            hint = describe_windows_error(code)
            if hint and hint not in message:
                message = f"{message} {hint}"
            self._phase = RunnerPhase.FAILED
            self._error = message
            self._proc = None
            runtime_state.mark_failed(message, strategy_name=spec.strategy_name)
            debug("kernel", f"winws immediate exit: {message}", level="error")
            return False, message

    def stop(self, *, cooldown: bool = True) -> tuple[bool, str]:
        with self._lock:
            return self.stop_locked(cooldown=cooldown)

    def stop_locked(self, *, cooldown: bool = True) -> tuple[bool, str]:
        runtime_state.mark_stopping()
        self._phase = RunnerPhase.STOPPING

        proc = self._proc
        if proc and proc.poll() is None:
            try:
                proc.terminate()
            except OSError:
                pass
            try:
                proc.wait(timeout=KILL_TIMEOUT)
            except subprocess.TimeoutExpired:
                try:
                    proc.kill()
                except OSError:
                    pass
                try:
                    proc.wait(timeout=1.0)
                except subprocess.TimeoutExpired:
                    pass

        self._proc = None

        for pid in find_canonical_winws_pids():
            subprocess.run(
                ["taskkill", "/F", "/PID", str(pid)],
                capture_output=True,
                check=False,
                creationflags=CREATE_NO_WINDOW,
            )

        self._phase = RunnerPhase.IDLE
        self._strategy_name = None
        self._error = None
        runtime_state.mark_stopped()

        if cooldown:
            time.sleep(COOLDOWN_SECONDS)

        return True, "winws остановлен."

    @staticmethod
    def _read_startup_error(proc: subprocess.Popen[bytes] | None) -> str:
        if proc is None or proc.stderr is None:
            return ""
        try:
            blob = proc.stderr.read()
        except OSError:
            return ""
        if not blob:
            return ""
        text = blob.decode("utf-8", errors="replace").strip()
        if not text:
            return ""
        return text.splitlines()[0][:240]


_runner = WinwsRunner()


def get_runner() -> WinwsRunner:
    return _runner
