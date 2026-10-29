"""HTTP/ping probes for strategy testing (standard mode)."""

from __future__ import annotations

import concurrent.futures
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

CREATE_NO_WINDOW = 0x08000000
CURL_TIMEOUT = 5
MAX_PARALLEL = 8
PING_COUNT = 3
NAME_COL_MIN = 10
_PING_MS = re.compile(r"(\d+)\s*(?:ms|мс)", re.I)
_PING_AVG = re.compile(r"(?:Average|Среднее)\s*=\s*(\d+)", re.I)

_TARGET_LINE = re.compile(r'^\s*(\w+)\s*=\s*"(.+)"\s*$')


@dataclass(frozen=True)
class ProbeTarget:
    name: str
    url: str | None
    ping_host: str | None


@dataclass(frozen=True)
class TargetProbeResult:
    name: str
    http_tokens: tuple[str, ...]
    ping: str


def load_targets(path: Path | None = None) -> list[ProbeTarget]:
    if path is None:
        return _default_targets()
    targets_file = path
    if not targets_file.exists():
        return _default_targets()

    targets: list[ProbeTarget] = []
    for raw in targets_file.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = _TARGET_LINE.match(line)
        if not match:
            continue
        name, value = match.group(1), match.group(2)
        if value.upper().startswith("PING:"):
            targets.append(ProbeTarget(name, None, value.split(":", 1)[1].strip()))
        else:
            targets.append(ProbeTarget(name, value, None))
    return targets or _default_targets()


def _default_targets() -> list[ProbeTarget]:
    return [
        ProbeTarget("DiscordMain", "https://discord.com", None),
        ProbeTarget("DiscordGateway", "https://gateway.discord.gg", None),
        ProbeTarget("DiscordCDN", "https://cdn.discordapp.com", None),
        ProbeTarget("DiscordUpdates", "https://updates.discord.com", None),
        ProbeTarget("YouTubeWeb", "https://www.youtube.com", None),
        ProbeTarget("YouTubeShort", "https://youtu.be", None),
        ProbeTarget("YouTubeImage", "https://i.ytimg.com", None),
        ProbeTarget("YouTubeVideoRedirect", "https://redirector.googlevideo.com", None),
        ProbeTarget("GoogleMain", "https://www.google.com", None),
        ProbeTarget("GoogleGstatic", "https://www.gstatic.com", None),
        ProbeTarget("CloudflareWeb", "https://www.cloudflare.com", None),
        ProbeTarget("CloudflareCDN", "https://cdnjs.cloudflare.com", None),
        ProbeTarget("CloudflareDNS1111", None, "1.1.1.1"),
        ProbeTarget("CloudflareDNS1001", None, "1.0.0.1"),
        ProbeTarget("GoogleDNS8888", None, "8.8.8.8"),
        ProbeTarget("GoogleDNS8844", None, "8.8.4.4"),
        ProbeTarget("Quad9DNS9999", None, "9.9.9.9"),
    ]


def _run_curl(url: str, extra: list[str]) -> str:
    args = [
        "curl.exe",
        "-I",
        "-s",
        "-m",
        str(CURL_TIMEOUT),
        "-o",
        "NUL",
        "-w",
        "%{http_code}",
        "--show-error",
        *extra,
        url,
    ]
    result = subprocess.run(
        args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=CREATE_NO_WINDOW,
    )
    stderr = result.stderr or ""
    output = (result.stdout or "").strip()

    if re.search(
        r"Could not resolve host|certificate|SSL certificate problem|self[- ]?signed|"
        r"certificate verify failed|unable to get local issuer certificate",
        stderr,
        re.I,
    ):
        return "SSL"
    if result.returncode == 35 or re.search(
        r"not supported|unsupported protocol|Unrecognized option|Unknown option",
        stderr,
        re.I,
    ):
        return "UNSUP"
    if result.returncode == 0:
        return "OK"
    return "ERROR"


