from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.modules.updates.app import (
    AppUpdate,
    _version_tuple,
    download_verified_installer,
    fetch_app_update,
    launch_installer,
)


class AppUpdateTests(unittest.TestCase):
    def test_semver_comparison_is_numeric(self) -> None:
        self.assertGreater(_version_tuple("1.10.0"), _version_tuple("1.9.9"))

    def test_release_requires_installer_and_checksum(self) -> None:
        response = MagicMock()
        response.json.return_value = {
            "assets": [
                {
                    "name": "2Wings-Setup-9.9.9.exe",
                    "browser_download_url": "https://example.test/setup.exe",
                },
                {
                    "name": "2Wings-Setup-9.9.9.exe.sha256",
                    "browser_download_url": "https://example.test/setup.sha256",
                },
            ]
        }
        client = MagicMock()
        client.__enter__.return_value.get.return_value = response
        client.__exit__.return_value = None
        with patch("src.modules.updates.app.httpx.Client", return_value=client):
            update = fetch_app_update()

        self.assertIsNotNone(update)
        self.assertEqual(update.version, "9.9.9")

    def test_download_rejects_invalid_checksum(self) -> None:
        update = AppUpdate(
            "9.9.9",
            "https://example.test/setup.exe",
            "https://example.test/setup.sha256",
            "2Wings-Setup-9.9.9.exe",
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            def fake_download(_client, url: str, destination: Path) -> None:
                if url.endswith(".sha256"):
                    destination.write_bytes(b"0" * 64)
                else:
                    destination.write_bytes(b"installer")

            with (
                patch("src.modules.updates.app.temp_dir", return_value=root),
                patch("src.modules.updates.app._download", side_effect=fake_download),
            ):
                with self.assertRaises(ValueError):
                    download_verified_installer(update)

    def test_download_accepts_matching_checksum(self) -> None:
        payload = b"verified installer"
        digest = hashlib.sha256(payload).hexdigest()
        update = AppUpdate(
            "9.9.9",
            "https://example.test/setup.exe",
            "https://example.test/setup.sha256",
            "2Wings-Setup-9.9.9.exe",
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            def fake_download(_client, url: str, destination: Path) -> None:
                if url.endswith(".sha256"):
                    destination.write_bytes(digest.encode())
                else:
                    destination.write_bytes(payload)

            with (
                patch("src.modules.updates.app.temp_dir", return_value=root),
                patch("src.modules.updates.app._download", side_effect=fake_download),
            ):
                installer = download_verified_installer(update)

            self.assertEqual(installer.read_bytes(), payload)

    def test_download_uses_partial_when_installer_is_locked(self) -> None:
        payload = b"verified installer"
        digest = hashlib.sha256(payload).hexdigest()
        update = AppUpdate(
            "9.9.9",
            "https://example.test/setup.exe",
            "https://example.test/setup.sha256",
            "2Wings-Setup-9.9.9.exe",
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            def fake_download(_client, url: str, destination: Path) -> None:
                if url.endswith(".sha256"):
                    destination.write_bytes(digest.encode())
                else:
                    destination.write_bytes(payload)

            with (
                patch("src.modules.updates.app.temp_dir", return_value=root),
                patch("src.modules.updates.app._download", side_effect=fake_download),
                patch("src.modules.updates.app.os.replace", side_effect=PermissionError),
            ):
                installer = download_verified_installer(update)

            self.assertEqual(installer.name, "2Wings-Setup-9.9.9.exe.part")
            self.assertEqual(installer.read_bytes(), payload)

    def test_download_reuses_verified_installer_without_redownload(self) -> None:
        payload = b"verified installer"
        digest = hashlib.sha256(payload).hexdigest()
        update = AppUpdate(
            "9.9.9",
            "https://example.test/setup.exe",
            "https://example.test/setup.sha256",
            "2Wings-Setup-9.9.9.exe",
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            update_dir = root / "app-update"
            update_dir.mkdir()
            installer = update_dir / update.installer_name
            installer.write_bytes(payload)
            (update_dir / f"{update.installer_name}.sha256").write_text(digest, encoding="utf-8")

            with (
                patch("src.modules.updates.app.temp_dir", return_value=root),
                patch("src.modules.updates.app._download") as download,
            ):
                result = download_verified_installer(update)

            download.assert_not_called()
            self.assertEqual(result, installer)

    def test_parallel_install_attempt_returns_warning(self) -> None:
        from src.modules.updates import app as app_updates

        app_updates._install_lock.acquire()
        try:
            ok, message, kind = app_updates.check_and_install_app()
        finally:
            app_updates._install_lock.release()

        self.assertFalse(ok)
        self.assertEqual(kind, "warning")
        self.assertIn("уже выполняется", message.lower())

    def test_installer_launch_uses_silent_update_flags(self) -> None:
        installer = Path("2Wings-Setup-9.9.9.exe")
        with (
            patch("src.modules.updates.app.is_packaged_app", return_value=True),
            patch("src.modules.updates.app.subprocess.Popen") as popen,
        ):
            launch_installer(installer)

        args = popen.call_args.args[0]
        self.assertIn("/VERYSILENT", args)
        self.assertIn("/TWOWINGSRELAUNCH=1", args)


if __name__ == "__main__":
    unittest.main()


class VersionOrderTests(unittest.TestCase):
    def test_dev_build_is_older_than_its_release(self) -> None:
        from src.modules.updates.app import _version_tuple

        self.assertLess(_version_tuple("1.5.0-dev"), _version_tuple("1.5.0"))
        self.assertLess(_version_tuple("1.4.0"), _version_tuple("1.5.0-dev"))
        self.assertEqual(_version_tuple("v1.5.0"), _version_tuple("1.5.0"))
