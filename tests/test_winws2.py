from __future__ import annotations

import unittest
from pathlib import Path

from src.modules.strategies.winws2 import ConversionError, convert_winws1_argv, to_winws2_argv

LUA = Path(r"C:\2Wings\lua")
BIN = r"C:\2Wings Data\bin"


def convert(*argv: str) -> list[str]:
    return convert_winws1_argv(list(argv), lua_dir=LUA).argv


def body(argv: list[str]) -> list[str]:
    return [token for token in argv if not token.startswith(("--blob=", "--lua-init="))]


class GeneralStrategyTests(unittest.TestCase):
    def test_globals_blobs_and_lua_come_first(self) -> None:
        argv = convert(
            "--wf-tcp=80,443",
            "--wf-udp=443",
            "--filter-udp=443",
            "--dpi-desync=fake",
            "--dpi-desync-repeats=6",
            f"--dpi-desync-fake-quic={BIN}\\quic_initial_www_google_com.bin",
        )
        self.assertEqual(argv[:2], ["--wf-tcp-out=80,443", "--wf-udp-out=443"])
        self.assertIn(f"--blob=fs_quic_initial_www_google_com:@{BIN}\\quic_initial_www_google_com.bin", argv)
        self.assertIn(f"--lua-init=@{LUA / 'zapret-lib.lua'}", argv)
        self.assertIn(f"--lua-init=@{LUA / 'zapret-antidpi.lua'}", argv)
        self.assertEqual(
            body(argv)[2:],
            [
                "--filter-udp=443",
                "--payload=quic_initial",
                "--lua-desync=fake:blob=fs_quic_initial_www_google_com:repeats=6",
                "--payload=wireguard_initiation,dht,discord_ip_discovery,stun",
                "--lua-desync=fake:blob=twowings_zero64:repeats=6",
            ],
        )

    def test_filter_l7_limits_payload_groups(self) -> None:
        argv = body(
            convert(
                "--filter-udp=19294-19344",
                "--filter-l7=discord,stun",
                "--dpi-desync=fake",
                f"--dpi-desync-fake-discord={BIN}\\ACTIVE_DISCORD_UDP.bin",
                f"--dpi-desync-fake-stun={BIN}\\ACTIVE_DISCORD_UDP.bin",
                "--dpi-desync-repeats=6",
            )
        )
        self.assertEqual(
            argv[2:],
            ["--payload=discord_ip_discovery,stun", "--lua-desync=fake:blob=fs_active_discord_udp:repeats=6"],
        )

    def test_profiles_are_separated_and_blobs_deduplicated(self) -> None:
        pattern = f"--dpi-desync-split-seqovl-pattern={BIN}\\tls_clienthello_www_google_com.bin"
        result = convert(
            "--filter-tcp=443",
            "--dpi-desync=multisplit",
            "--dpi-desync-split-seqovl=681",
            "--dpi-desync-split-pos=1",
            pattern,
            "--new",
            "--filter-tcp=8443",
            "--dpi-desync=multisplit",
            "--dpi-desync-split-seqovl=681",
            pattern,
        )
        self.assertEqual(sum(token.startswith("--blob=") for token in result), 1)
        self.assertEqual(result.count("--new"), 1)
        self.assertIn(
            "--lua-desync=multisplit:pos=1:seqovl=681:seqovl_pattern=fs_tls_clienthello_www_google_com", result
        )


