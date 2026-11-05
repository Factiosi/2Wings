"""Move twowings-tls-watch.lua reports into the user's exclude lists.

winws2 appends lines to ``tls-alerts.txt`` in its writable directory; the
daemon takes the file every couple of seconds and writes new domains to
``list-exclude-user.txt`` and new addresses to ``ipset-exclude-user.txt``.
winws2 rereads list files when they change, so the next connection already
goes untouched.
"""

from __future__ import annotations

import ipaddress
import os
import re
import threading
from dataclasses import dataclass
from pathlib import Path

from src.core.debug_log import info, warn
from src.core.paths import flowseal_user_lists_dir, winws2_writable_dir
from src.core.settings import get_settings

ALERTS_FILE = "tls-alerts.txt"
DOMAIN_LIST = "list-exclude-user.txt"
IP_LIST = "ipset-exclude-user.txt"
POLL_SECONDS = 2.0
MARK = "# 2Wings: сервер отверг TLS-рукопожатие после обхода"
_DOMAIN = re.compile(r"^(?=.{1,253}$)([a-z0-9-]{1,63}\.)+[a-z0-9-]{2,63}$")


@dataclass(frozen=True)
class Report:
    kind: str  # "d" — exclude the domain, "i" — exclude the address
    host: str | None
    ip: str | None
    alert: int


def alerts_path() -> Path:
    return winws2_writable_dir() / ALERTS_FILE


def parse_reports(text: str) -> list[Report]:
    reports: list[Report] = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) != 4 or parts[0] not in {"d", "i"}:
            continue
        kind, host, ip, alert = parts
        reports.append(
            Report(
                kind=kind,
                host=None if host == "-" else host.lower().strip("."),
                ip=None if ip == "-" else ip,
                alert=int(alert) if alert.isdigit() else -1,
            )
        )
    return reports


def _exclude_entry(report: Report) -> tuple[str, str] | None:
    """(list file name, line) for a report, or None when it is not usable."""
    if report.kind == "d" and report.host and _DOMAIN.match(report.host):
        return DOMAIN_LIST, report.host
    if report.ip:
        try:
            address = ipaddress.ip_address(report.ip)
        except ValueError:
            return None
        if address.is_global:
            return IP_LIST, f"{address}/{address.max_prefixlen}"
    return None


def _list_lines(path: Path) -> set[str]:
    try:
        text = path.read_text(encoding="utf-8-sig", errors="replace")
    except FileNotFoundError:
        return set()
    return {line.split("#", 1)[0].strip().lower() for line in text.splitlines()} - {""}


def append_to_list(path: Path, entries: list[str]) -> list[str]:
    """Append entries missing from the list file; return the ones added."""
    existing = _list_lines(path)
    added = [entry for entry in dict.fromkeys(entries) if entry.lower() not in existing]
    if not added:
        return []
    try:
        current = path.read_text(encoding="utf-8-sig", errors="replace")
    except FileNotFoundError:
        current = ""
    lines = [] if not current or current.endswith("\n") else [""]
    if MARK not in current:
        lines.append(MARK)
    lines.extend(added)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write("\n".join(lines) + "\n")
    return added


def apply_reports(reports: list[Report], lists_dir: Path | None = None) -> list[str]:
    """Write reports into the exclude lists; return human-readable added entries."""
    lists_dir = lists_dir or flowseal_user_lists_dir()
    grouped: dict[str, list[str]] = {}
    for report in reports:
        entry = _exclude_entry(report)
        if entry:
            grouped.setdefault(entry[0], []).append(entry[1])
    added: list[str] = []
    for name, entries in grouped.items():
        added += append_to_list(lists_dir / name, entries)
    return added


def take_reports(path: Path | None = None) -> str:
    """Move the alerts file aside and read it; winws2 starts a new one on the next alert."""
    path = path or alerts_path()
    if not path.exists():
        return ""
    taken = path.with_name(path.name + ".taken")
    try:
        os.replace(path, taken)
    except OSError:
        return ""  # winws2 is writing right now; next poll
    try:
        return taken.read_text(encoding="utf-8", errors="replace")
    finally:
        taken.unlink(missing_ok=True)


def _poll_once() -> None:
    text = take_reports()
    if not text or not get_settings().tls_auto_exclude:
        return
    added = apply_reports(parse_reports(text))
    if added:
        info("tls-exclude", f"добавлено в исключения после ошибки TLS: {', '.join(added)}")


def _loop(stop: threading.Event) -> None:
    while not stop.wait(POLL_SECONDS):
        try:
            _poll_once()
        except OSError as exc:
            warn("tls-exclude", f"не удалось обработать отчёты TLS: {exc}")


def start_watcher() -> threading.Event:
    """Daemon only. Returns the event that stops the watcher."""
    stop = threading.Event()
    threading.Thread(target=_loop, args=(stop,), daemon=True, name="twowings-tls-exclude").start()
    return stop
