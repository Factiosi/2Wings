"""Shared Fluent controls: pages, setting cards, selects and status marks."""

from __future__ import annotations

import os
from collections.abc import Callable, Iterable, Sequence
from functools import lru_cache

from PySide6.QtCore import (
    Property,
    QAbstractAnimation,
    QByteArray,
    QEasingCurve,
    QElapsedTimer,
    QPropertyAnimation,
    QRectF,
    Qt,
    QTimer,
    QVariantAnimation,
    Signal,
)
from PySide6.QtGui import QColor, QIcon, QPainter, QSurfaceFormat
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QAbstractButton, QApplication, QFrame, QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    ComboBox,
    DotInfoBadge,
    FluentIconBase,
    IconWidget,
    IndeterminateProgressRing,
    InfoBadge,
    InfoLevel,
    LineEdit,
    ScrollArea,
    SimpleCardWidget,
    StrongBodyLabel,
    SwitchButton,
    Theme,
    TitleLabel,
    setTheme,
    isDarkTheme,
    setThemeColor,
)
from qfluentwidgets.common.icon import SvgIconEngine
from qfluentwidgets.components.widgets.combo_box import ComboBoxMenu
from qfluentwidgets.components.widgets.menu import IndicatorMenuItemDelegate
from qframelesswindow.utils import getSystemAccentColor

from src.core.paths import program_root

PAGE_MARGIN = 36
ROW_GAP = 4
GROUP_GAP = 24

# WinUI status colors: (light theme, dark theme).
COLOR_SUCCESS = ("#0f7b0f", "#6ccb5f")
COLOR_WARNING = ("#9d5d00", "#fce100")
COLOR_ERROR = ("#c42b1c", "#ff99a4")
COLOR_MUTED = ("#5c5c5c", "#9d9d9d")

EXPAND_MS = 220
BADGE_MENU_WIDTH = 380
WHEEL_NOTCH_PX = 120
WHEEL_GLIDE_MS = 180

# InfoBadge colours by status: (light background, dark background, attention uses the accent).
_BADGE_COLORS = {
    "active": ("#0f7b0f", "#6ccb5f"),
    "expiring": ("#9d5d00", "#fce100"),
    "error": ("#c42b1c", "#ff99a4"),
    "offline": ("#5c5c5c", "#9d9d9d"),
    "connecting": ("#005fb8", "#60cdff"),
}

_LEVELS = {
    "active": InfoLevel.SUCCESS,
    "connecting": InfoLevel.ATTENTION,
    "expiring": InfoLevel.WARNING,
    "error": InfoLevel.ERROR,
    "offline": InfoLevel.INFOAMTION,
}


def use_vsync_rendering() -> None:
    """Compose widgets through Direct3D. Software composition is not synchronised with the
    display, which shows as tears while scrolling. Call before QApplication is created."""
    os.environ.setdefault("QT_WIDGETS_RHI", "1")
    os.environ.setdefault("QT_WIDGETS_RHI_BACKEND", "d3d11")
    # Without an alpha channel the see-through part of the window comes out black
    # instead of showing Mica.
    surface = QSurfaceFormat.defaultFormat()
    surface.setAlphaBufferSize(8)
    QSurfaceFormat.setDefaultFormat(surface)


def _display_tick_ms() -> int:
    rates = [screen.refreshRate() for screen in QApplication.screens()]
    return max(1, round(1000 / max([*rates, 60.0])))


def play_at_display_rate(animation: QAbstractAnimation) -> None:
    """Play an animation at the display's rate. Qt ticks every animation 60 times a second,
    which reads as too few frames on a faster monitor, and has no public way to change it."""
    if animation.state() != QAbstractAnimation.State.Running:
        animation.start()
    animation.pause()
    clock = QElapsedTimer()
    clock.start()
    offset = animation.currentTime()
    previous = getattr(animation, "display_timer", None)
    if previous is not None:
        previous.stop()
        previous.deleteLater()
    timer = QTimer(animation)
    timer.setTimerType(Qt.TimerType.PreciseTimer)
    timer.setInterval(_display_tick_ms())
    animation.display_timer = timer

    def tick() -> None:
        if animation.state() == QAbstractAnimation.State.Stopped:
            timer.stop()
            return
        animation.setCurrentTime(offset + clock.elapsed())

    timer.timeout.connect(tick)
    timer.start()


@lru_cache(maxsize=None)
def _lucide_source(name: str) -> str:
    return (program_root() / "assets" / "icons" / "lucide" / f"{name}.svg").read_text(encoding="utf-8")