class FakeTlsTests(unittest.TestCase):
    def test_tls_mod_applies_to_last_fake(self) -> None:
        argv = convert(
            "--filter-tcp=443",
            "--dpi-desync=fake",
            "--dpi-desync-fake-tls=0x00000000",
            "--dpi-desync-fake-tls=!",
            "--dpi-desync-fake-tls-mod=rnd,dupsid,sni=www.google.com",
        )
        self.assertIn("--lua-desync=fake:blob=0x00000000", argv)
        self.assertIn("--lua-desync=fake:blob=fake_default_tls:tls_mod=rnd,dupsid,sni=www.google.com", argv)

    def test_default_tls_fake_keeps_nfqws1_randomisation(self) -> None:
        argv = convert("--filter-tcp=443", "--dpi-desync=fake")
        self.assertIn("--lua-desync=fake:blob=fake_default_tls:tls_mod=rnd,rndsni,dupsid", argv)
        self.assertIn("--lua-desync=fake:blob=fake_default_http", argv)

    def test_tls_mod_none_disables_randomisation(self) -> None:
        argv = convert("--filter-tcp=443", "--dpi-desync=fake", "--dpi-desync-fake-tls-mod=none")
        self.assertIn("--lua-desync=fake:blob=fake_default_tls", argv)


class FoolingTests(unittest.TestCase):
    def test_badseq_uses_nfqws1_defaults_and_ts_up(self) -> None:
        argv = convert("--filter-tcp=443", "--dpi-desync=fake", "--dpi-desync-fooling=badseq")
        self.assertIn(
            "--lua-desync=fake:blob=fake_default_http:tcp_seq=-10000:tcp_ack=-66000:tcp_ts_up",
            argv,
        )

    def test_custom_increments(self) -> None:
        argv = convert(
            "--filter-tcp=443",
            "--dpi-desync=fake",
            "--dpi-desync-fake-tls-mod=none",
            "--dpi-desync-fooling=badseq,ts",
            "--dpi-desync-badseq-increment=2",
            "--dpi-desync-ts-increment=-1000",
        )
        self.assertIn(
            "--lua-desync=fake:blob=fake_default_tls:tcp_seq=2:tcp_ack=-66000:tcp_ts_up:tcp_ts=-1000", argv
        )

    def test_fooling_and_repeats_skip_real_segments(self) -> None:
        argv = convert(
            "--filter-tcp=443",
            "--ip-id=zero",
            "--dpi-desync=fake,multisplit",
            "--dpi-desync-fooling=ts",
            "--dpi-desync-repeats=8",
            "--dpi-desync-fake-tls-mod=none",
        )
        self.assertIn("--lua-desync=fake:blob=fake_default_tls:tcp_ts=-600000:ip_id=zero:repeats=8", argv)
        self.assertIn("--lua-desync=multisplit:ip_id=zero", argv)

    def test_fakedsplit_fakes_get_fooling_and_pattern(self) -> None:
        argv = convert(
            "--filter-tcp=443",
            "--dpi-desync=fakedsplit",
            "--dpi-desync-fooling=md5sig",
            "--dpi-desync-repeats=6",
            "--dpi-desync-fakedsplit-pattern=0x00",
        )
        self.assertIn("--lua-desync=fakedsplit:pattern=0x00:tcp_md5:repeats=6", argv)

    def test_udp_fakes_drop_tcp_fooling(self) -> None:
        argv = convert("--filter-udp=443", "--dpi-desync=fake", "--dpi-desync-fooling=ts,badsum")
        self.assertIn("--lua-desync=fake:blob=fake_default_quic:badsum", argv)


