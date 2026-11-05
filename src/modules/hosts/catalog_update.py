"""Fetch a fresh hosts catalog from zapretgui's release store.

zapretgui publishes ``update-manifest.json`` with every release; it lists each
file with its SHA-256. Files sit in a content-addressed store as
``<sha256>.zst``. 2Wings takes the catalog entry from the newest manifest,
downloads that blob, checks the hash and keeps the file only if it is newer
than the catalog 2Wings already has.
"""

from __future__ import annotations

import hashlib
import os
import time
from pathlib import Path

import httpx

from src.core.debug_log import debug, info
from src.modules.hosts.catalog import CatalogError, active_catalog_path, cached_catalog_path, catalog_version

FORGEJO = "https://git2.zapret.moe"
RELEASES_API = f"{FORGEJO}/api/v1/repos/zapretdiscordyoutube/zapretgui/releases?limit=5"
STORE = f"{FORGEJO}/api/packages/zapretdiscordyoutube/generic/zapret-gui-store/1"
MANIFEST_NAME = "update-manifest.json"
CATALOG_FILE = "system/hosts_catalog.sqlite3"
MAX_CATALOG_BYTES = 16 * 1024 * 1024
CHECK_INTERVAL_SECONDS = 6 * 3600


def _client() -> httpx.Client:
    return httpx.Client(timeout=httpx.Timeout(30.0, connect=10.0), headers={"User-Agent": "2Wings"}, follow_redirects=True)


def _latest_catalog_sha256(client: httpx.Client) -> str:
    releases = client.get(RELEASES_API)
    releases.raise_for_status()
    for release in releases.json():
        manifest_url = next(
            (asset.get("browser_download_url") for asset in release.get("assets", []) if asset.get("name") == MANIFEST_NAME),
            None,
        )
        if not manifest_url:
            continue
        manifest = client.get(manifest_url)
        manifest.raise_for_status()
        for entry in manifest.json().get("files", []):
            if entry.get("path") == CATALOG_FILE:
                digest = str(entry.get("sha256") or "").lower()
                if len(digest) == 64:
                    return digest
    raise CatalogError("в выпусках zapretgui нет каталога hosts")


def _download(client: httpx.Client, digest: str) -> bytes:
    import zstandard

    response = client.get(f"{STORE}/{digest}.zst")
    response.raise_for_status()
    data = zstandard.ZstdDecompressor().decompress(response.content, max_output_size=MAX_CATALOG_BYTES)
    if hashlib.sha256(data).hexdigest() != digest:
        raise CatalogError("контрольная сумма каталога не совпала")
    return data


def update_catalog() -> tuple[bool, str]:
    """Download the newest catalog. Returns (changed, message)."""
    target = cached_catalog_path()
    try:
        current = catalog_version(active_catalog_path())
    except CatalogError:
        current = ""
    with _client() as client:
        digest = _latest_catalog_sha256(client)
        data = _download(client, digest)
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".partial")
    partial.write_bytes(data)
    try:
        version = catalog_version(partial)
        _check_stamp().touch()
        if version <= current:
            debug("hosts", f"catalog {version} is not newer than {current}")
            return False, f"Каталог сервисов актуален ({current})."
        os.replace(partial, target)
    finally:
        partial.unlink(missing_ok=True)
    info("hosts", f"hosts catalog updated to {version}")
    return True, f"Каталог сервисов обновлён до {version}."


def _check_stamp() -> Path:
    return cached_catalog_path().with_name("hosts_catalog.checked")


def catalog_check_due() -> bool:
    try:
        return time.time() - _check_stamp().stat().st_mtime >= CHECK_INTERVAL_SECONDS
    except OSError:
        return True
