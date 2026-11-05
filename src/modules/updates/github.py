"""Fetch flowseal releases from GitHub."""

from __future__ import annotations

import re
import shutil
import stat
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from pathlib import PurePosixPath

import httpx

from src.core.debug_log import debug
from src.core.paths import GITHUB_RELEASE_API, GITHUB_VERSION_URL, staging_dir

MAX_ARCHIVE_BYTES = 512 * 1024 * 1024
MAX_EXTRACTED_BYTES = 2 * 1024 * 1024 * 1024
MAX_ARCHIVE_ENTRIES = 20_000


@dataclass
class UpdateInfo:
    local_version: str | None
    remote_version: str | None
    update_available: bool
    download_url: str | None
    error: str | None = None


def _client() -> httpx.Client:
    return httpx.Client(
        timeout=httpx.Timeout(30.0, connect=10.0),
        headers={
            "User-Agent": "2Wings",
            "Cache-Control": "no-cache",
        },
        follow_redirects=True,
    )


def fetch_remote_version(retries: int = 3) -> str | None:
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            with _client() as client:
                response = client.get(GITHUB_VERSION_URL)
                response.raise_for_status()
                version = response.text.strip()
                if re.fullmatch(r"\d+\.\d+\.\d+", version):
                    return version
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            time.sleep(1.5 * (attempt + 1))
    if last_error:
        return None
    return None


def fetch_latest_release_asset_url() -> tuple[str | None, str | None]:
    """Return (version_tag, zip_download_url)."""
    try:
        with _client() as client:
            response = client.get(GITHUB_RELEASE_API)
            response.raise_for_status()
            data = response.json()
            tag = str(data.get("tag_name", "")).lstrip("v") or None
            for asset in data.get("assets", []):
                name = str(asset.get("name", "")).lower()
                if name.endswith(".zip"):
                    return tag, str(asset.get("browser_download_url"))
            return tag, None
    except Exception:  # noqa: BLE001
        return None, None


def _parse_version(value: str | None) -> tuple[int, ...] | None:
    if not value:
        return None
    cleaned = value.strip().lstrip("vV")
    parts: list[int] = []
    for chunk in cleaned.replace("-", ".").split("."):
        if not chunk:
            continue
        digits = ""
        for ch in chunk:
            if ch.isdigit():
                digits += ch
            else:
                break
        if not digits:
            return None
        parts.append(int(digits))
    return tuple(parts) if parts else None


def is_remote_newer(local_version: str | None, remote_version: str | None) -> bool:
    local = _parse_version(local_version)
    remote = _parse_version(remote_version)
    if remote is None:
        return False
    if local is None:
        return True
    max_len = max(len(local), len(remote))
    local_padded = local + (0,) * (max_len - len(local))
    remote_padded = remote + (0,) * (max_len - len(remote))
    return remote_padded > local_padded


def check_for_update(local_version: str | None) -> UpdateInfo:
    remote = fetch_remote_version()
    _, asset_url = fetch_latest_release_asset_url()
    if remote is None:
        return UpdateInfo(
            local_version=local_version,
            remote_version=None,
            update_available=False,
            download_url=asset_url,
            error="Не удалось получить версию с GitHub. Работаем на локальной копии.",
        )
    update_available = is_remote_newer(local_version, remote)
    debug(
        "updates",
        f"check_for_update local={local_version} remote={remote} update={update_available}",
    )
    return UpdateInfo(
        local_version=local_version,
        remote_version=remote,
        update_available=update_available,
        download_url=asset_url,
    )


def download_release_to_staging(url: str, version: str) -> Path:
    staging = staging_dir()
    if staging.exists():
        import shutil

        shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True, exist_ok=True)

    zip_path = staging / f"zapret-{version}.zip"
    with _client() as client:
        with client.stream("GET", url) as response:
            response.raise_for_status()
            with zip_path.open("wb") as handle:
                downloaded = 0
                for chunk in response.iter_bytes():
                    downloaded += len(chunk)
                    if downloaded > MAX_ARCHIVE_BYTES:
                        raise ValueError("Архив Flowseal превышает допустимый размер (512 МБ).")
                    handle.write(chunk)

    extract_root = staging / "extracted"
    extract_root.mkdir(exist_ok=True)
    with zipfile.ZipFile(zip_path, "r") as archive:
        _safe_extract_zip(archive, extract_root)

    # Release zips usually contain a single top-level folder.
    children = [p for p in extract_root.iterdir() if p.is_dir()]
    if len(children) == 1:
        return children[0]
    return extract_root


def _safe_extract_zip(archive: zipfile.ZipFile, destination: Path) -> None:
    """Extract a trusted-format archive without path traversal or symlinks."""
    infos = archive.infolist()
    if len(infos) > MAX_ARCHIVE_ENTRIES:
        raise ValueError("В архиве Flowseal слишком много файлов.")
    total = sum(max(info.file_size, 0) for info in infos)
    if total > MAX_EXTRACTED_BYTES:
        raise ValueError("Распакованный архив Flowseal превышает допустимый размер.")

    root = destination.resolve()
    for info in infos:
        normalized = info.filename.replace("\\", "/")
        relative = PurePosixPath(normalized)
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or any(":" in part for part in relative.parts)
            or not relative.parts
        ):
            raise ValueError(f"Небезопасный путь в архиве: {info.filename}")
        mode = info.external_attr >> 16
        if stat.S_IFMT(mode) == stat.S_IFLNK:
            raise ValueError(f"Символические ссылки в архиве запрещены: {info.filename}")
        target = (root / Path(*relative.parts)).resolve()
        if not target.is_relative_to(root):
            raise ValueError(f"Путь выходит за каталог распаковки: {info.filename}")
        if info.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        with archive.open(info, "r") as source, target.open("wb") as output:
            shutil.copyfileobj(source, output, length=1024 * 1024)