class Lucide(FluentIconBase):
    """Icon from assets/icons/lucide, drawn in the theme's text colour."""

    def __init__(self, name: str) -> None:
        self.name = name

    def path(self, theme=Theme.AUTO) -> str:
        return str(program_root() / "assets" / "icons" / "lucide" / f"{self.name}.svg")

    def _svg(self, theme, color=None) -> str:
        if color is None:
            dark = isDarkTheme() if theme == Theme.AUTO else theme == Theme.DARK
            color = "#ffffff" if dark else "#000000"
        return _lucide_source(self.name).replace("currentColor", QColor(color).name())

    def icon(self, theme=Theme.AUTO, color=None) -> QIcon:
        return QIcon(SvgIconEngine(self._svg(theme, color)))

    def render(self, painter, rect, theme=Theme.AUTO, indexes=None, **attributes) -> None:
        renderer = QSvgRenderer(QByteArray(self._svg(theme, attributes.get("fill")).encode("utf-8")))
        renderer.render(painter, QRectF(rect))


class ExpandChevron(QAbstractButton):
    """Expander arrow that turns over when its row opens."""

    def __init__(self, expanded: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(30, 30)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._angle = 180.0 if expanded else 0.0
        self._icon = Lucide("chevron-down")
        self._turn = QPropertyAnimation(self, b"angle", self)
        self._turn.setDuration(EXPAND_MS)
        self._turn.setEasingCurve(QEasingCurve.Type.OutCubic)

    def _get_angle(self) -> float:
        return self._angle

    def _set_angle(self, value: float) -> None:
        self._angle = value
        self.update()

    angle = Property(float, _get_angle, _set_angle)

    def set_expanded(self, expanded: bool) -> None:
        self._turn.stop()
        self._turn.setStartValue(self._angle)
        self._turn.setEndValue(180.0 if expanded else 0.0)
        play_at_display_rate(self._turn)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
        if self.underMouse():
            shade = 255 if isDarkTheme() else 0
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(shade, shade, shade, 14))
            painter.drawRoundedRect(self.rect(), 4, 4)
        painter.translate(self.width() / 2, self.height() / 2)
        painter.rotate(self._angle)
        self._icon.render(painter, QRectF(-8, -8, 16, 16))

    def enterEvent(self, event) -> None:
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self.update()
        super().leaveEvent(event)


def apply_theme(mode: str) -> None:
    """``mode``: auto | dark | light. The accent always comes from Windows."""
    setTheme({"dark": Theme.DARK, "light": Theme.LIGHT}.get(mode, Theme.AUTO))
    accent = getSystemAccentColor()
    if accent.isValid():
        setThemeColor(accent)


def caption(text: str, *, parent: QWidget | None = None) -> CaptionLabel:
    label = CaptionLabel(text, parent)
    label.setWordWrap(True)
    label.setTextColor(*COLOR_MUTED)
    return label


def spinner(size: int = 16, parent: QWidget | None = None) -> IndeterminateProgressRing:
    ring = IndeterminateProgressRing(parent)
    ring.setFixedSize(size, size)
    ring.setStrokeWidth(2)
    return ring


def row(*widgets: QWidget, stretch: bool = True, spacing: int = 8) -> QWidget:
    """A horizontal strip of controls, left-aligned unless ``stretch`` is off."""
    holder = QWidget()
    layout = QHBoxLayout(holder)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(spacing)
    for widget in widgets:
        layout.addWidget(widget)
    if stretch:
        layout.addStretch(1)
    return holder


def clear_layout(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.setParent(None)
            widget.deleteLater()
        elif item.layout() is not None:
            clear_layout(item.layout())


class _BadgeDelegate(IndicatorMenuItemDelegate):
    """Menu item with the same status badge a strategy has elsewhere."""

    def __init__(self, select: "Select") -> None:
        super().__init__()
        self._select = select

    def paint(self, painter, option, index) -> None:
        super().paint(painter, option, index)
        items = self._select.items
        if index.row() >= len(items):
            return
        badge = self._select.badges.get(str(items[index.row()].userData))
        if badge is None:
            return
        kind, text = badge
        light, dark = _BADGE_COLORS.get(kind, _BADGE_COLORS["offline"])
        is_dark = isDarkTheme()
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        font = painter.font()
        font.setPixelSize(11)
        painter.setFont(font)
        width = painter.fontMetrics().horizontalAdvance(text) + 16
        rect = option.rect.adjusted(0, 0, -14, 0)
        box = QRectF(rect.right() - width, rect.center().y() - 8, width, 16)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(dark if is_dark else light))
        painter.drawRoundedRect(box, 8, 8)
        painter.setPen(QColor("#000000" if is_dark else "#ffffff"))
        painter.drawText(box, Qt.AlignmentFlag.AlignCenter, text)
        painter.restore()