def _probe_ping(host: str) -> str:
    result = subprocess.run(
        ["ping", "-n", str(PING_COUNT), "-w", "1000", host],
        capture_output=True,
        text=True,
        encoding="cp866",
        errors="replace",
        creationflags=CREATE_NO_WINDOW,
    )
    stdout = result.stdout or ""
    avg_match = _PING_AVG.search(stdout)
    if avg_match:
        return f"{avg_match.group(1)} ms"
    times = [int(match.group(1)) for match in _PING_MS.finditer(stdout)]
    if times:
        return f"{round(sum(times) / len(times))} ms"
    if result.returncode != 0:
        return "Timeout"
    return "n/a"


def _probe_url(target: ProbeTarget) -> TargetProbeResult:
    assert target.url
    tokens: list[str] = []
    for label, extra in (
        ("HTTP", ["--http1.1"]),
        ("TLS1.2", ["--tlsv1.2", "--tls-max", "1.2"]),
        ("TLS1.3", ["--tlsv1.3", "--tls-max", "1.3"]),
    ):
        status = _run_curl(target.url, extra)
        if status == "OK":
            tokens.append(f"{label}:OK")
        elif status == "UNSUP":
            tokens.append(f"{label}:UNSUP")
        elif status == "SSL":
            tokens.append(f"{label}:SSL")
        else:
            tokens.append(f"{label}:ERROR")

    host = target.url.replace("https://", "").replace("http://", "").split("/")[0]
    ping = _probe_ping(host)
    return TargetProbeResult(target.name, tuple(tokens), ping)


def _probe_target(target: ProbeTarget) -> TargetProbeResult:
    if target.url:
        return _probe_url(target)
    ping = _probe_ping(target.ping_host or "")
    return TargetProbeResult(target.name, (), ping)


def probe_all_targets(*, targets: list[ProbeTarget] | None = None) -> list[TargetProbeResult]:
    items = targets or load_targets()
    if not items:
        return []
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_PARALLEL) as pool:
        return list(pool.map(_probe_target, items))


def probe_all_targets_with_callback(
    on_target,
    *,
    targets: list[ProbeTarget] | None = None,
) -> list[TargetProbeResult]:
    items = targets or load_targets()
    if not items:
        return []
    order = {item.name: index for index, item in enumerate(items)}
    collected: list[TargetProbeResult] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_PARALLEL) as pool:
        futures = {pool.submit(_probe_target, item): item for item in items}
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            on_target(result)
            collected.append(result)
    collected.sort(key=lambda row: order.get(row.name, 999))
    return collected


# TLS 1.3 is shown but not scored: curl on Windows 10 (Schannel) cannot do it, and
# sites still accept TLS 1.2, so a strategy that passes everything else works fully.
UNSCORED_LABELS = ("TLS1.3:",)


def score_results(results: list[TargetProbeResult]) -> tuple[int, int]:
    passed = 0
    total = 0
    for item in results:
        if item.http_tokens:
            for token in item.http_tokens:
                if token.startswith(UNSCORED_LABELS):
                    continue
                total += 1
                if token.endswith(":OK"):
                    passed += 1
        elif item.ping and item.ping not in {"Timeout", "n/a"}:
            total += 1
            passed += 1
    return passed, total


def _format_http_token(token: str) -> str:
    if token.endswith(":OK"):
        return f"{token}   "
    if token.endswith(":SSL"):
        return f"{token}  "
    return token


def format_probe_line(result: TargetProbeResult, *, name_width: int = NAME_COL_MIN) -> str:
    name = result.name.ljust(name_width)
    if result.http_tokens:
        token_text = "".join(f" {_format_http_token(token)}" for token in result.http_tokens)
        return f"{name}   {token_text} | Ping: {result.ping}"
    return f"{name}   Ping: {result.ping}"


def format_probe_lines(results: list[TargetProbeResult]) -> list[str]:
    name_width = max([len(item.name) for item in results] + [NAME_COL_MIN])
    return [format_probe_line(item, name_width=name_width) for item in results]


def placeholder_results() -> list[TargetProbeResult]:
    """Probe rows with ``?`` placeholders for every configured target."""
    rows: list[TargetProbeResult] = []
    for target in load_targets():
        if target.url:
            rows.append(
                TargetProbeResult(
                    target.name,
                    ("HTTP:?", "TLS1.2:?", "TLS1.3:?"),
                    "? ms",
                )
            )
        else:
            rows.append(TargetProbeResult(target.name, (), "? ms"))
    return rows