class AnyProtocolTests(unittest.TestCase):
    def test_game_filter_tcp_adds_unknown_group_and_cutoff(self) -> None:
        argv = body(
            convert(
                "--filter-tcp=1024-65535",
                "--dpi-desync=multisplit",
                "--dpi-desync-any-protocol=1",
                "--dpi-desync-cutoff=n3",
                "--dpi-desync-split-pos=1",
            )
        )
        self.assertEqual(
            argv,
            [
                "--filter-tcp=1024-65535",
                "--out-range=<n3",
                "--payload=tls_client_hello,http_req",
                "--lua-desync=multisplit:pos=1",
                "--payload=all",
                "--lua-desync=multisplit:pos=1:payload=~tls_client_hello,http_req,empty",
            ],
        )

    def test_game_filter_udp_uses_unknown_fake(self) -> None:
        argv = convert(
            "--filter-udp=1024-65535",
            "--dpi-desync=fake",
            "--dpi-desync-any-protocol=1",
            "--dpi-desync-cutoff=d2",
            f"--dpi-desync-fake-unknown-udp={BIN}\\ACTIVE_GAME_UDP.bin",
        )
        self.assertIn("--out-range=<d2", argv)
        self.assertIn(
            "--lua-desync=fake:blob=fs_active_game_udp:payload="
            "~quic_initial,wireguard_initiation,dht,discord_ip_discovery,stun,empty",
            argv,
        )

    def test_without_any_protocol_unknown_is_untouched(self) -> None:
        argv = convert("--filter-tcp=1024-65535", "--dpi-desync=multisplit")
        self.assertNotIn("--payload=all", argv)

    def test_hostfakesplit_is_not_applied_to_unknown(self) -> None:
        result = convert_winws1_argv(
            [
                "--filter-tcp=1024-65535",
                "--dpi-desync=hostfakesplit",
                "--dpi-desync-any-protocol=1",
                "--dpi-desync-hostfakesplit-mod=host=ozon.ru,altorder=1",
            ],
            lua_dir=LUA,
        )
        self.assertIn("--lua-desync=hostfakesplit:host=ozon.ru", result.argv)
        self.assertNotIn("--payload=all", result.argv)
        self.assertEqual(len(result.warnings), 1)


class SyndataTests(unittest.TestCase):
    def test_syndata_runs_before_payload_filters(self) -> None:
        argv = body(convert("--filter-tcp=443", "--dpi-desync=syndata,multidisorder"))
        self.assertEqual(
            argv,
            [
                "--filter-tcp=443",
                "--lua-desync=syndata",
                "--payload=tls_client_hello,http_req",
                "--lua-desync=multidisorder_legacy",
            ],
        )


class StrictnessTests(unittest.TestCase):
    def test_unknown_option_is_rejected(self) -> None:
        with self.assertRaises(ConversionError):
            convert("--filter-tcp=443", "--dpi-desync=fake", "--dpi-desync-autottl=2")

    def test_unknown_mode_is_rejected(self) -> None:
        with self.assertRaises(ConversionError):
            convert("--filter-tcp=443", "--dpi-desync=ipfrag2")

    def test_fakedsplit_accepts_single_position(self) -> None:
        with self.assertRaises(ConversionError):
            convert("--filter-tcp=443", "--dpi-desync=fakedsplit", "--dpi-desync-split-pos=1,midsld")

    def test_profile_without_desync_only_filters(self) -> None:
        self.assertEqual(body(convert("--filter-tcp=443", "--hostlist=C:\\l.txt")), ["--filter-tcp=443", "--hostlist=C:\\l.txt"])


class NativeWinws2Tests(unittest.TestCase):
    def test_native_args_get_lua_library(self) -> None:
        argv = ["--filter-tcp=443", "--lua-desync=multisplit:pos=1"]
        result = to_winws2_argv(argv, lua_dir=LUA)
        self.assertEqual(result.argv[:2], [f"--lua-init=@{LUA / name}" for name in ("zapret-lib.lua", "zapret-antidpi.lua")])
        self.assertEqual(result.argv[2:], argv)

    def test_native_args_keep_own_lua_init(self) -> None:
        argv = [
            "--lua-init=@D:\\z\\zapret-lib.lua",
            "--lua-init=@D:\\z\\zapret-antidpi.lua",
            "--lua-desync=fake:blob=fake_default_tls",
        ]
        self.assertEqual(to_winws2_argv(argv, lua_dir=LUA).argv, argv)

    def test_mixed_syntax_is_rejected(self) -> None:
        with self.assertRaises(ConversionError):
            to_winws2_argv(["--lua-desync=fake", "--dpi-desync=fake"], lua_dir=LUA)


if __name__ == "__main__":
    unittest.main()
