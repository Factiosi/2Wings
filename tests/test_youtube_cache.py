from __future__ import annotations

import unittest

from src.modules.hosts.hosts_file import set_block, summarize
from src.modules.hosts.youtube_cache import BLOCK_ID, CheckResult, Server, blocked_hosts, block_text, nodes_in

USER = "# my notes\r\n127.0.0.1 local.test\r\n"
A1 = "rr1---sn-8ph2xajvh-3ggs.googlevideo.com"
A3 = "rr3---sn-8ph2xajvh-3ggs.googlevideo.com"
A4 = "rr4---sn-8ph2xajvh-3ggs.googlevideo.com"


class YoutubeCacheTests(unittest.TestCase):
    def test_nodes_come_from_server_names(self) -> None:
        page = f'"url":"https://{A3}/videoplayback?x=1","u":"https://rr12---sn-xguxaxjvh-2x1e.googlevideo.com/v"'
        self.assertEqual(nodes_in(page), {"sn-8ph2xajvh-3ggs", "sn-xguxaxjvh-2x1e"})

    def test_dead_servers_are_closed_and_recovered_opened(self) -> None:
        first = CheckResult("2026-11-15T12:00:00", [Server(A1, "1.1.1.1", True), Server(A3, "1.1.1.3", False)])
        text = block_text(USER, first)
        self.assertTrue(text.startswith(USER))
        self.assertEqual(blocked_hosts(text), {A3})
        second = CheckResult("2026-11-15T13:00:00", [Server(A3, "1.1.1.3", True), Server(A4, "1.1.1.4", False)])
        self.assertEqual(blocked_hosts(block_text(text, second)), {A4})
        recovered = CheckResult("2026-11-15T14:00:00", [Server(A3, "1.1.1.3", True), Server(A4, "1.1.1.4", True)])
        self.assertEqual(block_text(text, recovered), USER)

    def test_nothing_changes_without_network(self) -> None:
        text = set_block(USER, BLOCK_ID, [("0.0.0.0", A3)])
        all_dead = CheckResult("t", [Server(A1, "1.1.1.1", False), Server(A3, "1.1.1.3", False)])
        self.assertEqual(block_text(text, all_dead), text)
        self.assertEqual(block_text(text, CheckResult("t", [], "YouTube не ответил")), text)

    def test_other_blocks_are_not_read(self) -> None:
        text = set_block(USER, "fix-youtube", [("0.0.0.0", A4)])
        self.assertEqual(blocked_hosts(text), set())
        self.assertEqual(summarize(block_text(text, CheckResult("t", [Server(A3, "1", False), Server(A1, "2", True)]))).blocks,
                         {"fix-youtube": 1, BLOCK_ID: 1})


if __name__ == "__main__":
    unittest.main()
