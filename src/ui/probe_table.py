"""Probe results table — compact UI rows (not selectable text)."""

from __future__ import annotations

import re
from typing import Literal

import flet as ft

from src.modules.strategy_testing import results as tr
from src.ui.theme import T, argb
from src.ui.components import ui_text

NAME_WIDTH = 148
HTTP_WIDTH = 64
TLS_WIDTH = 72
PING_WIDTH = 72
PROBE_FONT_SIZE = 12

CellKey = tuple[str, str]
MetricField = Literal["http", "tls12", "tls13"]
_METRIC_FIELDS: tuple[tuple[MetricField, str, int], ...] = (
    ("http", "HTTP", HTTP_WIDTH),
    ("tls12", "TLS1.2", TLS_WIDTH),
    ("tls13", "TLS1.3", TLS_WIDTH),
)


def factiosi_spinner(*, size: int = 16) -> ft.Container:
    """Квадрат с жёсткими пределами. Иначе кольцо тянется по ширине ячейки и становится овалом."""
    return ft.Container(
        width=size,
        height=size,
        alignment=ft.Alignment.CENTER,
        content=ft.ProgressRing(
            stroke_width=2,
            padding=0,
            track_gap=0,
            year_2023=True,
            size_constraints=ft.BoxConstraints(
                min_width=size,
                max_width=size,
                min_height=size,
                max_height=size,
            ),
            color=T.BUTTON,
            bgcolor=argb(T.BUTTON, 0x4D),
        ),
    )


def _metric_value(raw: str) -> str:
    if ":" in raw:
        return raw.split(":", 1)[1]
    return raw


def _token_color(raw: str) -> str:
    value = _metric_value(raw).strip()
    upper = value.upper()
    if upper == "OK":
        return T.STATUS_ACTIVE
    if upper in {"?", ""}:
        return T.TEXT_FAINT
    if upper in {"ERROR", "ERR"}:
        return T.STATUS_ERROR
    if "UNSUP" in upper:
        return T.STATUS_EXPIRING
    if any(x in upper for x in ("SSL", "FAIL", "TIMEOUT")):
        return T.STATUS_ERROR
    if value.lower() in {"timeout", "n/a"}:
        return T.STATUS_EXPIRING
    return T.TEXT


def _parse_ping_ms(text: str) -> int | None:
    match = re.search(r"(\d+)", text.replace(" ", ""))
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def _ping_value_color(text: str) -> str:
    upper = text.upper()
    if any(x in upper for x in ("ERROR", "FAIL", "TIMEOUT")) or upper.strip() in {"N/A", "?"}:
        return T.STATUS_ERROR
    ms = _parse_ping_ms(text)
    if ms is None:
        return T.TEXT
    if ms >= 200:
        return T.STATUS_ERROR
    if ms > 100:
        return T.STATUS_EXPIRING
    return T.STATUS_ACTIVE


def _short_token(raw: str) -> str:
    value = _metric_value(raw)
    if value == "?":
        return "?"
    if value == "OK":
        return "OK"
    if value == "ERROR":
        return "ERR"
    if value == "UNSUP":
        return "UNSUP"
    if value == "SSL":
        return "SSL"
    return value


def _value_text(value: str, *, value_color: str) -> ft.Control:
    return ui_text(value, size=PROBE_FONT_SIZE, color=value_color, no_wrap=True, weight=ft.FontWeight.W_600)


def _loading_content(spinner: ft.Control) -> ft.Control:
    return spinner


def _value_content(cell: tr.ProbeCell, *, ping: bool = False) -> ft.Control:
    if ping:
        if cell.phase == "pending" or cell.text in {"?", "? ms"}:
            return _value_text("—", value_color=T.TEXT_FAINT)
        ping_value = cell.text.replace(" ", "")
        return _value_text(ping_value, value_color=_ping_value_color(cell.text))

    if cell.phase == "pending" or cell.text == "?":
        return _value_text("—", value_color=T.TEXT_FAINT)
    value = _short_token(cell.text)
    return _value_text(value, value_color=_token_color(cell.text))


