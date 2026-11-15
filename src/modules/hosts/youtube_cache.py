"""Close dead YouTube cache servers in hosts so the player picks a working one.

Video comes from Google cache servers inside the provider's network
(``rrN---sn-<node>.googlevideo.com``). Some of them stop answering while the
rest work, and a video then loads or not depending on the server it got. This
is not DPI, so no strategy helps and strategy tests stay green: they never
touch these servers.

The check takes the servers YouTube hands out right now from a few watch pages,
adds the ones already closed (they may have come back), resolves every name
through Google DNS (hosts already points closed ones at 0.0.0.0) and asks each
for ``/generate_204`` over TLS a few times. A server that never answers goes to
the ``youtube-cache`` block; one that answers again leaves it.
"""

from __future__ import annotations

import json
import re
import socket
import ssl
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import datetime

import httpx

from src.core.debug_log import debug
from src.core.paths import cache_dir
from src.modules.hosts.hosts_file import read_hosts, set_block
from src.modules.hosts.live import REFERENCE_DOH, TYPE_A, _resolve
from src.modules.hosts.presets import BLOCKED_IP

BLOCK_ID = "youtube-cache"
CHECK_INTERVAL = 60 * 60
RETRY_INTERVAL = 10 * 60
# Popular, long-lived videos: their pages list the cache servers assigned to this network.
SAMPLE_VIDEOS = ("jNQXAC9IVRw", "dQw4w9WgXcQ", "9bZkp7q19f0", "kJQP7kiw5Fk")
SERVERS_PER_NODE = 16
ATTEMPTS = 3
PROBE_TIMEOUT = 5.0
WORKERS = 16
_SERVER = re.compile(r"rr(\d+)---(sn-[a-z0-9-]+)\.googlevideo\.com")
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
)


@dataclass
class Server:
    host: str
    ip: str
    alive: bool


@dataclass
class CheckResult:
    checked_at: str = ""
    servers: list[Server] = field(default_factory=list)
    error: str = ""

    @property
    def dead(self) -> list[Server]:
        return [server for server in self.servers if not server.alive]


def state_path():
    return cache_dir() / "youtube_cache.json"


def load_result() -> CheckResult:
    try:
        data = json.loads(state_path().read_text(encoding="utf-8"))
        return CheckResult(
            checked_at=str(data.get("checked_at", "")),
            servers=[Server(**item) for item in data.get("servers", [])],
            error=str(data.get("error", "")),
        )
    except (OSError, ValueError, TypeError):
        return CheckResult()


def save_result(result: CheckResult) -> None:
    path = state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(result), ensure_ascii=False, indent=2), encoding="utf-8")


def check_due() -> bool:
    """An hour after a check; ten minutes after a failed one (the bypass may not have been up)."""
    last = load_result()
    interval = RETRY_INTERVAL if last.error else CHECK_INTERVAL
    try:
        return time.time() - datetime.fromisoformat(last.checked_at).timestamp() >= interval
    except ValueError:
        return True


def nodes_in(text: str) -> set[str]:
    return {match.group(2) for match in _SERVER.finditer(text)}


def discover_nodes(client: httpx.Client) -> set[str]:
    """Cache nodes YouTube assigns to this network, from a few watch pages."""
    nodes: set[str] = set()
    for video in SAMPLE_VIDEOS:
        try:
            response = client.get(f"https://www.youtube.com/watch?v={video}")
            nodes |= nodes_in(response.text.replace("\\u0026", "&"))
        except httpx.HTTPError as exc:
            debug("hosts", f"youtube page {video}: {exc}")
    return nodes


def probe(host: str, ip: str) -> bool:
    """True when the server answers ``/generate_204`` at least once."""
    context = ssl.create_default_context()
    request = f"GET /generate_204 HTTP/1.1\r\nHost: {host}\r\nUser-Agent: {_USER_AGENT}\r\nConnection: close\r\n\r\n"
    for _ in range(ATTEMPTS):
        try:
            with socket.create_connection((ip, 443), timeout=PROBE_TIMEOUT) as raw:
                with context.wrap_socket(raw, server_hostname=host) as tls:
                    tls.sendall(request.encode("ascii"))
                    status = tls.recv(64).split(b"\r\n", 1)[0]
            if status.startswith(b"HTTP/") and len(status.split()) > 1:
                return True
        except OSError:
            continue
    return False


def check_servers(extra_hosts: set[str] = frozenset()) -> CheckResult:
    """Probe every server of the current nodes and of the hosts already closed."""
    now = datetime.now().isoformat(timespec="seconds")
    headers = {"User-Agent": _USER_AGENT, "Accept-Language": "ru"}
    with httpx.Client(timeout=httpx.Timeout(15.0, connect=8.0), headers=headers, follow_redirects=True) as client:
        nodes = discover_nodes(client)
        nodes |= {node for host in extra_hosts for node in nodes_in(host)}
        if not nodes:
            return CheckResult(now, [], "YouTube не ответил: не удалось узнать серверы")
        names = [f"rr{index}---{node}.googlevideo.com" for node in sorted(nodes) for index in range(1, SERVERS_PER_NODE + 1)]

        def resolve(name: str) -> tuple[str, str | None]:
            answers = _resolve(client, REFERENCE_DOH, name, TYPE_A)
            return name, answers[0] if answers else None

        with ThreadPoolExecutor(WORKERS) as pool:
            resolved = [(name, ip) for name, ip in pool.map(resolve, names) if ip]
    if not resolved:
        return CheckResult(now, [], "Google DNS не ответил: серверы не проверены")
    with ThreadPoolExecutor(WORKERS) as pool:
        alive = list(pool.map(lambda item: probe(*item), resolved))
    servers = [Server(name, ip, ok) for (name, ip), ok in zip(resolved, alive)]
    return CheckResult(now, servers)


def blocked_hosts(text: str | None = None) -> set[str]:
    """Hosts in our block right now."""
    text = read_hosts() if text is None else text
    hosts: set[str] = set()
    inside = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped == f"# >>> twowings:{BLOCK_ID} >>>":
            inside = True
        elif stripped == f"# <<< twowings:{BLOCK_ID} <<<":
            inside = False
        elif inside:
            parts = stripped.split("#", 1)[0].split()
            if len(parts) >= 2:
                hosts.add(parts[1].lower())
    return hosts


def block_text(text: str, result: CheckResult) -> str:
    """hosts text with the dead servers closed and the recovered ones opened.

    Nothing changes when the check failed or no server answered at all: then the
    network is down, not the servers.
    """
    if result.error or not any(server.alive for server in result.servers):
        return text
    rows = [(BLOCKED_IP, server.host) for server in sorted(result.dead, key=lambda s: s.host)]
    return set_block(text, BLOCK_ID, rows)

