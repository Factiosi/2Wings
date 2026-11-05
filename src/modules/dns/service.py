"""DNS module public API."""

from __future__ import annotations

from dataclasses import dataclass

from src.core.debug_log import debug, warn
from src.modules.dns.core import DNSManager
from src.modules.dns.providers import DNS_PROVIDERS

ALL_ADAPTERS_KEY = "__all__"


@dataclass
class DnsAdapterInfo:
    name: str
    ipv4: list[str]
    ipv6: list[str]
    dhcp: bool


@dataclass
class DnsPageState:
    adapters: list[str]
    adapter_labels: dict[str, str]
    selected_adapter: str
    adapter_info: DnsAdapterInfo | None
    all_adapters_info: list[DnsAdapterInfo]
    ipv6_available: bool


_manager: DNSManager | None = None


def _get_manager() -> DNSManager:
    global _manager
    if _manager is None:
        _manager = DNSManager()
    return _manager


def flatten_providers() -> list[tuple[str, str, str, list[str], list[str]]]:
    """Return (group, name, desc, ipv4, ipv6) for dropdown."""
    result: list[tuple[str, str, str, list[str], list[str]]] = []
    for group, providers in DNS_PROVIDERS.items():
        for name, data in providers.items():
            result.append(
                (
                    group,
                    name,
                    str(data.get("desc") or group),
                    list(data.get("ipv4") or []),
                    list(data.get("ipv6") or []),
                )
            )
    return result


def _adapter_info_from_raw(name: str, dns_info: dict[str, list[str]]) -> DnsAdapterInfo:
    ipv4 = list(dns_info.get("IPv4") or dns_info.get("ipv4") or [])
    ipv6 = list(dns_info.get("IPv6") or dns_info.get("ipv6") or [])
    return DnsAdapterInfo(
        name=name,
        ipv4=ipv4,
        ipv6=ipv6,
        dhcp=not ipv4 and not ipv6,
    )


def format_adapter_dns(info: DnsAdapterInfo) -> str:
    if info.dhcp:
        return "авто (DHCP)"
    parts: list[str] = []
    if info.ipv4:
        parts.append(", ".join(info.ipv4))
    if info.ipv6:
        parts.append(f"IPv6: {', '.join(info.ipv6)}")
    return " · ".join(parts) if parts else "не задан"


def format_status_lines(state: DnsPageState) -> list[str]:
    if state.selected_adapter == ALL_ADAPTERS_KEY:
        if not state.all_adapters_info:
            return ["Текущий DNS: нет адаптеров"]
        lines = ["Текущий DNS:"]
        lines.extend(f"{info.name} — {format_adapter_dns(info)}" for info in state.all_adapters_info)
        return lines
    if state.adapter_info:
        return [f"Текущий DNS ({state.adapter_info.name}): {format_adapter_dns(state.adapter_info)}"]
    return ["Текущий DNS: адаптер не выбран"]


def resolve_apply_adapters(selected: str, adapter_names: list[str]) -> list[str]:
    physical = [name for name in adapter_names if name != ALL_ADAPTERS_KEY]
    if selected == ALL_ADAPTERS_KEY:
        return physical
    if selected in physical:
        return [selected]
    return physical[:1]


def load_state(selected_adapter: str | None = None) -> DnsPageState:
    mgr = _get_manager()
    raw_adapters = mgr.get_network_adapters_fast(include_ignored=False, include_disconnected=True)
    physical_names = [name for name, _desc in raw_adapters]
    adapter_labels = {name: name for name in physical_names}
    adapters = [ALL_ADAPTERS_KEY, *physical_names]

    pick = selected_adapter if selected_adapter in adapters else (physical_names[0] if physical_names else ALL_ADAPTERS_KEY)

    all_info: list[DnsAdapterInfo] = []
    if physical_names:
        dns_map = mgr.get_all_dns_info_fast(physical_names)
        for name in physical_names:
            all_info.append(_adapter_info_from_raw(name, dns_map.get(name, {})))

    info: DnsAdapterInfo | None = None
    if pick == ALL_ADAPTERS_KEY:
        info = None
    elif pick in physical_names:
        dns_info = mgr.get_all_dns_info_fast([pick]).get(pick, {})
        info = _adapter_info_from_raw(pick, dns_info)

    ipv6_available = False
    try:
        import socket

        sock = socket.socket(socket.AF_INET6, socket.SOCK_DGRAM)
        sock.close()
        ipv6_available = True
    except OSError:
        ipv6_available = False

    return DnsPageState(
        adapters=adapters,
        adapter_labels=adapter_labels,
        selected_adapter=pick,
        adapter_info=info,
        all_adapters_info=all_info,
        ipv6_available=ipv6_available,
    )


