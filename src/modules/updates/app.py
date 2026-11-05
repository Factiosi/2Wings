"""2Wings application updates from verified GitHub release installers."""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path

import httpx

from src.core.debug_log import debug, info
from src.core.paths import TWOWINGS_RELEASE_API, is_packaged_app, temp_dir
from src.core.version import __version__
from src.modules.updates.splash_launcher import launch_updater

MSG_APP_UP_TO_DATE = "У вас последняя актуальная версия 2Wings"
MSG_APP_UPDATE_AVAILABLE = "Доступна новая версия 2Wings"
MSG_APP_UPDATE_CLICKABLE = (
    "Доступна новая версия 2Wings (нажмите сюда чтобы скачать и установить)"
)
MSG_APP_DOWNLOADING = "Новая версия 2Wings доступна и скачивается"
MSG_APP_INSTALL_IN_PROGRESS = (
    "Установка 2Wings уже выполняется. Дождитесь завершения мастера установки."
)
_ASSET_RE = re.compile(r"^2Wings-Setup-(\d+\.\d+\.\d+)\.exe$", re.I)
_install_lock = threading.Lock()


@dataclass(frozen=True)
class AppUpdate:
    version: str
    installer_url: str
    checksum_url: str
    installer_name: str


def _version_tuple(value: str) -> tuple[int, int, int, int]:
    """«1.5.0» и тестовая «1.5.0-dev». Тестовая сборка младше своего релиза: 1.5.0-dev < 1.5.0."""
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)(-dev)?", value.strip(), re.I)
    if not match:
        raise ValueError(f"Некорректная версия: {value}")
    major, minor, patch, dev = match.groups()
    return int(major), int(minor), int(patch), 0 if dev else 1


def fetch_app_update() -> AppUpdate | None:
    with httpx.Client(
        timeout=httpx.Timeout(30.0, connect=10.0),
        headers={"User-Agent": f"2Wings/{__version__}", "Cache-Control": "no-cache"},
        follow_redirects=True,
    ) as client:
        response = client.get(TWOWINGS_RELEASE_API)
        response.raise_for_status()
        payload = response.json()

    assets = payload.get("assets")
    if not isinstance(assets, list):
        return None
    by_name = {
        str(asset.get("name") or ""): str(asset.get("browser_download_url") or "")
        for asset in assets
        if isinstance(asset, dict)
    }
    for name, url in by_name.items():
        match = _ASSET_RE.fullmatch(name)
        if not match or not url:
            continue
        version = match.group(1)
        checksum_name = f"{name}.sha256"
        checksum_url = by_name.get(checksum_name)
        if checksum_url and _version_tuple(version) > _version_tuple(__version__):
            return AppUpdate(version, url, checksum_url, name)
    return None


def _download(client: httpx.Client, url: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with client.stream("GET", url) as response:
        response.raise_for_status()
        with destination.open("wb") as handle:
            for chunk in response.iter_bytes():
                handle.write(chunk)


def _read_expected_checksum(checksum_file: Path) -> str:
    expected = checksum_file.read_text(encoding="utf-8", errors="replace").strip().split()[0].lower()
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise ValueError("Файл контрольной суммы релиза повреждён.")
    return expected


def _verify_file_hash(path: Path, expected: str) -> None:
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != expected:
        raise ValueError("SHA-256 установщика не совпадает с опубликованной суммой.")


def _finalize_installer(partial: Path, installer: Path) -> Path:
    try:
        os.replace(partial, installer)
        return installer
    except OSError:
        # Предыдущий установщик может быть занят запущенным setup.exe.
        return partial


def _existing_verified_installer(installer: Path, checksum_file: Path) -> Path | None:
    if not installer.exists() or not checksum_file.exists():
        return None
    try:
        expected = _read_expected_checksum(checksum_file)
        _verify_file_hash(installer, expected)
    except ValueError:
        installer.unlink(missing_ok=True)
        return None
    return installer


def _format_install_error(exc: Exception) -> str:
    winerror = getattr(exc, "winerror", None)
    if winerror == 32:
        return MSG_APP_INSTALL_IN_PROGRESS
    if isinstance(exc, PermissionError) or getattr(exc, "errno", None) == 13:
        return MSG_APP_INSTALL_IN_PROGRESS
    return str(exc)


def download_verified_installer(update: AppUpdate) -> Path:
    update_dir = temp_dir() / "app-update"
    update_dir.mkdir(parents=True, exist_ok=True)
    installer = update_dir / update.installer_name
    partial = installer.with_suffix(installer.suffix + ".part")
    checksum_file = update_dir / f"{update.installer_name}.sha256"

    existing = _existing_verified_installer(installer, checksum_file)
    if existing is not None:
        return existing

    partial.unlink(missing_ok=True)
    with httpx.Client(
        timeout=httpx.Timeout(300.0, connect=15.0),
        headers={"User-Agent": f"2Wings/{__version__}"},
        follow_redirects=True,
    ) as client:
        _download(client, update.installer_url, partial)
        _download(client, update.checksum_url, checksum_file)

    expected = _read_expected_checksum(checksum_file)
    try:
        _verify_file_hash(partial, expected)
    except ValueError:
        partial.unlink(missing_ok=True)
        raise
    return _finalize_installer(partial, installer)


def launch_installer(installer: Path) -> None:
    if not is_packaged_app():
        raise RuntimeError("Автоустановка доступна только в собранной версии 2Wings.")
    creationflags = (
        subprocess.CREATE_NO_WINDOW
        | getattr(subprocess, "DETACHED_PROCESS", 0)
        | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    )
    subprocess.Popen(
        [
            str(installer),
            "/VERYSILENT",
            "/SUPPRESSMSGBOXES",
            "/NORESTART",
            "/CLOSEAPPLICATIONS",
            "/FORCECLOSEAPPLICATIONS",
            "/TWOWINGSRELAUNCH=1",
        ],
        cwd=str(installer.parent),
        creationflags=creationflags,
        close_fds=True,
    )
    info("app_updates", f"launched verified installer {installer.name}")


def check_app_only() -> tuple[bool, str, str]:
    try:
        update = fetch_app_update()
    except Exception as exc:  # noqa: BLE001
        debug("app_updates", f"check failed: {exc}", level="error")
        return False, f"Не удалось проверить обновления 2Wings: {exc}", "error"
    if update is None:
        return True, MSG_APP_UP_TO_DATE, "success"
    return True, MSG_APP_UPDATE_CLICKABLE, "warning"


def check_and_install_app() -> tuple[bool, str, str]:
    if not _install_lock.acquire(blocking=False):
        return False, MSG_APP_INSTALL_IN_PROGRESS, "warning"
    try:
        update = fetch_app_update()
        if update is None:
            return True, MSG_APP_UP_TO_DATE, "success"
        if launch_updater(
            version=update.version,
            from_version=__version__,
            installer_url=update.installer_url,
            checksum_url=update.checksum_url,
        ):
            return True, f"Обновление до 2Wings {update.version} запущено", "success"
        # Окна обновления нет: 2Wings скачивает и ставит сам, без прогресса.
        installer = download_verified_installer(update)
        launch_installer(installer)
        return True, f"2Wings {update.version} загружен. Запускается установка.", "success"
    except Exception as exc:  # noqa: BLE001
        debug("app_updates", f"install failed: {exc}", level="error")
        return False, f"Не удалось установить обновление 2Wings: {_format_install_error(exc)}", "error"
    finally:
        _install_lock.release()
