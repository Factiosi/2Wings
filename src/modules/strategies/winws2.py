"""Translate winws1 (nfqws1) arguments into winws2 (nfqws2 + Lua) arguments.

Flowseal publishes strategies for winws1. winws2 has no built-in desync modes:
every attack is a Lua function called with ``--lua-desync``, and payload,
direction and cutoff filtering moved into ``--payload`` / ``--out-range``.
The translation keeps the nfqws1 semantics as closely as winws2 allows:

* every fake of nfqws1 becomes its own ``fake`` instance, grouped by payload
  type exactly like nfqws1 picked ``--dpi-desync-fake-tls`` / ``-http`` / ...;
* defaults nfqws1 used silently (built-in TLS/HTTP/QUIC fakes, zero-filled
  unknown fakes, ``rnd,rndsni,dupsid`` on the default TLS fake) are spelled out;
* ``--dpi-desync-any-protocol`` adds a group for everything nfqws1 treated as
  unknown, ``--dpi-desync-cutoff`` becomes ``--out-range``;
* fooling goes only to fakes: in winws2 fooling of multisplit/multidisorder
  would corrupt the real segments.

Options without a faithful winws2 equivalent raise ``ConversionError`` instead
of being dropped, so a strategy never runs with silently changed behaviour.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

LUA_SCRIPTS = ("zapret-lib.lua", "zapret-antidpi.lua")

_WINWS2_MARKERS = frozenset(
    {
        "lua-desync",
        "lua-init",
        "blob",
        "payload",
        "out-range",
        "in-range",
        "wf-tcp-out",
        "wf-udp-out",
        "wf-tcp-in",
        "wf-udp-in",
    }
)

_GLOBAL_RENAMES = {"wf-tcp": "wf-tcp-out", "wf-udp": "wf-udp-out"}
_GLOBAL_PASSTHROUGH = frozenset(
    {
        "wf-l3",
        "wf-raw",
        "wf-save",
        "wf-iface",
        "wf-filter-lan",
        "wf-dup-check",
        "debug",
        "ctrack-timeouts",
        "ctrack-disable",
        "ipcache-lifetime",
        "ipcache-hostname",
        "comment",
    }
)
_PROFILE_PASSTHROUGH = frozenset(
    {
        "filter-l3",
        "filter-tcp",
        "filter-udp",
        "filter-l7",
        "hostlist",
        "hostlist-domains",
        "hostlist-exclude",
        "hostlist-exclude-domains",
        "hostlist-auto",
        "hostlist-auto-fail-threshold",
        "hostlist-auto-fail-time",
        "hostlist-auto-retrans-threshold",
        "hostlist-auto-debug",
        "ipset",
        "ipset-ip",
        "ipset-exclude",
        "ipset-exclude-ip",
    }
)
_PROFILE_DESYNC = frozenset(
    {
        "ip-id",
        "dpi-desync",
        "dpi-desync-repeats",
        "dpi-desync-fooling",
        "dpi-desync-ttl",
        "dpi-desync-ttl6",
        "dpi-desync-ts-increment",
        "dpi-desync-badseq-increment",
        "dpi-desync-badack-increment",
        "dpi-desync-split-pos",
        "dpi-desync-split-seqovl",
        "dpi-desync-split-seqovl-pattern",
        "dpi-desync-fakedsplit-pattern",
        "dpi-desync-fakedsplit-mod",
        "dpi-desync-hostfakesplit-mod",
        "dpi-desync-hostfakesplit-midhost",
        "dpi-desync-any-protocol",
        "dpi-desync-cutoff",
        "dpi-desync-fake-tls",
        "dpi-desync-fake-tls-mod",
        "dpi-desync-fake-http",
        "dpi-desync-fake-unknown",
        "dpi-desync-fake-syndata",
        "dpi-desync-fake-quic",
        "dpi-desync-fake-wireguard",
        "dpi-desync-fake-dht",
        "dpi-desync-fake-discord",
        "dpi-desync-fake-stun",
        "dpi-desync-fake-unknown-udp",
    }
)

_MODE_ALIASES = {
    "fake": "fake",
    "fakeknown": "fakeknown",
    "syndata": "syndata",
    "multisplit": "multisplit",
    "split2": "multisplit",
    "multidisorder": "multidisorder",
    "disorder2": "multidisorder",
    "fakedsplit": "fakedsplit",
    "split": "fakedsplit",
    "fakeddisorder": "fakeddisorder",
    "disorder": "fakeddisorder",
    "hostfakesplit": "hostfakesplit",
}
_SPLIT_MODES = ("multisplit", "multidisorder", "fakedsplit", "fakeddisorder", "hostfakesplit")
# multidisorder_legacy is the nfqws1-compatible variant (per-segment replay order).
_SPLIT_FUNCTIONS = {
    "multisplit": "multisplit",
    "multidisorder": "multidisorder_legacy",
    "fakedsplit": "fakedsplit",
    "fakeddisorder": "fakeddisorder",
    "hostfakesplit": "hostfakesplit",
}
_FAKING_SPLITS = frozenset({"fakedsplit", "fakeddisorder", "hostfakesplit"})

# Payloads nfqws1 recognised. Anything else was "unknown" for nfqws1.
_TCP_GROUPS = (("tls", "tls_client_hello"), ("http", "http_req"))
_UDP_GROUPS = (
    ("quic", "quic_initial"),
    ("wireguard", "wireguard_initiation"),
    ("dht", "dht"),
    ("discord", "discord_ip_discovery"),
    ("stun", "stun"),
)
_FAKE_OPTION_BY_GROUP = {
    "tls": "dpi-desync-fake-tls",
    "http": "dpi-desync-fake-http",
    "quic": "dpi-desync-fake-quic",
    "wireguard": "dpi-desync-fake-wireguard",
    "dht": "dpi-desync-fake-dht",
    "discord": "dpi-desync-fake-discord",
    "stun": "dpi-desync-fake-stun",
}

# nfqws1 built-in fakes and their winws2 counterparts.
DEFAULT_TLS_BLOB = "fake_default_tls"
DEFAULT_HTTP_BLOB = "fake_default_http"
DEFAULT_QUIC_BLOB = "fake_default_quic"
ZERO64_BLOB = "twowings_zero64"
ZERO256_BLOB = "twowings_zero256"
_ZERO_BLOBS = {ZERO64_BLOB: 64, ZERO256_BLOB: 256}
_DEFAULT_TLS_MOD = "rnd,rndsni,dupsid"

_DEFAULT_TS_INCREMENT = "-600000"
_DEFAULT_BADSEQ_INCREMENT = "-10000"
_DEFAULT_BADACK_INCREMENT = "-66000"

_CUTOFF = re.compile(r"^([nds]?)(\d+)$")
_IDENT = re.compile(r"[^A-Za-z0-9_]+")


class ConversionError(ValueError):
    """The winws1 strategy uses something winws2 cannot express faithfully."""


@dataclass(frozen=True)
class Winws2Args:
    argv: list[str]
    warnings: list[str] = field(default_factory=list)


def is_winws2_argv(argv: list[str]) -> bool:
    return any(token.startswith("--") and _split(token)[0] in _WINWS2_MARKERS for token in argv)


def _split(token: str) -> tuple[str, str | None]:
    body = token[2:]
    key, sep, value = body.partition("=")
    return key, (value if sep else None)


def _parse(argv: list[str]) -> list[tuple[str, str | None]]:
    options: list[tuple[str, str | None]] = []
    index = 0
    while index < len(argv):
        token = argv[index]
        if not token.startswith("--"):
            raise ConversionError(f"Неожиданный аргумент без ключа: {token}")
        key, value = _split(token)
        if value is None and key not in {"new", "dpi-desync-any-protocol"}:
            nxt = argv[index + 1] if index + 1 < len(argv) else None
            if nxt is not None and not nxt.startswith("--"):
                value = nxt
                index += 1
        options.append((key, value))
        index += 1
    return options


def _lua_escape(value: str) -> str:
    # winws2 splits --lua-desync on ':' and substitutes a leading '%' or '#'.
    escaped = value.replace(":", "\\:")
    return "\\" + escaped if escaped[:1] in {"%", "#"} else escaped


def _instance(function: str, args: list[tuple[str, str | None]]) -> str:
    parts = [function]
    for key, value in args:
        parts.append(key if value is None else f"{key}={_lua_escape(value)}")
    return "--lua-desync=" + ":".join(parts)


class _Blobs:
    """Assign Lua variable names to fake files and collect ``--blob`` options."""

    def __init__(self) -> None:
        self._by_path: dict[str, str] = {}
        self._options: list[str] = []
        self._zeros: set[str] = set()

    def ref(self, value: str) -> str:
        text = value.strip()
        if text.lower().startswith("0x"):
            return text
        key = str(Path(text)).lower()
        if key in self._by_path:
            return self._by_path[key]
        base = "fs_" + (_IDENT.sub("_", Path(text).stem).strip("_").lower() or "blob")
        name = base
        suffix = 2
        while name in self._by_path.values():
            name = f"{base}_{suffix}"
            suffix += 1
        self._by_path[key] = name
        self._options.append(f"--blob={name}:@{text}")
        return name

    def zero(self, name: str) -> str:
        self._zeros.add(name)
        return name

    def options(self) -> list[str]:
        zeros = [f"--blob={name}:0x{'00' * _ZERO_BLOBS[name]}" for name in sorted(self._zeros)]
        return [*self._options, *zeros]


@dataclass
class _Profile:
    filters: list[str] = field(default_factory=list)
    modes: list[str] = field(default_factory=list)
    repeats: str | None = None
    fooling: list[str] = field(default_factory=list)
    ttl: str | None = None
    ttl6: str | None = None
    ts_increment: str = _DEFAULT_TS_INCREMENT
    badseq_increment: str = _DEFAULT_BADSEQ_INCREMENT
    badack_increment: str = _DEFAULT_BADACK_INCREMENT
    ip_id: str | None = None
    split_pos: str | None = None
    seqovl: str | None = None
    seqovl_pattern: str | None = None
    fakedsplit_pattern: str | None = None
    hfs_host: str | None = None
    hfs_midhost: str | None = None
    any_protocol: bool = False
    cutoff: str | None = None
    syndata_blob: str | None = None
    tls_fakes: list[list] = field(default_factory=list)  # [value, mod]
    tls_mod_last: str | None = None
    fakes: dict[str, list[str]] = field(default_factory=dict)
    has_tcp: bool = False
    has_udp: bool = False
    l7: set[str] | None = None


def _read_profile(options: list[tuple[str, str | None]], warnings: list[str], number: int) -> _Profile:
    profile = _Profile()
    for key, value in options:
        if key in _PROFILE_PASSTHROUGH:
            if value is None:
                raise ConversionError(f"--{key} без значения.")
            profile.filters.append(f"--{key}={value}")
            if key == "filter-tcp":
                profile.has_tcp = True
            elif key == "filter-udp":
                profile.has_udp = True
            elif key == "filter-l7":
                profile.l7 = {item.strip().lower() for item in value.split(",") if item.strip()}
            continue
        if key not in _PROFILE_DESYNC:
            raise ConversionError(f"Опция --{key} не поддерживается конвертером winws2.")
        if key == "dpi-desync-any-protocol":
            profile.any_protocol = value is None or value.strip() not in {"", "0"}
            continue
        if value is None:
            raise ConversionError(f"--{key} без значения.")
        if key == "dpi-desync":
            for raw in value.split(","):
                mode = _MODE_ALIASES.get(raw.strip().lower())
                if mode is None:
                    raise ConversionError(f"Режим --dpi-desync={raw} не поддерживается конвертером winws2.")
                profile.modes.append(mode)
        elif key == "dpi-desync-repeats":
            profile.repeats = value
        elif key == "dpi-desync-fooling":
            profile.fooling.extend(item.strip().lower() for item in value.split(",") if item.strip())
        elif key == "dpi-desync-ttl":
            profile.ttl = value
        elif key == "dpi-desync-ttl6":
            profile.ttl6 = value
        elif key == "dpi-desync-ts-increment":
            profile.ts_increment = value
        elif key == "dpi-desync-badseq-increment":
            profile.badseq_increment = value
        elif key == "dpi-desync-badack-increment":
            profile.badack_increment = value
        elif key == "ip-id":
            if value not in {"zero", "seq", "rnd"}:
                raise ConversionError(f"--ip-id={value} не поддерживается winws2.")
            profile.ip_id = value
        elif key == "dpi-desync-split-pos":
            profile.split_pos = value
        elif key == "dpi-desync-split-seqovl":
            profile.seqovl = value
        elif key == "dpi-desync-split-seqovl-pattern":
            profile.seqovl_pattern = value
        elif key == "dpi-desync-fakedsplit-pattern":
            profile.fakedsplit_pattern = value
        elif key == "dpi-desync-fakedsplit-mod":
            _read_altorder_mod(value, "fakedsplit", warnings, number)
        elif key == "dpi-desync-hostfakesplit-mod":
            profile.hfs_host = _read_altorder_mod(value, "hostfakesplit", warnings, number)
        elif key == "dpi-desync-hostfakesplit-midhost":
            profile.hfs_midhost = value
        elif key == "dpi-desync-cutoff":
            match = _CUTOFF.match(value.strip().lower())
            if not match:
                raise ConversionError(f"--dpi-desync-cutoff={value} не распознан.")
            profile.cutoff = f"{match.group(1) or 'n'}{match.group(2)}"
        elif key == "dpi-desync-fake-tls":
            profile.tls_fakes.append([value, profile.tls_mod_last])
        elif key == "dpi-desync-fake-tls-mod":
            profile.tls_mod_last = value
            if profile.tls_fakes:
                profile.tls_fakes[-1][1] = value
        elif key == "dpi-desync-fake-syndata":
            profile.syndata_blob = value
        else:
            profile.fakes.setdefault(key, []).append(value)
    if not profile.has_tcp and not profile.has_udp:
        profile.has_tcp = profile.has_udp = True
    return profile


def _read_altorder_mod(value: str, mode: str, warnings: list[str], number: int) -> str | None:
    host: str | None = None
    for item in value.split(","):
        name, _, arg = item.strip().partition("=")
        if name == "host" and arg:
            host = arg
        elif name == "altorder":
            warnings.append(f"Профиль {number}: altorder для {mode} в winws2 отсутствует, порядок по умолчанию.")
        elif name:
            raise ConversionError(f"Модификатор {mode} {name!r} не поддерживается конвертером winws2.")
    return host


def _fooling_args(profile: _Profile, *, tcp: bool) -> list[tuple[str, str | None]]:
    args: list[tuple[str, str | None]] = []
    for item in profile.fooling:
        if item == "badsum":
            args.append(("badsum", None))
        elif not tcp:
            continue
        elif item == "ts":
            args.append(("tcp_ts", profile.ts_increment))
        elif item == "md5sig":
            args.append(("tcp_md5", None))
        elif item == "badseq":
            args.extend((("tcp_seq", profile.badseq_increment), ("tcp_ack", profile.badack_increment)))
            # nfqws1 always wrote the timestamp option first; with an invalid ack
            # Linux servers drop the fake only in that layout.
            args.append(("tcp_ts_up", None))
        elif item == "datanoack":
            args.append(("tcp_flags_unset", "ACK"))
        elif item == "none":
            continue
        else:
            raise ConversionError(f"Fooling {item!r} не поддерживается конвертером winws2.")
    if profile.ttl:
        args.append(("ip_ttl", profile.ttl))
    if profile.ttl6:
        args.append(("ip6_ttl", profile.ttl6))
    return args


def _ip_id_args(profile: _Profile) -> list[tuple[str, str | None]]:
    return [("ip_id", profile.ip_id)] if profile.ip_id else []


def _repeats_args(profile: _Profile) -> list[tuple[str, str | None]]:
    return [("repeats", profile.repeats)] if profile.repeats and profile.repeats != "1" else []


def _fake_instances(
    blobs_with_mods: list[tuple[str, str | None]],
    profile: _Profile,
    *,
    tcp: bool,
    payload: str | None,
) -> list[str]:
    result = []
    for blob, mod in blobs_with_mods:
        args: list[tuple[str, str | None]] = [("blob", blob)]
        if mod:
            args.append(("tls_mod", mod))
        args += _fooling_args(profile, tcp=tcp) + _ip_id_args(profile) + _repeats_args(profile)
        if payload:
            args.append(("payload", payload))
        result.append(_instance("fake", args))
    return result


def _split_instance(profile: _Profile, mode: str, blobs: _Blobs, *, payload: str | None) -> str:
    args: list[tuple[str, str | None]] = []
    if mode == "hostfakesplit":
        if profile.hfs_host:
            args.append(("host", profile.hfs_host))
        if profile.hfs_midhost:
            args.append(("midhost", profile.hfs_midhost))
    else:
        if profile.split_pos:
            positions = [item for item in profile.split_pos.split(",") if item.strip()]
            if mode in {"fakedsplit", "fakeddisorder"} and len(positions) > 1:
                raise ConversionError(f"{mode} в winws2 принимает одну позицию, задано: {profile.split_pos}.")
            args.append(("pos", profile.split_pos))
        if profile.seqovl and profile.seqovl != "0":
            if mode == "multisplit" and not profile.seqovl.lstrip("-").isdigit():
                raise ConversionError(f"seqovl для multisplit должен быть числом: {profile.seqovl}.")
            args.append(("seqovl", profile.seqovl))
            if profile.seqovl_pattern:
                args.append(("seqovl_pattern", blobs.ref(profile.seqovl_pattern)))
        if mode in {"fakedsplit", "fakeddisorder"} and profile.fakedsplit_pattern:
            args.append(("pattern", blobs.ref(profile.fakedsplit_pattern)))
    if mode in _FAKING_SPLITS:
        args += _fooling_args(profile, tcp=True)
    args += _ip_id_args(profile)
    if mode in _FAKING_SPLITS:
        args += _repeats_args(profile)
    if payload:
        args.append(("payload", payload))
    return _instance(_SPLIT_FUNCTIONS[mode], args)


def _tls_fakes(profile: _Profile, blobs: _Blobs) -> list[tuple[str, str | None]]:
    if not profile.tls_fakes:
        mod = profile.tls_mod_last if profile.tls_mod_last is not None else _DEFAULT_TLS_MOD
        return [(DEFAULT_TLS_BLOB, _tls_mod(mod))]
    result = []
    for value, mod in profile.tls_fakes:
        blob = DEFAULT_TLS_BLOB if value.strip() == "!" else blobs.ref(value)
        result.append((blob, _tls_mod(mod)))
    return result


def _tls_mod(mod: str | None) -> str | None:
    if not mod:
        return None
    items = [item.strip() for item in mod.split(",") if item.strip() and item.strip() != "none"]
    return ",".join(items) or None


def _group_fakes(profile: _Profile, group: str, blobs: _Blobs) -> list[tuple[str, str | None]]:
    if group == "tls":
        return _tls_fakes(profile, blobs)
    values = profile.fakes.get(_FAKE_OPTION_BY_GROUP[group], [])
    if values:
        return [(blobs.ref(value), None) for value in values]
    if group == "http":
        return [(DEFAULT_HTTP_BLOB, None)]
    if group == "quic":
        return [(DEFAULT_QUIC_BLOB, None)]
    return [(blobs.zero(ZERO64_BLOB), None)]


def _unknown_fakes(profile: _Profile, blobs: _Blobs, *, tcp: bool) -> list[tuple[str, str | None]]:
    option = "dpi-desync-fake-unknown" if tcp else "dpi-desync-fake-unknown-udp"
    values = profile.fakes.get(option, [])
    if values:
        return [(blobs.ref(value), None) for value in values]
    return [(blobs.zero(ZERO256_BLOB if tcp else ZERO64_BLOB), None)]


def _l7_allows(profile: _Profile, group: str) -> bool:
    return profile.l7 is None or group in profile.l7


def _emit_profile(profile: _Profile, blobs: _Blobs) -> list[str]:
    out = list(profile.filters)
    if not profile.modes:
        return out
    if profile.cutoff:
        out.append(f"--out-range=<{profile.cutoff}")

    modes = set(profile.modes)
    fake = bool(modes & {"fake", "fakeknown"})
    split_modes = [mode for mode in _SPLIT_MODES if mode in modes]
    if len(split_modes) > 1:
        raise ConversionError(f"Несколько режимов разреза в одном профиле: {', '.join(split_modes)}.")
    split = split_modes[0] if split_modes else None
    fake_unknown = fake and "fakeknown" not in modes

    if "syndata" in modes and profile.has_tcp:
        args: list[tuple[str, str | None]] = []
        if profile.syndata_blob:
            args.append(("blob", blobs.ref(profile.syndata_blob)))
        out.append(_instance("syndata", args + _ip_id_args(profile)))

    groups: list[tuple[list[str], list[str]]] = []  # (payloads, instances)

    def add(payload: str, instances: list[str]) -> None:
        for payloads, existing in groups:
            if existing == instances:
                payloads.append(payload)
                return
        groups.append(([payload], instances))

    if profile.has_tcp and (fake or split):
        for group, payload in _TCP_GROUPS:
            if not _l7_allows(profile, group):
                continue
            instances: list[str] = []
            if fake:
                instances += _fake_instances(_group_fakes(profile, group, blobs), profile, tcp=True, payload=None)
            if split:
                instances.append(_split_instance(profile, split, blobs, payload=None))
            add(payload, instances)
    if profile.has_udp and fake:
        for group, payload in _UDP_GROUPS:
            if _l7_allows(profile, group):
                add(payload, _fake_instances(_group_fakes(profile, group, blobs), profile, tcp=False, payload=None))

    for payloads, instances in groups:
        out.append("--payload=" + ",".join(payloads))
        out.extend(instances)

    if profile.any_protocol and _l7_allows(profile, "unknown"):
        tail: list[str] = []
        if profile.has_tcp and (fake_unknown or (split and split != "hostfakesplit")):
            known = ",".join(payload for _, payload in _TCP_GROUPS)
            payload = f"~{known},empty"
            if fake_unknown:
                tail += _fake_instances(_unknown_fakes(profile, blobs, tcp=True), profile, tcp=True, payload=payload)
            if split and split != "hostfakesplit":
                tail.append(_split_instance(profile, split, blobs, payload=payload))
        if profile.has_udp and fake_unknown:
            known = ",".join(payload for _, payload in _UDP_GROUPS)
            tail += _fake_instances(
                _unknown_fakes(profile, blobs, tcp=False), profile, tcp=False, payload=f"~{known},empty"
            )
        if tail:
            # C-level --payload has no negation; the Lua instances filter themselves.
            out.append("--payload=all")
            out.extend(tail)
    return out


def _lua_init(lua_dir: Path) -> list[str]:
    return [f"--lua-init=@{lua_dir / name}" for name in LUA_SCRIPTS]


def convert_winws1_argv(argv: list[str], *, lua_dir: Path) -> Winws2Args:
    """Translate a full winws1 command line (without the executable)."""
    warnings: list[str] = []
    global_options: list[str] = []
    profiles: list[list[tuple[str, str | None]]] = [[]]
    for key, value in _parse(argv):
        if key == "new":
            profiles.append([])
            continue
        if key in _GLOBAL_RENAMES:
            global_options.append(f"--{_GLOBAL_RENAMES[key]}={value}")
        elif key in _GLOBAL_PASSTHROUGH:
            global_options.append(f"--{key}" if value is None else f"--{key}={value}")
        else:
            profiles[-1].append((key, value))

    blobs = _Blobs()
    body: list[str] = []
    for number, options in enumerate(profiles, start=1):
        if number > 1:
            body.append("--new")
        body.extend(_emit_profile(_read_profile(options, warnings, number), blobs))
    return Winws2Args([*global_options, *blobs.options(), *_lua_init(lua_dir), *body], warnings)


TLS_WATCH_FUNCTION = "twowings_tls_watch"
# Inbound replies that mean "the server could not parse our ClientHello":
# a plaintext fatal TLS alert (record 0x15, version 3.x, length 2, level 2) or a
# plain "HTTP/" answer from a non-HTTP port. Only these packets are diverted,
# so watching costs nothing on normal traffic.
TLS_ALERT_FILTER = (
    "inbound and tcp and tcp.PayloadLength >= 5 and ("
    "(tcp.PayloadLength >= 7 and tcp.Payload[0] == 21 and tcp.Payload[1] == 3 "
    "and tcp.Payload[3] == 0 and tcp.Payload[4] == 2 and tcp.Payload[5] == 2)"
    " or (tcp.SrcPort != 80 and tcp.Payload[0] == 72 and tcp.Payload[1] == 84 "
    "and tcp.Payload[2] == 84 and tcp.Payload[3] == 80 and tcp.Payload[4] == 47))"
)
_HOSTLIST_EXCLUDE = ("--hostlist-exclude=", "--hostlist-exclude-domains=")


def _split_profiles(argv: list[str]) -> list[list[str]]:
    profiles: list[list[str]] = [[]]
    for token in argv:
        if token == "--new" or token.startswith("--new="):
            profiles.append([token])
        else:
            profiles[-1].append(token)
    return profiles


def inject_tls_watch(argv: list[str], *, script: Path, writable_dir: Path) -> list[str]:
    """Put twowings_tls_watch first into every profile and divert inbound TLS alerts.

    A profile that cannot exclude by hostname (no --hostlist-exclude, e.g. the
    game filter on ipset) reports the server address instead of the domain.
    """
    result = [
        f"--writable={writable_dir}",
        f"--wf-raw-part={TLS_ALERT_FILTER}",
    ]
    for index, profile in enumerate(_split_profiles(argv)):
        head, body = (profile[:1], profile[1:]) if index else ([], profile)
        by_ip = not any(token.startswith(_HOSTLIST_EXCLUDE) for token in body)
        watch = f"--lua-desync={TLS_WATCH_FUNCTION}" + (":exclude=ip" if by_ip else "")
        result += [*head, "--out-range=x", "--in-range=a", watch, "--in-range=x", "--out-range=a", *body]
    last_init = max((i for i, token in enumerate(result) if token.startswith("--lua-init=")), default=-1)
    result.insert(last_init + 1, f"--lua-init=@{script}")
    return result


def to_winws2_argv(argv: list[str], *, lua_dir: Path) -> Winws2Args:
    """Return winws2 arguments: native ones get the Lua library, winws1 ones are converted."""
    if not is_winws2_argv(argv):
        return convert_winws1_argv(argv, lua_dir=lua_dir)
    legacy = sorted({_split(token)[0] for token in argv if token.startswith("--dpi-desync")})
    if legacy:
        raise ConversionError(f"Смешаны опции winws1 и winws2: {', '.join('--' + key for key in legacy)}.")
    loaded = {Path(_split(token)[1] or "").name.lower() for token in argv if token.startswith("--lua-init=@")}
    missing = [f"--lua-init=@{lua_dir / name}" for name in LUA_SCRIPTS if name not in loaded]
    return Winws2Args([*missing, *argv])
