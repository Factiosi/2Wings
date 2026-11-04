"""Catalog of services that hosts entries open: which domains, which addresses.

The catalog is the SQLite file zapretgui ships (schema 1). Two kinds of
services live there:

* ``dns`` — every domain has answers per DNS profile (XBOX DNS, Comss DNS…):
  the address that profile's server gives from abroad;
* ``hosts`` — fixed ``address host`` pairs (Discord, YouTube, GitHub…).

Tigo ships a snapshot in ``assets/hosts`` and keeps a fresher copy in the cache
(``catalog_update.py``). Reading is read-only; the file is never modified.
"""

from __future__ import annotations

import ipaddress
import socket
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

from src.core.paths import cache_dir, program_root

SCHEMA_VERSION = "1"
CATALOG_NAME = "hosts_catalog.sqlite3"
DIRECT_PROFILE = "hosts"
# Listed by zapretgui, not offered by Tigo: this server answers over DoH only.
HIDDEN_PROFILES = ("zapret_dns",)
CATEGORY_TITLES = {"ai": "Нейросети", "other": "Сервисы", "direct": "Прямые записи"}


class CatalogError(RuntimeError):
    pass


@dataclass(frozen=True)
class Service:
    id: str
    name: str
    category: str  # ai | other | direct
    kind: str  # dns | hosts
    domains: int
    profiles: tuple[str, ...]  # DNS profiles with at least one answer


@dataclass(frozen=True)
class Catalog:
    path: Path
    version: str
    profiles: tuple[tuple[str, str], ...]  # (profile_id, name) in display order
    services: tuple[Service, ...]

    def service(self, service_id: str) -> Service | None:
        return next((item for item in self.services if item.id == service_id), None)


def bundled_catalog_path() -> Path:
    return program_root() / "assets" / "hosts" / CATALOG_NAME


def cached_catalog_path() -> Path:
    return cache_dir() / CATALOG_NAME


def _connect(path: Path) -> sqlite3.Connection:
    try:
        connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=5.0)
    except (OSError, sqlite3.Error) as exc:
        raise CatalogError(f"каталог не открывается: {exc}") from exc
    return connection


def catalog_version(path: Path) -> str:
    """Version of a catalog file, or raise CatalogError when it is not a usable one."""
    if not path.exists():
        raise CatalogError("каталога нет")
    with closing(_connect(path)) as connection:
        try:
            meta = dict(connection.execute("SELECT key, value FROM catalog_meta"))
        except sqlite3.Error as exc:
            raise CatalogError(f"каталог повреждён: {exc}") from exc
    if meta.get("schema_version") != SCHEMA_VERSION:
        raise CatalogError(f"схема каталога {meta.get('schema_version')!r} не поддерживается")
    return str(meta.get("catalog_version") or "")


def active_catalog_path() -> Path:
    """The newer of the cached and the bundled catalog that opens."""
    best: tuple[str, Path] | None = None
    for path in (cached_catalog_path(), bundled_catalog_path()):
        try:
            version = catalog_version(path)
        except CatalogError:
            continue
        if best is None or version > best[0]:
            best = (version, path)
    if best is None:
        raise CatalogError("каталог сервисов не найден")
    return best[1]


def load_catalog(path: Path | None = None) -> Catalog:
    path = path or active_catalog_path()
    version = catalog_version(path)
    with closing(_connect(path)) as connection:
        profiles = tuple(
            (str(pid), str(name))
            for pid, name in connection.execute(
                "SELECT profile_id, name FROM dns_profiles WHERE enabled = 1 ORDER BY sort_order, name"
            )
            if pid not in HIDDEN_PROFILES
        )
        answered: dict[str, set[str]] = {}
        for service_id, profile_id in connection.execute(
            "SELECT DISTINCT d.service_id, a.profile_id FROM dns_answers a JOIN domains d USING(domain_id)"
        ):
            answered.setdefault(service_id, set()).add(profile_id)
        services = []
        for service_id, name, category, kind in connection.execute(
            "SELECT service_id, name, category, kind FROM services WHERE enabled = 1 ORDER BY sort_order, name"
        ):
            if kind == "dns":
                count = connection.execute("SELECT COUNT(*) FROM domains WHERE service_id = ?", (service_id,)).fetchone()[0]
                own = answered.get(service_id, set())
                service_profiles = tuple(pid for pid, _ in profiles if pid in own)
                if not service_profiles:
                    continue
            else:
                count = connection.execute(
                    "SELECT COUNT(DISTINCT hostname) FROM hosts_entries WHERE service_id = ?", (service_id,)
                ).fetchone()[0]
                service_profiles = (DIRECT_PROFILE,)
            services.append(Service(service_id, name, category, kind, int(count), service_profiles))
    return Catalog(path=path, version=version, profiles=profiles, services=tuple(services))


