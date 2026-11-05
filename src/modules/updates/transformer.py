"""Transform downloaded Flowseal package into the 2Wings layout."""

from __future__ import annotations

import shutil
from pathlib import Path

from src.core.paths import (
    USER_LIST_FILES,
    _merge_copytree,
    flowseal_fake_bin_dir,
    flowseal_version_dir,
    flowseal_version_lists_dir,
    program_root,
    runtime_version_path,
    utils_dir,
)
from src.modules.strategies.parser import convert_bat_to_strategy_text, list_strategy_bats


def transform_runtime(source_root: Path) -> None:
    """Install Flowseal utils into the program directory.

    Flowseal's winws.exe and its WinDivert.dll are not copied: the engine is
    winws2 from zapret2 (modules/updates/engine.py) with its own patched DLL.
    """
    program_root().mkdir(parents=True, exist_ok=True)

    src_utils = source_root / "utils"
    if src_utils.exists():
        dest_utils = utils_dir()
        if dest_utils.exists():
            _merge_copytree(src_utils, dest_utils, skip_names=frozenset({"game_filter.enabled"}))
        else:
            shutil.copytree(src_utils, dest_utils)


def transform_fake_bins(source_root: Path) -> None:
    """Merge strategy fake .bin files into flowseal/bin (always updated)."""
    src_bin = source_root / "bin"
    if not src_bin.exists():
        return
    dest = flowseal_fake_bin_dir()
    dest.mkdir(parents=True, exist_ok=True)
    for item in src_bin.glob("*.bin"):
        shutil.copy2(item, dest / item.name)


def transform_version_lists(source_root: Path, version: str) -> None:
    """Copy versioned list files into flowseal/<version>/lists/."""
    src_lists = source_root / "lists"
    if not src_lists.exists():
        return
    dest = flowseal_version_lists_dir(version)
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    for item in src_lists.iterdir():
        if item.name in USER_LIST_FILES:
            continue
        target = dest / item.name
        if item.is_dir():
            shutil.copytree(item, target)
        else:
            shutil.copy2(item, target)


def transform_strategies(source_root: Path, version: str) -> None:
    """Store converted strategy .txt files in flowseal/<version>/."""
    dest = flowseal_version_dir(version)
    dest.mkdir(parents=True, exist_ok=True)
    for existing in dest.glob("*.txt"):
        existing.unlink()
    for bat in list_strategy_bats(source_root):
        out = dest / f"{bat.stem}.txt"
        out.write_text(convert_bat_to_strategy_text(bat), encoding="utf-8")


def transform_package(
    source_root: Path,
    version: str,
    *,
    skip_list_updates: bool = False,
) -> Path:
    """Install runtime, fake bins, version lists and strategies."""
    from src.modules.strategies.repository import bootstrap_user_lists

    transform_runtime(source_root)
    transform_fake_bins(source_root)
    if not skip_list_updates:
        transform_version_lists(source_root, version)
    flowseal_version_dir(version).mkdir(parents=True, exist_ok=True)
    transform_strategies(source_root, version)
    runtime_version_path().write_text(version + "\n", encoding="utf-8")
    bootstrap_user_lists(source_root if not skip_list_updates else None)
    return flowseal_version_dir(version)


def promote_staging(source_root: Path, version: str, *, skip_list_updates: bool) -> Path:
    try:
        return transform_package(source_root, version, skip_list_updates=skip_list_updates)
    finally:
        from src.core.paths import staging_dir

        staging = staging_dir()
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