def apply_auto(adapters: list[str]) -> tuple[bool, str]:
    mgr = _get_manager()
    ok_count = 0
    errors: list[str] = []
    for adapter in adapters:
        ok_v4, msg_v4 = mgr.set_auto_dns(adapter, "IPv4")
        ok_v6, msg_v6 = mgr.set_auto_dns(adapter, "IPv6")
        if ok_v4 and ok_v6:
            ok_count += 1
        else:
            errors.append(f"{adapter}: {msg_v4 or msg_v6}")
    mgr.flush_dns_cache()
    debug("dns", f"apply_auto adapters={adapters} ok={ok_count}")
    if not adapters:
        return False, "Нет сетевых адаптеров."
    if ok_count == 0:
        detail = errors[0] if errors else "Запустите от администратора."
        warn("dns", f"apply_auto failed: {detail}")
        return False, f"Не удалось применить авто DNS. {detail}"
    suffix = f" ({ok_count}/{len(adapters)})" if len(adapters) > 1 else ""
    return True, f"Авто DNS применён{suffix}."


def apply_provider(
    adapters: list[str],
    ipv4: list[str],
    ipv6: list[str],
    *,
    ipv6_available: bool,
) -> tuple[bool, str]:
    mgr = _get_manager()
    ok_count = 0
    errors: list[str] = []
    for adapter in adapters:
        ok_v4 = True
        if ipv4:
            ok_v4, msg_v4 = mgr.set_custom_dns(adapter, ipv4[0], ipv4[1] if len(ipv4) > 1 else None, "IPv4")
            if not ok_v4:
                errors.append(f"{adapter}: {msg_v4}")
        ok_v6 = True
        if ipv6_available and ipv6:
            ok_v6, msg_v6 = mgr.set_custom_dns(adapter, ipv6[0], ipv6[1] if len(ipv6) > 1 else None, "IPv6")
            if not ok_v6:
                errors.append(f"{adapter}: {msg_v6}")
        if ok_v4 and ok_v6:
            ok_count += 1
    mgr.flush_dns_cache()
    debug("dns", f"apply_provider adapters={adapters} ipv4={ipv4} ok={ok_count}")
    if not adapters:
        return False, "Нет сетевых адаптеров."
    if ok_count == 0:
        detail = errors[0] if errors else "Запустите от администратора."
        warn("dns", f"apply_provider failed: {detail}")
        return False, f"Не удалось применить DNS провайдера. {detail}"
    suffix = f" ({ok_count}/{len(adapters)})" if len(adapters) > 1 else ""
    return True, f"DNS провайдера применён{suffix}."


def apply_custom(adapters: list[str], primary: str, secondary: str | None) -> tuple[bool, str]:
    mgr = _get_manager()
    ok_count = 0
    errors: list[str] = []
    for adapter in adapters:
        ok, msg = mgr.set_custom_dns(adapter, primary, secondary, "IPv4")
        if ok:
            ok_count += 1
        else:
            errors.append(f"{adapter}: {msg}")
    mgr.flush_dns_cache()
    debug("dns", f"apply_custom adapters={adapters} primary={primary} ok={ok_count}")
    if not adapters:
        return False, "Нет сетевых адаптеров."
    if ok_count == 0:
        detail = errors[0] if errors else "Запустите от администратора."
        warn("dns", f"apply_custom failed: {detail}")
        return False, f"Не удалось применить свой DNS. {detail}"
    suffix = f" ({ok_count}/{len(adapters)})" if len(adapters) > 1 else ""
    return True, f"Свой DNS применён{suffix}."


def reset_dns_settings(adapters: list[str]) -> tuple[bool, str]:
    """Reset DNS to automatic (DHCP) for selected adapters."""
    ok, msg = apply_auto(adapters)
    if ok:
        return True, "DNS сброшен на автоматические (DHCP)."
    return ok, msg


def flush_cache() -> tuple[bool, str]:
    ok, msg = _get_manager().flush_dns_cache()
    return ok, msg or ("DNS-кэш сброшен" if ok else "Не удалось сбросить DNS-кэш")
