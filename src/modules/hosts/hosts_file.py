"""Read and edit the Windows hosts file.

2Wings owns only blocks between its own markers; everything else in the file is
the user's and is kept byte-for-byte, apart from line endings.
"""

from __future__ import annotations

import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path

from src.core.debug_log import debug

_BEGIN = "# >>> twowings:{} >>>"
_END = "# <<< twowings:{} <<<"
_BLOCK_LINE = re.compile(r"^# (>>>|<<<) twowings:([a-z0-9._-]+) (>>>|<<<)$")
# Versions up to 1.5.8 were called Tigo; their blocks become ours on the next read.
_LEGACY_BLOCK_LINE = re.compile(r"^# (>>>|<<<) tigo:([a-z0-9._-]+) (>>>|<<<)(?=\r?$)", re.M)
_BACKUP_NAME = "hosts.twowings.bak"
_LEGACY_BACKUP_NAME = "hosts.tigo.bak"

DEFAULT_HOSTS = """\
# Copyright (c) 1993-2009 Microsoft Corp.
#
# This is a sample HOSTS file used by Microsoft TCP/IP for Windows.
#
# This file contains the mappings of IP addresses to host names. Each
# entry should be kept on an individual line. The IP address should
# be placed in the first column followed by the corresponding host name.
# The IP address and the host name should be separated by at least one
# space.
#
# Additionally, comments (such as these) may be inserted on individual
# lines or following the machine name denoted by a '#' symbol.
#
# For example:
#
#      102.54.94.97     rhino.acme.com          # source server
#       38.25.63.10     x.acme.com              # x client host

# localhost name resolution is handled within DNS itself.
#	127.0.0.1       localhost
#	::1             localhost
"""


def hosts_path() -> Path:
    root = os.environ.get("SystemRoot") or r"C:\Windows"
    return Path(root) / "System32" / "drivers" / "etc" / "hosts"


@dataclass(frozen=True)
class HostsSummary:
    entries: int
    blocks: dict[str, int]  # 2Wings block id -> entries in it


def decode(raw: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1251"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1")


def is_entry(line: str) -> bool:
    text = line.split("#", 1)[0].strip()
    return len(text.split()) >= 2


def summarize(text: str) -> HostsSummary:
    entries = 0
    blocks: dict[str, int] = {}
    current: str | None = None
    for line in text.splitlines():
        marker = _BLOCK_LINE.match(line.strip())
        if marker:
            current = marker.group(2) if marker.group(1) == ">>>" else None
            if current:
                blocks.setdefault(current, 0)
            continue
        if is_entry(line):
            entries += 1
            if current:
                blocks[current] += 1
    return HostsSummary(entries=entries, blocks=blocks)


def remove_block(lines: list[str], block_id: str) -> list[str]:
    begin, end = _BEGIN.format(block_id), _END.format(block_id)
    result: list[str] = []
    inside = False
    for line in lines:
        stripped = line.strip()
        if stripped == begin:
            inside = True
            continue
        if inside:
            if stripped == end:
                inside = False
            continue
        result.append(line)
    return result


def set_block(text: str, block_id: str, rows: list[tuple[str, str]] | None) -> str:
    """Replace 2Wings's block ``block_id``; ``rows=None`` or empty removes it."""
    lines = remove_block(text.splitlines(), block_id)
    while lines and not lines[-1].strip():
        lines.pop()
    if rows:
        if lines:
            lines.append("")
        lines.append(_BEGIN.format(block_id))
        lines.extend(f"{ip} {domain}" for ip, domain in rows)
        lines.append(_END.format(block_id))
    return "\r\n".join(lines) + "\r\n"


def read_hosts(path: Path | None = None) -> str:
    path = path or hosts_path()
    try:
        text = decode(path.read_bytes())
    except FileNotFoundError:
        return ""
    return _LEGACY_BLOCK_LINE.sub(r"# \1 twowings:\2 \3", text)


def write_hosts(text: str, path: Path | None = None) -> None:
    """Write in place (the file keeps its ACL) and restore the read-only flag."""
    path = path or hosts_path()
    backup = backup_path(path)
    if path.exists() and not backup.exists():
        backup.write_bytes(path.read_bytes())
    mode = path.stat().st_mode if path.exists() else None
    read_only = mode is not None and not mode & stat.S_IWRITE
    if read_only:
        os.chmod(path, mode | stat.S_IWRITE)
    try:
        with path.open("w", encoding="utf-8", newline="") as handle:
            handle.write(text.replace("\r\n", "\n").replace("\n", "\r\n"))
    finally:
        if read_only:
            os.chmod(path, mode)
    debug("hosts", f"hosts written: {summarize(text).entries} entries")


def backup_path(path: Path | None = None) -> Path:
    path = path or hosts_path()
    backup = path.with_name(_BACKUP_NAME)
    legacy = path.with_name(_LEGACY_BACKUP_NAME)
    # The copy taken before the first change stays the original one after the rename.
    return legacy if legacy.exists() and not backup.exists() else backup
