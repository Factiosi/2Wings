"""Hosts editor actions for the UI."""

from __future__ import annotations

import ctypes
import os
from ctypes import wintypes
from dataclasses import dataclass

import httpx

from src.core.debug_log import info, warn
from src.core.settings import get_settings, save_settings
from src.modules.dns.core import flush_dns_cache_native
from src.modules.hosts.catalog import (
    Catalog,
    CatalogError,
    has_ipv6_route,
    load_catalog,
    profile_relays,
    service_domains,
    service_rows,
)
from src.modules.hosts.live import PROFILE_DOH, LiveResolveError, reachable, relay_rows
from src.modules.hosts.catalog_update import catalog_check_due, update_catalog
from src.modules.hosts.hosts_file import (
    DEFAULT_HOSTS,
    HostsSummary,
    backup_path,
    decode,
    hosts_path,
    read_hosts,
    set_block,
    summarize,
    write_hosts,
)
from src.modules.hosts.presets import PRESETS, HostsPreset

_ASSOCSTR_EXECUTABLE = 2
_SW_SHOWNORMAL = 1
_ACCESS_HINT = (
    "Нет доступа к файлу hosts. Его может защищать антивирус "
    "(в Защитнике Windows — «Изменение файла hosts»): разрешите изменение и повторите."
)


@dataclass(frozen=True)
class HostsState:
    summary: HostsSummary
    presets: list[tuple[HostsPreset, int]]  # preset, entries currently written (0 = off)
    has_backup: bool


def load_state() -> HostsState:
    summary = summarize(read_hosts())
    return HostsState(
        summary=summary,
        presets=[(preset, summary.blocks.get(preset.id, 0)) for preset in PRESETS],
        has_backup=backup_path().exists(),
    )


def _write(text: str, action: str) -> tuple[bool, str]:
    try:
        write_hosts(text)
    except PermissionError:
        warn("hosts", f"{action}: access denied")
        return False, _ACCESS_HINT
    except OSError as exc:
        warn("hosts", f"{action}: {exc}")
        return False, f"Не удалось записать hosts: {exc}"
    flush_dns_cache_native()
    info("hosts", action)
    return True, ""


def set_preset(preset_id: str, enabled: bool) -> tuple[bool, str]:
    preset = next((item for item in PRESETS if item.id == preset_id), None)
    if preset is None:
        return False, "Набор не найден."
    text = set_block(read_hosts(), preset.id, preset.rows() if enabled else None)
    ok, error = _write(text, f"preset {preset.id} {'on' if enabled else 'off'}")
    if not ok:
        return False, error
    return True, f"«{preset.title}»: {'включено' if enabled else 'выключено'}."


SERVICE_BLOCK_PREFIX = "svc-"


def service_block_id(service_id: str) -> str:
    return SERVICE_BLOCK_PREFIX + service_id.lower()


def collect_service_rows(catalog: Catalog, selection: dict[str, str], *, ipv6: bool) -> dict[str, list[tuple[str, str]]]:
    """Addresses for every chosen service: live for DoH profiles, snapshot otherwise.

    Addresses that do not accept a connection on 443 are dropped, so a dead
    relay never ends up in hosts.
    """
    rows: dict[str, list[tuple[str, str]]] = {}
    live_domains: dict[str, dict[str, list[str]]] = {}  # profile -> service -> domains
    for service_id, profile_id in selection.items():
        service = catalog.service(service_id)
        if service is None:
            continue
        if service.kind == "dns" and profile_id in PROFILE_DOH:
            live_domains.setdefault(profile_id, {})[service_id] = service_domains(catalog, service_id)
        else:
            rows[service_id] = service_rows(catalog, service_id, profile_id, ipv6=ipv6)
    for profile_id, services in live_domains.items():
        domains = [domain for names in services.values() for domain in names]
        by_host: dict[str, list[tuple[str, str]]] = {}
        known = profile_relays(catalog, profile_id)
        for address, host in relay_rows(domains, profile_id, ipv6=ipv6, known_relays=known):
            by_host.setdefault(host, []).append((address, host))
        for service_id, names in services.items():
            rows[service_id] = [row for name in dict.fromkeys(names) for row in by_host.get(name, [])]
    alive = reachable({address for entries in rows.values() for address, _ in entries})
    return {sid: [row for row in entries if row[0] in alive] for sid, entries in rows.items()}


def _services_text(text: str, rows: dict[str, list[tuple[str, str]]]) -> tuple[str, int]:
    """Rewrite every service block; return (text, entries written)."""
    wanted = {service_block_id(sid) for sid in rows}
    for block_id in summarize(text).blocks:
        if block_id.startswith(SERVICE_BLOCK_PREFIX) and block_id not in wanted:
            text = set_block(text, block_id, None)
    written = 0
    for service_id, entries in rows.items():
        text = set_block(text, service_block_id(service_id), entries)
        written += len(entries)
    return text, written


