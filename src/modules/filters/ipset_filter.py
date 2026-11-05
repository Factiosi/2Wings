"""IPSet filter toggle (service.bat :ipset_switch)."""

from __future__ import annotations

from pathlib import Path

from src.core.debug_log import debug
from src.core.paths import flowseal_version_lists_dir
from src.core.settings import IpsetFilterMode, get_settings, save_settings

DUMMY_IP = "203.0.113.113/32"


def _list_file(version: str) -> Path:
    return flowseal_version_lists_dir(version) / "ipset-all.txt"


def _backup_file(version: str) -> Path:
    return flowseal_version_lists_dir(version) / "ipset-all.txt.backup"


def detect_ipset_mode(version: str) -> IpsetFilterMode:
    list_file = _list_file(version)
    if not list_file.exists():
        return "any"
    lines = [
        ln.strip()
        for ln in list_file.read_text(encoding="utf-8", errors="replace").splitlines()
        if ln.strip()
    ]
    if not lines:
        return "any"
    if any(DUMMY_IP in ln for ln in lines):
        return "none"
    return "loaded"


def apply_ipset_mode(version: str, mode: IpsetFilterMode) -> None:
    list_file = _list_file(version)
    backup_file = _backup_file(version)
    list_file.parent.mkdir(parents=True, exist_ok=True)
    current = detect_ipset_mode(version)

    if mode == "none" and current == "loaded":
        if backup_file.exists():
            backup_file.unlink()
        if list_file.exists():
            list_file.rename(backup_file)
        list_file.write_text(DUMMY_IP + "\n", encoding="utf-8")
    elif mode == "any" and current != "any":
        # Лист уходит в резерв, как для «Отключён»: иначе вернуть «Из листа» будет не из чего.
        if current == "loaded" and list_file.exists():
            backup_file.unlink(missing_ok=True)
            list_file.rename(backup_file)
        list_file.write_text("", encoding="utf-8")
    elif mode == "loaded" and current != "loaded":
        if backup_file.exists():
            if list_file.exists():
                list_file.unlink()
            backup_file.rename(list_file)
        else:
            raise FileNotFoundError(
                "Нет резервной копии ipset-all.txt. Сначала обновите список."
            )

    settings = get_settings()
    settings.ipset_filter = mode
    save_settings(settings)
    debug("filters", f"ipset filter set to {mode}")


def sync_ipset_from_disk(version: str) -> IpsetFilterMode:
    mode = detect_ipset_mode(version)
    settings = get_settings()
    settings.ipset_filter = mode
    save_settings(settings)
    return mode


def keep_ipset_mode(version: str) -> IpsetFilterMode:
    """После обновления стратегий: новая версия приносит полный лист, выбор пользователя переносим на неё."""
    mode = get_settings().ipset_filter
    try:
        apply_ipset_mode(version, mode)
    except FileNotFoundError:
        return sync_ipset_from_disk(version)
    return mode