class Select(ComboBox):
    """ComboBox over (value, label) pairs; ``changed`` fires only on user choice."""

    changed = Signal(str)

    def __init__(self, options: Sequence[tuple[str, str]] = (), value: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._guard = False
        self.badges: dict[str, tuple[str, str]] = {}  # value -> (status kind, text)
        self.setMinimumWidth(240)
        self.setMaxVisibleItems(12)
        self.set_options(options, value)
        self.currentIndexChanged.connect(self._on_index)

    def set_options(self, options: Sequence[tuple[str, str]], value: str = "") -> None:
        self._guard = True
        self.clear()
        for option_value, label in options:
            self.addItem(label, userData=option_value)
        self.set_value(value)
        self._guard = False

    def _showComboMenu(self):
        super()._showComboMenu()
        if self.dropMenu is not None and self.dropMenu.aniManager is not None:
            play_at_display_rate(self.dropMenu.aniManager.ani)

    def _createComboMenu(self):
        menu = ComboBoxMenu(self)
        if self.badges:
            menu.view.setMinimumWidth(BADGE_MENU_WIDTH)
            # Set on the instance: a Python subclass of this menu loses its exec() override.
            menu.badge_delegate = _BadgeDelegate(self)
            menu.view.setItemDelegate(menu.badge_delegate)
        return menu

    def value(self) -> str:
        return str(self.currentData() or "")

    def set_value(self, value: str) -> None:
        guard = self._guard
        self._guard = True
        index = self.findData(value)
        if index >= 0:
            self.setCurrentIndex(index)
        self._guard = guard

    def _on_index(self, _index: int) -> None:
        if not self._guard:
            self.changed.emit(self.value())


class OptionCard(SimpleCardWidget):
    """Fluent settings row: icon, title with description, controls on the right."""

    def __init__(
        self,
        title: str,
        description: str = "",
        *controls: QWidget,
        icon: FluentIconBase | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.outer = QVBoxLayout(self)
        self.outer.setContentsMargins(16, 12, 16, 12)
        self.outer.setSpacing(8)
        line = QHBoxLayout()
        line.setSpacing(16)
        if icon is not None:
            mark = IconWidget(icon, self)
            mark.setFixedSize(16, 16)
            line.addWidget(mark)
        texts = QVBoxLayout()
        texts.setSpacing(0)
        self.title_label = BodyLabel(title, self)
        self.title_label.setWordWrap(True)
        texts.addWidget(self.title_label)
        self.description_label = caption(description, parent=self)
        self.description_label.setVisible(bool(description))
        texts.addWidget(self.description_label)
        line.addLayout(texts, 1)
        for control in controls:
            line.addWidget(control, 0, Qt.AlignmentFlag.AlignVCenter)
        self.outer.addLayout(line)


def switch(checked: bool, on_toggle: Callable[[bool], None] | None = None) -> SwitchButton:
    button = SwitchButton()
    button.setOnText("Вкл.")
    button.setOffText("Выкл.")
    button.setChecked(checked)
    if on_toggle is not None:
        button.checkedChanged.connect(on_toggle)
    return button


def switch_card(
    title: str,
    description: str,
    checked: bool,
    on_toggle: Callable[[bool], None],
    *,
    icon: FluentIconBase | None = None,
) -> OptionCard:
    return OptionCard(title, description, switch(checked, on_toggle), icon=icon)


def select_card(
    title: str,
    options: Sequence[tuple[str, str]],
    value: str,
    on_change: Callable[[str], None] | None,
    *,
    description: str = "",
    icon: FluentIconBase | None = None,
) -> OptionCard:
    select = Select(options, value)
    if on_change is None:
        select.setEnabled(False)
    else:
        select.changed.connect(on_change)
    card = OptionCard(title, description, select, icon=icon)
    card.select = select
    return card


def text_field(value: str = "", *, placeholder: str = "", width: int | None = None) -> LineEdit:
    field = LineEdit()
    field.setText(value)
    field.setPlaceholderText(placeholder)
    if width is not None:
        field.setFixedWidth(width)
    return field


class StatusMark(QWidget):
    """A coloured dot and a text that may be long, such as an error message."""

    def __init__(self, kind: str = "offline", text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self._dot = DotInfoBadge(self)
        self._dot.setFixedSize(8, 8)
        layout.addWidget(self._dot, 0, Qt.AlignmentFlag.AlignVCenter)
        self._label = BodyLabel(self)
        self._label.setWordWrap(True)
        layout.addWidget(self._label, 1)
        self.set_status(kind, text)

    def set_status(self, kind: str, text: str) -> None:
        self._dot.setLevel(_LEVELS.get(kind, InfoLevel.INFOAMTION))
        self._label.setText(text)


def status_badge(kind: str, text: str, parent: QWidget | None = None) -> InfoBadge:
    return InfoBadge(text, parent, level=_LEVELS.get(kind, InfoLevel.INFOAMTION))


class Group(QWidget):
    """Header over a stack of cards — the Windows settings layout."""

    def __init__(self, title: str | None, *widgets: QWidget, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.stack = QVBoxLayout(self)
        self.stack.setContentsMargins(0, 0, 0, 0)
        self.stack.setSpacing(ROW_GAP)
        self.stack.setAlignment(Qt.AlignmentFlag.AlignTop)
        if title:
            header = StrongBodyLabel(title, self)
            header.setWordWrap(True)
            self.stack.addWidget(header)
            self.stack.addSpacing(4)
        for widget in widgets:
            self.stack.addWidget(widget)

    def add(self, *widgets: QWidget) -> None:
        for widget in widgets:
            self.stack.addWidget(widget)


class Panel(SimpleCardWidget):
    """Card holding free-form content rather than one setting."""

    def __init__(self, *widgets: QWidget, spacing: int = 12, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.stack = QVBoxLayout(self)
        self.stack.setContentsMargins(16, 16, 16, 16)
        self.stack.setSpacing(spacing)
        for widget in widgets:
            self.stack.addWidget(widget)

    def add(self, *widgets: QWidget) -> None:
        for widget in widgets:
            self.stack.addWidget(widget)


class Page(ScrollArea):
    """Scrolling page with the standard title. Subclasses fill it in ``build``."""

    title = ""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.view = QWidget(self)
        self.view.setObjectName("pageView")
        self.body = QVBoxLayout(self.view)
        self.body.setContentsMargins(PAGE_MARGIN, 28, PAGE_MARGIN, 28)
        self.body.setSpacing(GROUP_GAP)
        self.body.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.body.addWidget(TitleLabel(self.title, self.view))
        self.setWidget(self.view)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFrameShape(QFrame.Shape.NoFrame)
        # The library's overlay bar eases every change of the value over half a second and
        # pushes those old values back into the page: that is the jelly, and the jump after
        # a change of height. It follows at once, the wheel gets a short glide of its own.
        self.scrollDelagate.vScrollBar.duration = 0
        self._glide = QVariantAnimation(self)
        self._glide.setDuration(WHEEL_GLIDE_MS)
        self._glide.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._glide.valueChanged.connect(lambda value: self.verticalScrollBar().setValue(int(value)))
        self._glide_target = 0
        self.scrollDelagate.verticalSmoothScroll.wheelEvent = self._on_wheel
        # The window's Mica shows through the page.
        self.setStyleSheet("QScrollArea, #pageView { background: transparent; border: none; }")

    def _on_wheel(self, event) -> None:
        delta = event.angleDelta().y()
        bar = self.verticalScrollBar()
        if delta == 0 or delta % 120 != 0:
            # A touchpad already reports smooth, small steps.
            self._glide.stop()
            bar.setValue(bar.value() - event.pixelDelta().y())
            return
        start = bar.value()
        base = self._glide_target if self._glide.state() != QVariantAnimation.State.Stopped else start
        self._glide_target = max(bar.minimum(), min(bar.maximum(), base - delta * WHEEL_NOTCH_PX // 120))
        self._glide.stop()
        self._glide.setStartValue(start)
        self._glide.setEndValue(self._glide_target)
        play_at_display_rate(self._glide)

    def add(self, *widgets: Iterable[QWidget] | QWidget) -> None:
        for widget in widgets:
            self.body.addWidget(widget)

    def stop(self) -> None:
        """Stop timers and subscriptions; the page is about to be destroyed."""


__all__ = [
    "COLOR_ERROR",
    "COLOR_MUTED",
    "COLOR_SUCCESS",
    "COLOR_WARNING",
    "EXPAND_MS",
    "ExpandChevron",
    "Group",
    "Lucide",
    "OptionCard",
    "Page",
    "Panel",
    "Select",
    "StatusMark",
    "apply_theme",
    "caption",
    "clear_layout",
    "row",
    "select_card",
    "spinner",
    "status_badge",
    "switch",
    "switch_card",
    "text_field",
    "play_at_display_rate",
    "use_vsync_rendering",
]
