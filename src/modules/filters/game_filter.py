"""Game filter flag management."""

from __future__ import annotations

from pathlib import Path

from src.core.debug_log import debug
from src.core.paths import utils_dir
from src.core.settings import GameFilterMode, get_settings, save_settings

GAME_FILTER_PORTS = {
    "off": ("12", "12"),
    "all": ("1024-65535", "1024-65535"),
    "tcp": ("1024-65535", "12"),
    "udp": ("12", "1024-65535"),
}


def get_game_filter_ports(mode: GameFilterMode | None = None) -> tuple[str, str]:
    mode = mode or get_settings().game_filter
    return GAME_FILTER_PORTS.get(mode, GAME_FILTER_PORTS["off"])


def get_game_filter_flag_path(_version: str) -> Path:
    return utils_dir() / "game_filter.enabled"


def read_game_filter_mode(version: str) -> GameFilterMode:
    path = get_game_filter_flag_path(version)
    if not path.exists():
        return "off"
    value = path.read_text(encoding="utf-8", errors="replace").strip().lower()
    if value == "all":
        return "all"
    if value == "tcp":
        return "tcp"
    if value == "udp":
        return "udp"
    return "off"


def _write_game_filter_flag(mode: GameFilterMode) -> None:
    path = get_game_filter_flag_path("")
    path.parent.mkdir(parents=True, exist_ok=True)
    if mode == "off":
        if path.exists():
            path.unlink()
    else:
        path.write_text(mode + "\n", encoding="utf-8")


def apply_game_filter(version: str, mode: GameFilterMode) -> None:
    _write_game_filter_flag(mode)

    settings = get_settings()
    settings.game_filter = mode
    save_settings(settings)
    debug("filters", f"game filter set to {mode}")


def ensure_game_filter_synced(version: str) -> GameFilterMode:
    """Align flag file with settings.json; user settings win on conflict."""
    settings = get_settings()
    disk_mode = read_game_filter_mode(version)
    settings_mode = settings.game_filter

    if disk_mode == settings_mode:
        return settings_mode

    if settings_mode == "off" and disk_mode != "off":
        settings.game_filter = disk_mode
        save_settings(settings)
        debug("filters", f"game filter adopted from disk: {disk_mode}")
        return disk_mode

    _write_game_filter_flag(settings_mode)
    debug("filters", f"game filter restored on disk: {settings_mode}")
    return settings_mode


def sync_game_filter_from_disk(version: str) -> GameFilterMode:
    """Backward-compatible alias for ensure_game_filter_synced."""
    return ensure_game_filter_synced(version)
