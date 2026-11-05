"""Parse strategy test log lines."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Callable

COLOR_STATUS_ACTIVE = "active"
COLOR_STATUS_EXPIRING = "expiring"
COLOR_STATUS_ERROR = "error"
COLOR_TEXT = "text"
COLOR_TEXT_MUTED = "muted"


class TestLogLevel(str, Enum):
    INFO = "info"
    OK = "ok"
    WARN = "warn"
    ERROR = "error"


@dataclass(frozen=True)
class TestLogLine:
    timestamp: str
    text: str
    level: TestLogLevel


@dataclass(frozen=True)
class ParsedTestRow:
    name: str
    tokens: tuple[str, ...]
    ping: str | None


_listeners: list[Callable[[], None]] = []
_lines: list[TestLogLine] = []
_MAX_LINES = 800

_TEST_ROW_PIPE = re.compile(
    r"^(?P<name>\S+)\s+(?:(?P<tokens>(?:\S+\s+)+)\|\s*Ping:\s*(?P<ping>.+)|:\s*\|\s*Ping:\s*(?P<ping_empty>.+))$"
)
_TEST_ROW_PING_ONLY = re.compile(r"^(?P<name>\S+)\s+Ping:\s*(?P<ping>.+)$")


def token_color(token: str) -> str:
    upper = token.upper()
    if "ERROR" in upper or "SSL" in upper or "FAIL" in upper:
        return COLOR_STATUS_ERROR
    if "UNSUP" in upper:
        return COLOR_STATUS_EXPIRING
    if ":OK" in upper or upper.endswith("OK"):
        return COLOR_STATUS_ACTIVE
    return COLOR_TEXT


def _timestamp() -> str:
    return datetime.now().strftime("%d.%m.%Y %H:%M:%S")


def subscribe(listener: Callable[[], None]) -> None:
    _listeners.append(listener)


def unsubscribe(listener: Callable[[], None]) -> None:
    if listener in _listeners:
        _listeners.remove(listener)


def _notify() -> None:
    for listener in list(_listeners):
        listener()


def parse_test_row(text: str) -> ParsedTestRow | None:
    stripped = text.strip()
    match = _TEST_ROW_PIPE.match(stripped)
    if match:
        ping = match.group("ping") or match.group("ping_empty")
        tokens_raw = match.group("tokens") or ""
        tokens = tuple(part for part in tokens_raw.split() if part)
        return ParsedTestRow(match.group("name"), tokens, (ping or "").strip())
    match = _TEST_ROW_PING_ONLY.match(stripped)
    if match:
        return ParsedTestRow(match.group("name"), (), match.group("ping").strip())
    return None


def _classify_console_line(text: str) -> TestLogLevel:
    upper = text.upper()
    row = parse_test_row(text)
    if row and row.tokens:
        if any(token_color(token) == COLOR_STATUS_ERROR for token in row.tokens):
            return TestLogLevel.ERROR
        if any(token_color(token) == COLOR_STATUS_EXPIRING for token in row.tokens):
            return TestLogLevel.WARN
        return TestLogLevel.OK
    if row and row.ping:
        if row.ping.lower() in {"timeout", "n/a"}:
            return TestLogLevel.WARN
        return TestLogLevel.OK
    if "[ERROR]" in upper or " ОШИБКА" in upper or upper.startswith("FAIL"):
        return TestLogLevel.ERROR
    if "[WARN" in upper or "WARNING" in upper:
        return TestLogLevel.WARN
    if (
        "[OK]" in upper
        or "ALL TESTS FINISHED" in upper
        or "BEST STRATEGY" in upper
        or "BEST CONFIG" in upper
        or "RESULTS SAVED" in upper
        or ": FULL" in upper
        or ": PARTIAL" in upper
        or ": FAILED" in upper
    ):
        return TestLogLevel.OK
    return TestLogLevel.INFO


def append(text: str, *, level: TestLogLevel = TestLogLevel.INFO) -> None:
    line = TestLogLine(_timestamp(), text.rstrip(), level)
    _lines.append(line)
    if len(_lines) > _MAX_LINES:
        del _lines[: len(_lines) - _MAX_LINES]
    _notify()


def append_from_console(text: str) -> None:
    stripped = text.strip()
    if not stripped:
        return
    append(stripped, level=_classify_console_line(stripped))


def clear() -> None:
    _lines.clear()
    _notify()

