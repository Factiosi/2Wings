"""Daemon: take adapters and hosts off the DNS service 2Wings no longer offers.

Zapret DNS closed plain DNS: an adapter left on its address has no working DNS at
all, and its hosts lines lead to a relay 2Wings no longer manages. The addresses
stay here only to recognise what earlier versions wrote.
"""

from __future__ import annotations

from src.core.debug_log import info, warn
from src.core.settings import reload_settings
from src.modules.dns.core import DNSManager
from src.modules.hosts.service import apply_services, hosts_uses_addresses

RETIRED_SERVERS = frozenset({"83.217.211.149", "38.180.241.191", "2a03:afc0:9::235d"})
RETIRED_RELAYS = RETIRED_SERVERS | {"5.129.221.64"}
FAMILIES = ("IPv4", "IPv6")


def clean_adapters(manager: DNSManager) -> list[str]:
    """Drop retired servers, keep the user's others; no servers left means automatic DNS."""
    changed: list[str] = []
    for name, _description in manager.get_network_adapters_fast(include_ignored=False, include_disconnected=True):
        for family in FAMILIES:
            current = manager.get_current_dns(name, family)
            kept = [server for server in current if server.lower() not in RETIRED_SERVERS]
            if len(kept) == len(current):
                continue
            if kept:
                ok, message = manager.set_custom_dns(name, kept[0], kept[1] if len(kept) > 1 else None, family)
            else:
                ok, message = manager.set_auto_dns(name, family)
            if ok:
                changed.append(name)
            else:
                warn("dns", f"{name}: не удалось убрать прежний DNS ({family}): {message}")
    return changed


def clean_retired_dns() -> None:
    manager = DNSManager()
    changed = clean_adapters(manager)
    if changed:
        manager.flush_dns_cache()
        info("dns", f"Убран прежний DNS с адаптеров: {', '.join(dict.fromkeys(changed))}")
    if hosts_uses_addresses(RETIRED_RELAYS):
        ok, message = apply_services(reload_settings().hosts_services)
        (info if ok else warn)("hosts", message)
