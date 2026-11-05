"""Probe results table for one strategy."""

from __future__ import annotations

import re
from typing import Literal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import CaptionLabel

from src.modules.strategy_testing import results as tr
from src.ui.components import COLOR_ERROR, COLOR_MUTED, COLOR_SUCCESS, COLOR_WARNING, clear_layout, spinner

CellKey = tuple[str, str]
MetricField = Literal["http", "tls12", "tls13"]
_METRIC_FIELDS: tuple[MetricField, ...] = ("http", "tls12", "tls13")
_CAPTIONS = ("Адрес", "HTTP", "TLS 1.2", "TLS 1.3", "Ping")
_COLOR_TEXT = ("#1a1a1a", "#ffffff")


def _metric_value(raw: str) -> str:
    if ":" in raw:
        return raw.split(":", 1)[1]
    return raw


def _token_color(raw: str) -> tuple[str, str]:
    value = _metric_value(raw).strip()
    upper = value.upper()
    if upper == "OK":
        return COLOR_SUCCESS
    if upper in {"?", ""}:
        return COLOR_MUTED
    if upper in {"ERROR", "ERR"}:
        return COLOR_ERROR
    if "UNSUP" in upper:
        return COLOR_WARNING
    if any(x in upper for x in ("SSL", "FAIL", "TIMEOUT")):
        return COLOR_ERROR
    if value.lower() in {"timeout", "n/a"}:
        return COLOR_WARNING
    return _COLOR_TEXT


def _parse_ping_ms(text: str) -> int | None:
    match = re.search(r"(\d+)", text.replace(" ", ""))
    return int(match.group(1)) if match else None


def _ping_value_color(text: str) -> tuple[str, str]:
    upper = text.upper()
    if any(x in upper for x in ("ERROR", "FAIL", "TIMEOUT")) or upper.strip() in {"N/A", "?"}:
        return COLOR_ERROR
    ms = _parse_ping_ms(text)
    if ms is None:
        return _COLOR_TEXT
    if ms >= 200:
        return COLOR_ERROR
    if ms > 100:
        return COLOR_WARNING
    return COLOR_SUCCESS


def _short_token(raw: str) -> str:
    value = _metric_value(raw)
    return "ERR" if value == "ERROR" else value


def _cell_view(cell: tr.ProbeCell, *, ping: bool) -> tuple[str, tuple[str, str]]:
    if ping:
        if cell.phase == "pending" or cell.text in {"?", "? ms"}:
            return "—", COLOR_MUTED
        return cell.text.replace(" ", ""), _ping_value_color(cell.text)
    if cell.phase == "pending" or cell.text == "?":
        return "—", COLOR_MUTED
    return _short_token(cell.text), _token_color(cell.text)


class _Cell(QWidget):
    """A value label that turns into a ring while the probe is running."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self.label = CaptionLabel("—", self)
        self._layout.addWidget(self.label)
        self.ring = None

    def show_value(self, text: str, color: tuple[str, str]) -> None:
        if self.ring is not None:
            self.ring.setParent(None)
            self.ring.deleteLater()
            self.ring = None
        self.label.setVisible(True)
        self.label.setText(text)
        self.label.setTextColor(*color)

    def show_ring(self):
        if self.ring is None:
            self.ring = spinner(14, self)
            self._layout.addWidget(self.ring)
            self.label.setVisible(False)
        return self.ring


class ProbeTableView(QWidget):
    """Reuses cells and rings between syncs, so a ring is not restarted on every tick."""

    def __init__(self, strategy_id: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._strategy_id = strategy_id
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)
        self._detail = CaptionLabel(self)
        self._detail.setWordWrap(True)
        self._detail.setTextColor(*COLOR_ERROR)
        self._detail.setVisible(False)
        root.addWidget(self._detail)
        self._grid = QGridLayout()
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(16)
        self._grid.setVerticalSpacing(6)
        self._grid.setColumnStretch(0, 1)
        root.addLayout(self._grid)
        self._cells: dict[CellKey, _Cell] = {}
        self._spinners: dict[CellKey, QWidget] = {}
        self._row_order: list[str] = []
        self.sync(strategy_id)

    def sync(self, strategy_id: str | None = None) -> None:
        sid = strategy_id or self._strategy_id
        self._strategy_id = sid
        rows = tr.get_probe_table(sid) or tr.default_probe_table()
        item = tr.get_result(sid)
        detail = item.detail.strip() if item and item.detail and not tr.get_probe_table(sid) else ""
        self._detail.setText(detail)
        self._detail.setVisible(bool(detail))
        names = [row.name for row in rows]
        if names != self._row_order:
            self._rebuild(rows)
        for row in rows:
            if row.http is not None:
                for field in _METRIC_FIELDS:
                    self._paint((row.name, field), getattr(row, field), ping=False)
            self._paint((row.name, "ping"), row.ping, ping=True)

    def _rebuild(self, rows: list[tr.ProbeTableRow]) -> None:
        clear_layout(self._grid)
        self._cells.clear()
        self._spinners.clear()
        self._row_order = [row.name for row in rows]
        for column, text in enumerate(_CAPTIONS):
            head = CaptionLabel(text, self)
            head.setTextColor(*COLOR_MUTED)
            self._grid.addWidget(head, 0, column)
        for index, row in enumerate(rows, start=1):
            self._grid.addWidget(CaptionLabel(row.name, self), index, 0, Qt.AlignmentFlag.AlignVCenter)
            if row.http is not None:
                for column, field in enumerate(_METRIC_FIELDS, start=1):
                    self._cells[(row.name, field)] = cell = _Cell(self)
                    self._grid.addWidget(cell, index, column)
            self._cells[(row.name, "ping")] = cell = _Cell(self)
            self._grid.addWidget(cell, index, 4)

    def _paint(self, key: CellKey, value: tr.ProbeCell, *, ping: bool) -> None:
        cell = self._cells.get(key)
        if cell is None:
            return
        if value.phase == "loading":
            self._spinners[key] = cell.show_ring()
            return
        self._spinners.pop(key, None)
        text, color = _cell_view(value, ping=ping)
        cell.show_value(text, color)
