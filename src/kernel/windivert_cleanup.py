"""WinDivert driver service cleanup."""

from __future__ import annotations

import subprocess
import time

CREATE_NO_WINDOW = 0x08000000
ERROR_SERVICE_DOES_NOT_EXIST = 1060
REMOVAL_WAIT_SECONDS = 5.0
REMOVAL_POLL_SECONDS = 0.1


def _run(args: list[str]) -> int:
    return subprocess.run(
        args,
        capture_output=True,
        check=False,
        creationflags=CREATE_NO_WINDOW,
    ).returncode


def _service_exists(name: str) -> bool:
    return _run(["sc", "query", name]) != ERROR_SERVICE_DOES_NOT_EXIST


def cleanup_windivert_services() -> None:
    for name in ("WinDivert", "WinDivert14"):
        if not _service_exists(name):
            continue
        _run(["net", "stop", name])
        _run(["sc", "delete", name])
        # Until Windows finishes the removal the service counts as disabled, and a start
        # in that moment fails with "the service cannot be started" (1058).
        deadline = time.monotonic() + REMOVAL_WAIT_SECONDS
        while _service_exists(name) and time.monotonic() < deadline:
            time.sleep(REMOVAL_POLL_SECONDS)
