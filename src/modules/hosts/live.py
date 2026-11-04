"""Ask DNS profiles for their current answers instead of trusting the catalog snapshot.

The catalog is a snapshot: relay addresses change and some die (a Comss relay
written for Gemini stopped answering while another profile already proxied it).
For profiles that publish a DoH endpoint Tigo resolves every domain at apply
time and keeps only *relay* answers — those that differ from what a neutral
resolver returns; a domain the profile does not proxy is left to normal DNS.
Every address that goes into hosts must accept a TCP connection on 443.
"""

from __future__ import annotations

import ipaddress
import random
import socket
import struct
from concurrent.futures import ThreadPoolExecutor

import httpx

from src.core.debug_log import debug

PROFILE_DOH = {
    "comss_dns": "https://dns.comss.one/dns-query",
    "xbox_dns": "https://xbox-dns.ru/dns-query",
}
REFERENCE_DOH = "https://dns.google/dns-query"
TYPE_A = 1
TYPE_AAAA = 28
WORKERS = 16
PROBE_TIMEOUT = 3.0


class LiveResolveError(RuntimeError):
    pass


def build_query(name: str, qtype: int) -> bytes:
    header = struct.pack(">HHHHHH", random.randint(0, 0xFFFF), 0x0100, 1, 0, 0, 0)
    labels = b"".join(bytes([len(part)]) + part.encode("ascii") for part in name.strip(".").split("."))
    return header + labels + b"\0" + struct.pack(">HH", qtype, 1)


def _skip_name(data: bytes, offset: int) -> int:
    while True:
        length = data[offset]
        if length & 0xC0 == 0xC0:
            return offset + 2
        if length == 0:
            return offset + 1
        offset += length + 1


def parse_answers(data: bytes, qtype: int) -> list[str]:
    """Addresses of type ``qtype`` in a DNS response (CNAME chains are skipped)."""
    if len(data) < 12:
        return []
    questions, answers = struct.unpack(">HH", data[4:8])
    offset = 12
    for _ in range(questions):
        offset = _skip_name(data, offset) + 4
    result: list[str] = []
    for _ in range(answers):
        offset = _skip_name(data, offset)
        rtype, _rclass, _ttl, length = struct.unpack(">HHIH", data[offset : offset + 10])
        offset += 10
        rdata = data[offset : offset + length]
        offset += length
        if rtype == qtype == TYPE_A and length == 4:
            result.append(socket.inet_ntop(socket.AF_INET, rdata))
        elif rtype == qtype == TYPE_AAAA and length == 16:
            result.append(socket.inet_ntop(socket.AF_INET6, rdata))
    return result


def _resolve(client: httpx.Client, url: str, name: str, qtype: int) -> list[str] | None:
    """Answers, or None when the server could not be asked."""
    try:
        response = client.post(
            url,
            content=build_query(name, qtype),
            headers={"content-type": "application/dns-message", "accept": "application/dns-message"},
        )
        response.raise_for_status()
    except (httpx.HTTPError, UnicodeError) as exc:
        debug("hosts", f"DoH {url} {name}: {exc}")
        return None
    return parse_answers(response.content, qtype)


def relay_rows(
    domains: list[str], profile_id: str, *, ipv6: bool, known_relays: set[str] = frozenset()
) -> list[tuple[str, str]]:
    """``(address, hostname)`` for the domains this profile proxies right now.

    A relay serves many names from one address, while a CDN hands out a
    different address per name. So a candidate counts only if it is a known relay
    of this profile (from the catalog) or answers for at least two names here —
    a lone real Google address from another /16 is not taken for a proxy.
    """
    url = PROFILE_DOH[profile_id]
    qtypes = [TYPE_A, TYPE_AAAA] if ipv6 else [TYPE_A]
    jobs = [(domain, qtype) for domain in dict.fromkeys(domains) for qtype in qtypes]
    limits = httpx.Limits(max_connections=WORKERS * 2, max_keepalive_connections=WORKERS * 2)
    with httpx.Client(timeout=httpx.Timeout(10.0, connect=5.0), limits=limits, headers={"User-Agent": "Tigo"}) as client:

        def ask(job: tuple[str, int]) -> tuple[list[str] | None, list[str] | None]:
            domain, qtype = job
            return _resolve(client, url, domain, qtype), _resolve(client, REFERENCE_DOH, domain, qtype)

        with ThreadPoolExecutor(WORKERS) as pool:
            answers = list(pool.map(ask, jobs))
    if jobs and all(profile is None for profile, _ in answers):
        raise LiveResolveError(f"DNS-сервер {url} не отвечает")
    # A CDN answers from many networks depending on the name and the resolver, so an
    # address counts as real if the neutral resolver gave its network for any name here.
    neutral = [address for _profile, reference in answers for address in reference or []]
    candidates: list[tuple[str, str]] = []
    for (domain, _qtype), (profile, _reference) in zip(jobs, answers):
        for address in profile or []:
            if is_relay(address, neutral):
                candidates.append((address, domain))
                break  # hosts uses one line per name and family
    shared = {address for address, _ in candidates if sum(1 for other, _ in candidates if other == address) >= 2}
    return [(address, domain) for address, domain in candidates if address in shared or address in known_relays]


def is_relay(address: str, neutral: list[str]) -> bool:
    """A relay answer points outside every network the neutral resolver answers with.

    Different resolvers hand out different addresses of the same CDN (a profile
    and Google DNS give other 142.251.x.x for www.google.com), so only a foreign
    network (/16 for IPv4, /48 for IPv6) means the profile proxies the domain.
    """
    try:
        parsed = ipaddress.ip_address(address)
    except ValueError:
        return False
    if not parsed.is_global:
        return False
    prefix = 16 if parsed.version == 4 else 48
    network = ipaddress.ip_network(f"{parsed}/{prefix}", strict=False)
    for other in neutral:
        try:
            if ipaddress.ip_address(other) in network:
                return False
        except ValueError:
            continue
    return True


def reachable(addresses: set[str], port: int = 443) -> set[str]:
    """Addresses that accept a TCP connection; a dead relay must not reach hosts."""

    def probe(address: str) -> str | None:
        try:
            with socket.create_connection((address, port), timeout=PROBE_TIMEOUT):
                return address
        except OSError:
            return None

    if not addresses:
        return set()
    with ThreadPoolExecutor(WORKERS) as pool:
        return {address for address in pool.map(probe, sorted(addresses)) if address}
