from __future__ import annotations

import os
import stat
import tempfile
import unittest
from pathlib import Path

from src.modules.hosts.hosts_file import decode, set_block, summarize, write_hosts
from src.modules.hosts.presets import PRESETS

USER = "# my notes\r\n127.0.0.1 local.test\r\n"


class BlockTests(unittest.TestCase):
    def test_add_keeps_user_lines_and_marks_block(self) -> None:
        text = set_block(USER, "block-max", [("0.0.0.0", "max.ru"), ("0.0.0.0", "oneme.com")])
        self.assertTrue(text.startswith(USER))
        self.assertIn("# >>> twowings:block-max >>>\r\n0.0.0.0 max.ru\r\n0.0.0.0 oneme.com\r\n# <<< twowings:block-max <<<", text)
        self.assertEqual(summarize(text).blocks, {"block-max": 2})
        self.assertEqual(summarize(text).entries, 3)

    def test_replace_and_remove(self) -> None:
        text = set_block(USER, "block-max", [("0.0.0.0", "max.ru")])
        text = set_block(text, "block-max", [("0.0.0.0", "oneme.com")])
        self.assertEqual(text.count("twowings:block-max >>>"), 1)
        self.assertNotIn("max.ru", text)
        removed = set_block(text, "block-max", None)
        self.assertEqual(removed, USER)

    def test_blocks_are_independent(self) -> None:
        text = set_block(USER, "a", [("1.1.1.1", "a.test")])
        text = set_block(text, "b", [("2.2.2.2", "b.test")])
        text = set_block(text, "a", None)
        self.assertEqual(summarize(text).blocks, {"b": 1})

    def test_comments_and_blank_lines_are_not_entries(self) -> None:
        self.assertEqual(summarize("# 1.2.3.4 x\n\n   \n1.2.3.4 y # note\n").entries, 1)

    def test_decode_falls_back_to_cp1251(self) -> None:
        self.assertEqual(decode("# заметка\n".encode("cp1251")), "# заметка\n")
        self.assertEqual(decode("﻿# bom\n".encode("utf-8")), "# bom\n")


class PresetTests(unittest.TestCase):
    def test_presets_are_well_formed(self) -> None:
        ids = [preset.id for preset in PRESETS]
        self.assertEqual(len(ids), len(set(ids)))
        for preset in PRESETS:
            self.assertRegex(preset.id, r"^[a-z0-9-]+$")
            self.assertEqual(len(preset.domains), len(set(preset.domains)), preset.id)
            for domain in preset.domains:
                self.assertRegex(domain, r"^[a-z0-9.-]+$")


class WriteTests(unittest.TestCase):
    def test_backup_once_and_read_only_flag_kept(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "hosts"
            path.write_text("original\n", encoding="utf-8")
            os.chmod(path, stat.S_IREAD)
            write_hosts("first\n", path)
            write_hosts("second\n", path)
            self.assertEqual(path.read_bytes(), b"second\r\n")
            self.assertEqual((Path(tmp) / "hosts.twowings.bak").read_text(encoding="utf-8"), "original\n")
            self.assertFalse(path.stat().st_mode & stat.S_IWRITE)
            os.chmod(path, stat.S_IREAD | stat.S_IWRITE)



class LegacyNameTests(unittest.TestCase):
    def test_blocks_of_the_previous_name_are_read_as_ours(self) -> None:
        import tempfile
        from pathlib import Path

        from src.modules.hosts.hosts_file import backup_path, read_hosts, summarize

        with tempfile.TemporaryDirectory() as tmp:
            hosts = Path(tmp) / "hosts"
            hosts.write_bytes(b"# >>> tigo:svc-a >>>\r\n1.2.3.4 a.example\r\n# <<< tigo:svc-a <<<\r\n# tigo: a comment\r\n")
            text = read_hosts(hosts)
            self.assertEqual(summarize(text).blocks, {"svc-a": 1})
            self.assertIn("# tigo: a comment", text)
            self.assertEqual(backup_path(hosts).name, "hosts.twowings.bak")
            (Path(tmp) / "hosts.tigo.bak").write_bytes(b"original")
            self.assertEqual(backup_path(hosts).name, "hosts.tigo.bak")


if __name__ == "__main__":
    unittest.main()
