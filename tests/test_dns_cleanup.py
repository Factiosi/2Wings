from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.core.settings import AppSettings
from src.modules.dns import cleanup
from src.modules.dns.cleanup import clean_adapters, clean_retired_dns
from src.modules.dns.service import flatten_providers
from src.modules.hosts.hosts_file import set_block
from src.modules.hosts.service import hosts_uses_addresses

RETIRED = "38.180.241.191"
RETIRED_V6 = "2a03:afc0:9::235d"


def _manager(servers: dict[tuple[str, str], list[str]]) -> MagicMock:
    manager = MagicMock()
    manager.get_network_adapters_fast.return_value = sorted({(name, "") for name, _family in servers})
    manager.get_current_dns.side_effect = lambda name, family: servers.get((name, family), [])
    manager.set_custom_dns.return_value = (True, "OK")
    manager.set_auto_dns.return_value = (True, "")
    return manager


class AdapterCleanupTests(unittest.TestCase):
    def test_lone_retired_server_returns_the_adapter_to_automatic(self) -> None:
        manager = _manager({("Ethernet", "IPv4"): [RETIRED], ("Ethernet", "IPv6"): [RETIRED_V6.upper()]})
        self.assertEqual(clean_adapters(manager), ["Ethernet", "Ethernet"])
        self.assertEqual([call.args for call in manager.set_auto_dns.call_args_list], [("Ethernet", "IPv4"), ("Ethernet", "IPv6")])
        manager.set_custom_dns.assert_not_called()

    def test_the_users_other_server_stays(self) -> None:
        manager = _manager({("Ethernet", "IPv4"): [RETIRED, "1.1.1.1"]})
        clean_adapters(manager)
        manager.set_custom_dns.assert_called_once_with("Ethernet", "1.1.1.1", None, "IPv4")
        manager.set_auto_dns.assert_not_called()

    def test_other_adapters_are_left_alone(self) -> None:
        manager = _manager({("Wi-Fi", "IPv4"): ["8.8.8.8"], ("Wi-Fi", "IPv6"): []})
        self.assertEqual(clean_adapters(manager), [])
        manager.set_custom_dns.assert_not_called()
        manager.set_auto_dns.assert_not_called()


class HostsCleanupTests(unittest.TestCase):
    def test_active_line_counts_and_a_comment_does_not(self) -> None:
        text = set_block("# 5.129.221.64 old.example\r\n", "svc-a", [("104.18.1.1", "a.example")])
        with patch("src.modules.hosts.service.read_hosts", return_value=text):
            self.assertFalse(hosts_uses_addresses({"5.129.221.64"}))
            self.assertTrue(hosts_uses_addresses({"104.18.1.1"}))

    def _clean(self, *, in_hosts: bool) -> MagicMock:
        settings = AppSettings(hosts_services={"dns.chat": "comss_dns"})
        with (
            patch.object(cleanup, "DNSManager", return_value=_manager({})),
            patch.object(cleanup, "hosts_uses_addresses", return_value=in_hosts),
            patch.object(cleanup, "reload_settings", return_value=settings),
            patch.object(cleanup, "apply_services", return_value=(True, "ok")) as apply,
        ):
            clean_retired_dns()
        return apply

    def test_hosts_with_a_retired_relay_are_rewritten(self) -> None:
        self._clean(in_hosts=True).assert_called_once_with({"dns.chat": "comss_dns"})

    def test_clean_hosts_are_not_touched(self) -> None:
        self._clean(in_hosts=False).assert_not_called()


class SettingsMigrationTests(unittest.TestCase):
    def test_saved_profile_moves_to_comss(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"
            path.write_text(
                json.dumps({"hosts_profile": "zapret_dns", "hosts_services": {"dns.chat": "zapret_dns", "hosts.direct": "hosts"}}),
                encoding="utf-8",
            )
            loaded = AppSettings.load(path)
        self.assertEqual(loaded.hosts_profile, "comss_dns")
        self.assertEqual(loaded.hosts_services, {"dns.chat": "comss_dns", "hosts.direct": "hosts"})

    def test_fresh_settings_use_comss(self) -> None:
        self.assertEqual(AppSettings().hosts_profile, "comss_dns")


class ProviderListTests(unittest.TestCase):
    def test_dns_page_offers_exactly_these(self) -> None:
        names = {row[1]: row[3] for row in flatten_providers()}
        self.assertEqual(set(names), {"Comss DNS", "Cloudflare", "Google DNS", "Quad9"})
        self.assertEqual(names["Quad9"], ["9.9.9.9", "149.112.112.112"])


if __name__ == "__main__":
    unittest.main()