def has_ipv6_route() -> bool:
    """True when a global IPv6 destination is routable (UDP connect sends nothing)."""
    try:
        with socket.socket(socket.AF_INET6, socket.SOCK_DGRAM) as sock:
            sock.connect(("2001:4860:4860::8888", 53))
            return ipaddress.ip_address(sock.getsockname()[0].split("%")[0]).is_global
    except (OSError, ValueError):
        return False


def _usable(address: str, *, ipv6: bool) -> bool:
    try:
        parsed = ipaddress.ip_address(address)
    except ValueError:
        return False
    if parsed.version == 6 and not ipv6:
        return False
    return parsed.is_global


def _best_per_host(rows, *, ipv6: bool) -> list[tuple[str, str]]:
    """rows: (hostname, address, priority); keep the best address per host and family."""
    best: dict[tuple[str, int], tuple[int, str]] = {}
    order: list[tuple[str, int]] = []
    for hostname, address, priority in rows:
        if not _usable(address, ipv6=ipv6):
            continue
        key = (str(hostname).lower(), ipaddress.ip_address(address).version)
        if key not in best:
            order.append(key)
        if key not in best or int(priority) < best[key][0]:
            best[key] = (int(priority), address)
    return [(best[key][1], key[0]) for key in order]


def profile_relays(catalog: Catalog, profile_id: str, *, min_names: int = 3) -> set[str]:
    """Addresses a profile answered with for many names in the snapshot — its relays."""
    with closing(_connect(catalog.path)) as connection:
        return {
            str(address)
            for address, count in connection.execute(
                "SELECT ip_address, COUNT(DISTINCT domain_id) FROM dns_answers WHERE profile_id = ? GROUP BY ip_address",
                (profile_id,),
            )
            if count >= min_names and _usable(str(address), ipv6=True)
        }


def service_domains(catalog: Catalog, service_id: str) -> list[str]:
    """Domains of a DNS service, in catalog order."""
    with closing(_connect(catalog.path)) as connection:
        return [
            str(hostname).lower()
            for (hostname,) in connection.execute(
                "SELECT hostname FROM domains WHERE service_id = ? ORDER BY sort_order, domain_id", (service_id,)
            )
        ]


def service_rows(catalog: Catalog, service_id: str, profile_id: str, *, ipv6: bool) -> list[tuple[str, str]]:
    """``(address, hostname)`` lines for one service from the catalog snapshot.

    Only the chosen profile's answers count: borrowing another profile's relay
    once wrote a dead relay of one profile for Gemini while another was chosen.
    Profiles with a DoH endpoint are asked live instead (``live.relay_rows``).
    """
    service = catalog.service(service_id)
    if service is None:
        return []
    with closing(_connect(catalog.path)) as connection:
        if service.kind != "dns":
            rows = connection.execute(
                "SELECT hostname, ip_address, priority FROM hosts_entries WHERE service_id = ? ORDER BY entry_id",
                (service_id,),
            ).fetchall()
        else:
            rows = connection.execute(
                "SELECT d.hostname, a.ip_address, a.priority FROM domains d JOIN dns_answers a USING(domain_id) "
                "WHERE d.service_id = ? AND a.profile_id = ? ORDER BY d.sort_order, d.domain_id",
                (service_id, profile_id),
            ).fetchall()
    return _best_per_host(rows, ipv6=ipv6)
