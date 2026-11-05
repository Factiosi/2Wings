from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.modules.strategies.winws2 import TLS_ALERT_FILTER, inject_tls_watch
from src.modules.tls_exclude.watcher import MARK, Report, apply_reports, parse_reports, take_reports

SCRIPT = Path(r"C:\2Wings\assets\lua\twowings-tls-watch.lua")
WRITABLE = Path(r"C:\Users\u\AppData\Roaming\2Wings\cache\winws2")
WATCH = ["--out-range=x", "--in-range=a"]
RESET = ["--in-range=x", "--out-range=a"]


class InjectTests(unittest.TestCase):
    def test_every_profile_gets_watch_with_the_right_exclude_mode(self) -> None:
        argv = [
            "--wf-tcp-out=443",
            "--lua-init=@C:\\2Wings\\lua\\zapret-antidpi.lua",
            "--filter-tcp=443",
            "--hostlist-exclude=C:\\l\\list-exclude.txt",
            "--lua-desync=fake",
            "--new",
            "--filter-udp=1024-65535",
            "--ipset=C:\\l\\ipset-all.txt",
            "--out-range=<n2",
            "--lua-desync=fake",
        ]
        result = inject_tls_watch(argv, script=SCRIPT, writable_dir=WRITABLE)
        self.assertEqual(result[:2], [f"--writable={WRITABLE}", f"--wf-raw-part={TLS_ALERT_FILTER}"])
        first = result.index("--lua-desync=twowings_tls_watch")
        self.assertEqual(result[first - 2 : first], WATCH)
        self.assertEqual(result[first + 1 : first + 3], RESET)
        new = result.index("--new")
        self.assertEqual(result[new + 3], "--lua-desync=twowings_tls_watch:exclude=ip")
        self.assertLess(new + 3, result.index("--out-range=<n2"))
        init = result.index("--lua-init=@C:\\2Wings\\lua\\zapret-antidpi.lua")
        self.assertEqual(result[init + 1], f"--lua-init=@{SCRIPT}")

    def test_filter_matches_fatal_alerts_and_http_replies_off_port_80(self) -> None:
        self.assertIn("tcp.Payload[0] == 21", TLS_ALERT_FILTER)
        self.assertIn("tcp.Payload[5] == 2", TLS_ALERT_FILTER)
        self.assertIn("tcp.SrcPort != 80 and tcp.Payload[0] == 72", TLS_ALERT_FILTER)  # "HTTP/"
        self.assertTrue(TLS_ALERT_FILTER.startswith("inbound and tcp"))
        self.assertEqual(TLS_ALERT_FILTER.count("("), TLS_ALERT_FILTER.count(")"))


class ReportTests(unittest.TestCase):
    def test_parse(self) -> None:
        text = "d Example.COM 104.16.1.1 40\ni - 185.10.10.10 80\ngarbage\nd a.b 1.1.1.1 x\n"
        self.assertEqual(
            parse_reports(text),
            [
                Report("d", "example.com", "104.16.1.1", 40),
                Report("i", None, "185.10.10.10", 80),
                Report("d", "a.b", "1.1.1.1", -1),
            ],
        )

    def test_apply_appends_once_with_mark_and_skips_private(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            lists = Path(tmp)
            (lists / "list-exclude-user.txt").write_text("domain.example.abc", encoding="utf-8")
            reports = [
                Report("d", "broken.example", "104.16.1.1", 40),
                Report("d", "broken.example", "104.16.1.2", 40),
                Report("i", None, "185.10.10.10", 80),
                Report("i", None, "192.168.1.5", 80),
                Report("d", "not a domain", None, 40),
            ]
            added = apply_reports(reports, lists)
            self.assertEqual(added, ["broken.example", "185.10.10.10/32"])
            self.assertEqual(
                (lists / "list-exclude-user.txt").read_text(encoding="utf-8"),
                f"domain.example.abc\n{MARK}\nbroken.example\n",
            )
            self.assertEqual((lists / "ipset-exclude-user.txt").read_text(encoding="utf-8"), f"{MARK}\n185.10.10.10/32\n")
            self.assertEqual(apply_reports(reports, lists), [])

    def test_take_moves_the_file_aside(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "tls-alerts.txt"
            self.assertEqual(take_reports(path), "")
            path.write_text("d x.example 1.2.3.4 40\n", encoding="utf-8")
            self.assertEqual(take_reports(path), "d x.example 1.2.3.4 40\n")
            self.assertEqual(list(Path(tmp).iterdir()), [])


if __name__ == "__main__":
    unittest.main()


class LuaScriptTests(unittest.TestCase):
    def test_the_script_defines_the_function_the_arguments_call(self) -> None:
        from src.core.paths import tls_watch_script
        from src.modules.strategies.winws2 import inject_tls_watch

        argv = inject_tls_watch(["--new"], script=tls_watch_script(), writable_dir=Path("w"))
        called = {arg.split("=", 1)[1].split(":", 1)[0] for arg in argv if arg.startswith("--lua-desync=")}
        self.assertTrue(called)
        source = tls_watch_script().read_text(encoding="utf-8")
        for name in called:
            self.assertIn(f"function {name}(", source)