def apply_services(selection: dict[str, str]) -> tuple[bool, str]:
    """Write the chosen services into hosts and remember the choice."""
    try:
        catalog = load_catalog()
    except CatalogError as exc:
        return False, f"Каталог сервисов недоступен: {exc}"
    known = {sid: pid for sid, pid in selection.items() if catalog.service(sid)}
    try:
        rows = collect_service_rows(catalog, known, ipv6=has_ipv6_route())
    except LiveResolveError as exc:
        return False, f"Не удалось спросить адреса: {exc}. hosts не изменён."
    empty = [catalog.service(sid).name for sid, entries in rows.items() if not entries]
    current = read_hosts()
    text, written = _services_text(current, rows)
    if text != current:
        ok, error = _write(text, f"services applied: {len(known)} services, {written} entries")
        if not ok:
            return False, error
    settings = get_settings()
    settings.hosts_services = known
    save_settings(settings)
    message = f"Сервисы в hosts: {len(known)}, записей: {written}." if known else "Сервисы убраны из hosts."
    if empty:
        message += f" Выбранный DNS сейчас не открывает: {', '.join(empty)}."
    return True, message


def hosts_uses_addresses(addresses: set[str]) -> bool:
    """True when an active hosts line points at one of the addresses."""
    for line in read_hosts().splitlines():
        parts = line.split("#", 1)[0].split()
        if parts and parts[0].lower() in addresses:
            return True
    return False


def refresh_catalog_and_services(*, force: bool = False) -> tuple[bool, str]:
    """Fetch a newer catalog when due and rewrite the chosen services with it."""
    if not force and not catalog_check_due():
        return True, ""
    try:
        changed, message = update_catalog()
    except (CatalogError, httpx.HTTPError, OSError, ValueError) as exc:
        warn("hosts", f"catalog update failed: {exc}")
        return False, f"Не удалось обновить каталог сервисов: {exc}"
    selection = get_settings().hosts_services
    if selection:
        # Relay addresses change between catalog releases too: re-ask on every check.
        ok, applied = apply_services(selection)
        return ok, f"{message} {applied}"
    return True, message


def restore_default() -> tuple[bool, str]:
    ok, error = _write(DEFAULT_HOSTS, "restored default hosts")
    if not ok:
        return False, error
    _forget_services()
    return True, "Файл hosts восстановлен к стандартному виду Windows."


def restore_backup() -> tuple[bool, str]:
    backup = backup_path()
    if not backup.exists():
        return False, "Резервной копии нет: Tigo ещё не менял hosts."
    ok, error = _write(decode(backup.read_bytes()), "restored hosts backup")
    if not ok:
        return False, error
    _forget_services()
    return True, "Файл hosts восстановлен из копии, снятой до первого изменения Tigo."


def _forget_services() -> None:
    """The file no longer has service blocks; keep the saved choice in step."""
    settings = get_settings()
    if settings.hosts_services:
        settings.hosts_services = {}
        save_settings(settings)


def default_text_editor() -> str:
    """Executable registered for .txt files, Notepad when there is none."""
    buffer = ctypes.create_unicode_buffer(1024)
    size = wintypes.DWORD(len(buffer))
    result = ctypes.windll.shlwapi.AssocQueryStringW(
        0, _ASSOCSTR_EXECUTABLE, ".txt", "open", buffer, ctypes.byref(size)
    )
    if result == 0 and buffer.value and os.path.isfile(buffer.value):
        return buffer.value
    return "notepad.exe"


def open_in_editor() -> tuple[bool, str]:
    """Open hosts in the default text editor, elevated so it can save the file."""
    editor = default_text_editor()
    code = ctypes.windll.shell32.ShellExecuteW(None, "runas", editor, f'"{hosts_path()}"', None, _SW_SHOWNORMAL)
    if code <= 32 and editor != "notepad.exe":
        warn("hosts", f"{editor} did not start elevated ({code}), falling back to Notepad")
        editor = "notepad.exe"
        code = ctypes.windll.shell32.ShellExecuteW(None, "runas", editor, f'"{hosts_path()}"', None, _SW_SHOWNORMAL)
    if code <= 32:
        return False, f"Не удалось открыть редактор (код {code})."
    name = os.path.splitext(os.path.basename(editor))[0]
    return True, f"Файл hosts открыт в {name} от имени администратора. После сохранения нажмите «Обновить»."