class ProbeTableView:
    """Mutable probe table that reuses spinner controls between sync calls."""

    def __init__(self, strategy_id: str) -> None:
        self._strategy_id = strategy_id
        self._table = ft.Column(spacing=0, tight=True)
        self._root: ft.Control = self._table
        self._row_by_name: dict[str, ft.Container] = {}
        self._cell_containers: dict[CellKey, ft.Container] = {}
        self._spinners: dict[CellKey, ft.Control] = {}
        self._row_order: list[str] = []
        self.sync(strategy_id)

    @property
    def control(self) -> ft.Control:
        return self._root

    def sync(self, strategy_id: str | None = None) -> None:
        sid = strategy_id or self._strategy_id
        self._strategy_id = sid
        rows = tr.get_probe_table(sid) or tr.default_probe_table()
        item = tr.get_result(sid)
        if item and item.detail.strip() and not tr.get_probe_table(sid):
            self._root = ft.Column(
                [
                    ui_text(item.detail.strip(), size=PROBE_FONT_SIZE, color=T.STATUS_ERROR),
                    self._table,
                ],
                spacing=8,
                tight=True,
            )
        elif self._root is not self._table:
            self._root = self._table

        names = [row.name for row in rows]
        if names != self._row_order:
            self._rebuild_rows(rows)
            return
        for row in rows:
            self._sync_row(row)

    def _rebuild_rows(self, rows: list[tr.ProbeTableRow]) -> None:
        self._table.controls.clear()
        self._row_by_name.clear()
        self._cell_containers.clear()
        self._spinners.clear()
        self._row_order = [row.name for row in rows]
        self._table.controls.append(self._header())
        for row in rows:
            row_container = self._build_row(row)
            self._row_by_name[row.name] = row_container
            self._table.controls.append(row_container)

    def _header(self) -> ft.Container:
        captions = [("Адрес", NAME_WIDTH), ("HTTP", HTTP_WIDTH), ("TLS 1.2", TLS_WIDTH), ("TLS 1.3", TLS_WIDTH), ("Ping", PING_WIDTH)]
        return ft.Container(
            content=ft.Row(
                [
                    ft.Container(
                        content=ui_text(caption, size=PROBE_FONT_SIZE, color=T.TEXT_MUTED, no_wrap=True),
                        width=width,
                    )
                    for caption, width in captions
                ],
                spacing=8,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.Padding.only(left=8, right=8, bottom=4),
        )

    def _build_row(self, row: tr.ProbeTableRow) -> ft.Container:
        cells: list[ft.Control] = [
            ft.Container(
                content=ui_text(row.name, size=PROBE_FONT_SIZE, color=T.TEXT, no_wrap=True),
                width=NAME_WIDTH,
            )
        ]
        if row.http is not None:
            for field, label, width in _METRIC_FIELDS:
                cell = getattr(row, field)
                cells.append(self._ensure_cell((row.name, field), cell, label, width))
        else:
            for _field, _label, width in _METRIC_FIELDS:
                cells.append(ft.Container(width=width))
        cells.append(self._ensure_cell((row.name, "ping"), row.ping, "Ping", PING_WIDTH, ping=True))
        return ft.Container(
            content=ft.Row(
                cells,
                spacing=8,
                tight=True,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            bgcolor=T.SUNKEN,
            border_radius=4,
            padding=ft.Padding.symmetric(horizontal=8, vertical=4),
            margin=ft.Margin.only(bottom=4),
        )

    def _sync_row(self, row: tr.ProbeTableRow) -> None:
        if row.http is not None:
            for field, label, width in _METRIC_FIELDS:
                cell = getattr(row, field)
                self._sync_cell((row.name, field), cell, label, width)
        self._sync_cell((row.name, "ping"), row.ping, "Ping", PING_WIDTH, ping=True)

    def _ensure_cell(
        self,
        key: CellKey,
        cell: tr.ProbeCell,
        label: str,
        width: int,
        *,
        ping: bool = False,
    ) -> ft.Container:
        if cell.phase == "loading":
            spinner = factiosi_spinner(size=16)
            self._spinners[key] = spinner
            content: ft.Control = _loading_content(spinner)
        else:
            content = _value_content(cell, ping=ping)
        container = ft.Container(
            content=content,
            width=width,
            alignment=ft.Alignment.CENTER_LEFT,
        )
        self._cell_containers[key] = container
        return container

    def _sync_cell(
        self,
        key: CellKey,
        cell: tr.ProbeCell,
        label: str,
        width: int,
        *,
        ping: bool = False,
    ) -> None:
        container = self._cell_containers.get(key)
        if container is None:
            row = self._row_by_name.get(key[0])
            if row is None:
                return
            self._ensure_cell(key, cell, label, width, ping=ping)
            return

        if cell.phase == "loading":
            if key in self._spinners:
                return
            spinner = factiosi_spinner(size=16)
            self._spinners[key] = spinner
            container.content = _loading_content(spinner)
            return

        self._spinners.pop(key, None)
        container.content = _value_content(cell, ping=ping)


def build_probe_table(strategy_id: str) -> ft.Control:
    return ProbeTableView(strategy_id).control
