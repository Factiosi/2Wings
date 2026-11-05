"""winws process helpers."""

from __future__ import annotations

import subprocess
import time

from src.kernel.process_probe import find_canonical_winws_pids

CREATE_NO_WINDOW = 0x08000000
EXIT_WAIT_SECONDS = 3.0
EXIT_POLL_SECONDS = 0.1


def _taskkill(*target: str) -> bool:
    result = subprocess.run(
        ["taskkill", *target, "/F"],
        capture_output=True,
        text=True,
        encoding="cp866",
        errors="replace",
        check=False,
        creationflags=CREATE_NO_WINDOW,
    )
    return result.returncode == 0


def kill_winws() -> bool:
    """Stop leftover engines and wait until they are gone: while one holds the WinDivert
    driver, deleting the service leaves it disabled and the next start fails."""
    killed = _taskkill("/IM", "winws.exe")
    for pid in find_canonical_winws_pids():
        killed = _taskkill("/PID", str(pid)) or killed
    deadline = time.monotonic() + EXIT_WAIT_SECONDS
    while find_canonical_winws_pids() and time.monotonic() < deadline:
        time.sleep(EXIT_POLL_SECONDS)
    return killed
