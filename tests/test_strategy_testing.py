from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.modules.strategy_testing import cache
from src.modules.strategy_testing import results as tr
from src.modules.strategy_testing.probe import TargetProbeResult, load_targets, score_results
from src.modules.strategy_testing.runner import INTER_STRATEGY_PAUSE_SECONDS
from src.ui.pages.strategies import compute_expanded_state


class ProbeTargetTests(unittest.TestCase):
    def test_builtin_profile_contains_all_targets(self) -> None:
        targets = load_targets()
        self.assertEqual(len(targets), 17)
        self.assertEqual(
            [target.name for target in targets],
            [
                "DiscordMain",
                "DiscordGateway",
                "DiscordCDN",
                "DiscordUpdates",
                "YouTubeWeb",
                "YouTubeShort",
                "YouTubeImage",
                "YouTubeVideoRedirect",
                "GoogleMain",
                "GoogleGstatic",
                "CloudflareWeb",
                "CloudflareCDN",
                "CloudflareDNS1111",
                "CloudflareDNS1001",
                "GoogleDNS8888",
                "GoogleDNS8844",
                "Quad9DNS9999",
            ],
        )

    def test_explicit_target_file_overrides_builtin_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "targets.txt"
            path.write_text(
                'ExampleWeb = "https://example.com"\nExamplePing = "PING:1.1.1.1"\n',
                encoding="utf-8",
            )
            targets = load_targets(path)

        self.assertEqual([target.name for target in targets], ["ExampleWeb", "ExamplePing"])
        self.assertEqual(targets[1].ping_host, "1.1.1.1")


class ScoreTests(unittest.TestCase):
    def test_tls13_does_not_affect_the_verdict(self) -> None:
        results = [
            TargetProbeResult("A", ("HTTP:OK", "TLS1.2:OK", "TLS1.3:UNSUP"), "10 ms"),
            TargetProbeResult("B", ("HTTP:OK", "TLS1.2:OK", "TLS1.3:ERROR"), "10 ms"),
        ]
        self.assertEqual(score_results(results), (4, 4))
        results.append(TargetProbeResult("C", ("HTTP:OK", "TLS1.2:ERROR", "TLS1.3:OK"), "10 ms"))
        self.assertEqual(score_results(results), (5, 6))


class ResultCacheSchemaTests(unittest.TestCase):
    def test_stale_three_target_cache_is_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "test_results.json"
            path.write_text(
                json.dumps(
                    {
                        "schema": 1,
                        "versions": {
                            "1.10.1": {
                                "general": {
                                    "state": "full",
                                    "rows": [{"name": "DiscordMain"}],
                                }
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            with patch(
                "src.modules.strategy_testing.cache.test_results_cache_path",
                return_value=path,
            ):
                self.assertEqual(cache.load_all_versions(), {})


class LiveProbeTests(unittest.TestCase):
    def test_remote_snapshot_updates_cells_incrementally(self) -> None:
        version = "test-live-probe"
        strategy_id = "flowseal:test"
        tr.init_probe_table(strategy_id, version=version)
        tr.set_probe_loading(strategy_id, version=version)
        snapshot = tr.probe_snapshot(strategy_id, version=version)
        self.assertEqual(snapshot[0]["http"]["phase"], "loading")

        snapshot[0]["http"] = {"phase": "done", "text": "HTTP:OK"}
        snapshot[0]["ping"] = {"phase": "done", "text": "42 ms"}
        tr.apply_remote_probe_snapshot(strategy_id, snapshot, version=version)
        table = tr.get_probe_table(strategy_id, version=version)

        self.assertEqual(table[0].http.text, "HTTP:OK")
        self.assertEqual(table[0].ping.text, "42 ms")
        self.assertEqual(table[1].http.phase, "loading")


class ProbeTableViewTests(unittest.TestCase):
    def test_loading_spinner_is_reused_between_syncs(self) -> None:
        from src.ui.probe_table import ProbeTableView

        version = "test-probe-view"
        strategy_id = "flowseal:spinner"
        with patch("src.modules.strategy_testing.results._resolve_version", return_value=version):
            tr.init_probe_table(strategy_id, version=version)
            tr.set_probe_loading(strategy_id, version=version)

            view = ProbeTableView(strategy_id)
            loading_key = ("YouTubeWeb", "http")
            spinner = view._spinners[loading_key]
            view.sync(strategy_id)
            self.assertIs(view._spinners[loading_key], spinner)

            snapshot = tr.probe_snapshot(strategy_id, version=version)
            for row in snapshot:
                if row["name"] == "YouTubeWeb":
                    row["http"] = {"phase": "done", "text": "HTTP:OK"}
                    break
            tr.apply_remote_probe_snapshot(strategy_id, snapshot, version=version)
            view.sync(strategy_id)
            self.assertNotIn(loading_key, view._spinners)
            self.assertIn(("YouTubeWeb", "ping"), view._spinners)


class TestUiStateTests(unittest.TestCase):
    def test_mass_run_focuses_only_current_strategy(self) -> None:
        self.assertEqual(
            compute_expanded_state(
                running=True,
                current_strategy_id="two",
                session_active=True,
                planned_strategy_ids={"one", "two"},
                completed_strategy_ids={"one"},
                current_expanded={"one"},
            ),
            {"two"},
        )

    def test_finished_run_expands_all_completed_strategies(self) -> None:
        self.assertEqual(
            compute_expanded_state(
                running=False,
                current_strategy_id=None,
                session_active=True,
                planned_strategy_ids={"one", "two"},
                completed_strategy_ids={"one", "two"},
                current_expanded={"two"},
            ),
            {"one", "two"},
        )

    def test_finished_run_expands_only_planned_completed_strategies(self) -> None:
        self.assertEqual(
            compute_expanded_state(
                running=False,
                current_strategy_id=None,
                session_active=True,
                planned_strategy_ids={"one", "two"},
                completed_strategy_ids={"one", "two", "three"},
                current_expanded=set(),
            ),
            {"one", "two"},
        )

    def test_inter_strategy_pause_is_two_seconds(self) -> None:
        self.assertEqual(INTER_STRATEGY_PAUSE_SECONDS, 2.0)

    def test_pause_keeps_completed_strategy_expanded(self) -> None:
        self.assertEqual(
            compute_expanded_state(
                running=True,
                current_strategy_id="one",
                session_active=True,
                planned_strategy_ids={"one", "two"},
                completed_strategy_ids={"one"},
                current_expanded={"one"},
            ),
            {"one"},
        )


class StrategyActionTests(unittest.TestCase):
    def test_action_buttons_follow_tested_and_selected_state(self) -> None:
        from src.ui.strategy_status import strategy_actions_disabled

        with patch("src.ui.strategy_status.tr.is_tested", return_value=False):
            self.assertTrue(
                strategy_actions_disabled("a", selected_strategy=None, tests_running=False)
            )
        with patch("src.ui.strategy_status.tr.is_tested", return_value=True):
            self.assertTrue(
                strategy_actions_disabled("a", selected_strategy="a", tests_running=False)
            )
            self.assertTrue(
                strategy_actions_disabled("a", selected_strategy="b", tests_running=True)
            )
            self.assertFalse(
                strategy_actions_disabled("a", selected_strategy="b", tests_running=False)
            )


if __name__ == "__main__":
    unittest.main()
