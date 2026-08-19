from __future__ import annotations

import re
from html import unescape

from PySide6.QtCore import QEvent, QPoint, QRect, QTimer, Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)


class _HelpPopover(QFrame):
    """Small top-level card used by :class:`HelpIconButton`."""

    pointer_entered = Signal()
    pointer_left = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        flags = (
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.NoDropShadowWindowHint
        )
        super().__init__(parent, flags)
        self.setObjectName("contextHelpPopover")
        self.setAttribute(
            Qt.WidgetAttribute.WA_ShowWithoutActivating,
            True,
        )
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setMinimumWidth(300)
        self.setMaximumWidth(390)

        self.title_label = QLabel()
        self.title_label.setObjectName("contextHelpTitle")
        self.title_label.setWordWrap(True)

        self.body_label = QLabel()
        self.body_label.setObjectName("contextHelpBody")
        self.body_label.setWordWrap(True)
        self.body_label.setTextFormat(Qt.TextFormat.RichText)
        self.body_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.LinksAccessibleByMouse
        )
        self.body_label.setOpenExternalLinks(False)

        self.hint_label = QLabel()
        self.hint_label.setObjectName("contextHelpHint")
        self.hint_label.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 11)
        layout.setSpacing(7)
        layout.addWidget(self.title_label)
        layout.addWidget(self.body_label)
        layout.addWidget(self.hint_label)

        self.set_pinned(False)

    def set_content(self, title: str, body: str) -> None:
        self.title_label.setText(title.strip())
        self.body_label.setText(body.strip())

    def set_pinned(self, pinned: bool) -> None:
        self.setProperty("pinned", bool(pinned))
        if pinned:
            self.hint_label.setText(
                "Ajuda fixada. Clique novamente no ? ou pressione Esc para fechar."
            )
        else:
            self.hint_label.setText(
                "Passe o cursor para consultar ou clique no ? para manter aberto."
            )
        self._repolish()

    def enterEvent(self, event) -> None:  # noqa: N802 - Qt API
        self.pointer_entered.emit()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802 - Qt API
        self.pointer_left.emit()
        super().leaveEvent(event)

    def _repolish(self) -> None:
        style = self.style()
        if style is None:
            return
        style.unpolish(self)
        style.polish(self)
        self.update()


class HelpIconButton(QToolButton):
    """
    Question-mark button with a hover card that can be pinned by clicking.

    The popover also opens for keyboard focus, closes with Escape, and is
    repositioned to stay inside the available screen area.
    """

    _active_button: HelpIconButton | None = None

    def __init__(
        self,
        title: str,
        body: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._title = title.strip()
        self._body = body.strip()

        self.setObjectName("contextHelpButton")
        self.setText("?")
        self.setCheckable(True)
        self.setAutoRaise(False)
        self.setFixedSize(24, 24)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName(f"Ajuda: {self._title}")
        self.setAccessibleDescription(self._plain_text(self._body))

        self._popover = _HelpPopover(self)
        self._popover.set_content(self._title, self._body)
        self._popover.pointer_entered.connect(self._cancel_hide)
        self._popover.pointer_left.connect(self._schedule_hide)

        self._show_timer = QTimer(self)
        self._show_timer.setSingleShot(True)
        self._show_timer.setInterval(320)
        self._show_timer.timeout.connect(self._show_popover)

        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.setInterval(180)
        self._hide_timer.timeout.connect(self._hide_if_unpinned)

        self.clicked.connect(self._toggle_pin)

        self._filter_installed = False

    def set_help_content(self, title: str, body: str) -> None:
        self._title = title.strip()
        self._body = body.strip()
        self.setAccessibleName(f"Ajuda: {self._title}")
        self.setAccessibleDescription(self._plain_text(self._body))
        self._popover.set_content(self._title, self._body)
        if self._popover.isVisible():
            self._position_popover()

    def enterEvent(self, event) -> None:  # noqa: N802 - Qt API
        self._hide_timer.stop()
        if not self._popover.isVisible():
            self._show_timer.start()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802 - Qt API
        self._show_timer.stop()
        self._schedule_hide()
        super().leaveEvent(event)

    def focusInEvent(self, event) -> None:  # noqa: N802 - Qt API
        self._show_timer.stop()

        # A newly opened window may automatically assign focus to the first
        # focusable help icon. Only keyboard navigation should open the card;
        # focus caused by window activation or programmatic setup stays quiet.
        keyboard_focus_reasons = {
            Qt.FocusReason.TabFocusReason,
            Qt.FocusReason.BacktabFocusReason,
            Qt.FocusReason.ShortcutFocusReason,
        }
        if event.reason() in keyboard_focus_reasons:
            self._show_popover()

        super().focusInEvent(event)

    def focusOutEvent(self, event) -> None:  # noqa: N802 - Qt API
        self._schedule_hide()
        super().focusOutEvent(event)

    def event(self, event) -> bool:
        event_type = event.type()
        if (
            event_type == QEvent.Type.Hide
            and hasattr(self, "_popover")
            and hasattr(self, "_show_timer")
        ):
            self.close_help()
        if event_type == QEvent.Type.Destroy:
            if HelpIconButton._active_button is self:
                HelpIconButton._active_button = None
            if hasattr(self, "_filter_installed"):
                self._remove_application_filter()
        return super().event(event)

    def eventFilter(self, watched, event) -> bool:  # noqa: N802 - Qt API
        if not self._popover.isVisible():
            return False

        event_type = event.type()
        if event_type == QEvent.Type.KeyPress:
            if event.key() == Qt.Key.Key_Escape:
                self.close_help()
                return True

        if event_type == QEvent.Type.MouseButtonPress:
            global_position = getattr(event, "globalPosition", None)
            if callable(global_position):
                point = global_position().toPoint()
                if not self._contains_global_point(point):
                    self.close_help()

        if event_type == QEvent.Type.ApplicationDeactivate:
            self.close_help()

        if event_type in {
            QEvent.Type.Move,
            QEvent.Type.Resize,
            QEvent.Type.Wheel,
        }:
            QTimer.singleShot(0, self._position_popover)

        return False

    def close_help(self) -> None:
        self._show_timer.stop()
        self._hide_timer.stop()
        self.setChecked(False)
        self._popover.set_pinned(False)
        self._popover.hide()
        self._remove_application_filter()
        if HelpIconButton._active_button is self:
            HelpIconButton._active_button = None

    def _toggle_pin(self, checked: bool) -> None:
        self._show_timer.stop()
        self._hide_timer.stop()
        self._popover.set_pinned(checked)
        if checked:
            self._show_popover()
        else:
            self._popover.hide()
            self._remove_application_filter()
            if HelpIconButton._active_button is self:
                HelpIconButton._active_button = None

    def _show_popover(self) -> None:
        if (
            not self.isVisible()
            or not self.isEnabled()
            or self.visibleRegion().isEmpty()
        ):
            return

        active = HelpIconButton._active_button
        if active is not None and active is not self:
            active.close_help()
        HelpIconButton._active_button = self
        self._popover.set_content(self._title, self._body)
        self._popover.set_pinned(self.isChecked())
        self._install_application_filter()
        self._position_popover()
        self._popover.show()
        self._popover.raise_()

    def _schedule_hide(self) -> None:
        if not self.isChecked():
            self._hide_timer.start()

    def _cancel_hide(self) -> None:
        self._hide_timer.stop()

    def _hide_if_unpinned(self) -> None:
        if not self.isChecked():
            self._popover.hide()
            self._remove_application_filter()
            if HelpIconButton._active_button is self:
                HelpIconButton._active_button = None

    def _install_application_filter(self) -> None:
        if self._filter_installed:
            return
        application = QApplication.instance()
        if application is None:
            return
        application.installEventFilter(self)
        self._filter_installed = True

    def _remove_application_filter(self) -> None:
        if not self._filter_installed:
            return
        application = QApplication.instance()
        if application is not None:
            application.removeEventFilter(self)
        self._filter_installed = False

    def _position_popover(self) -> None:
        if (
            not self.isVisible()
            or self.visibleRegion().isEmpty()
        ):
            self.close_help()
            return

        icon_top_left = self.mapToGlobal(QPoint(0, 0))
        icon_rect = QRect(icon_top_left, self.size())
        screen = QGuiApplication.screenAt(icon_rect.center()) or self.screen()
        if screen is None:
            screen = QGuiApplication.primaryScreen()
        if screen is None:
            return

        available = screen.availableGeometry()
        preferred_width = min(360, max(280, available.width() - 24))
        self._popover.setFixedWidth(preferred_width)
        self._popover.adjustSize()

        width = self._popover.width()
        height = self._popover.height()
        margin = 8

        x = icon_rect.right() - width
        y = icon_rect.bottom() + margin

        if y + height > available.bottom() + 1:
            y = icon_rect.top() - height - margin
        if y < available.top():
            y = available.top() + margin

        x = max(available.left() + margin, x)
        if x + width > available.right() + 1:
            x = available.right() - width - margin + 1

        self._popover.move(x, y)

    @staticmethod
    def _plain_text(markup: str) -> str:
        text = re.sub(r"<[^>]+>", " ", markup)
        return " ".join(unescape(text).split())

    def _contains_global_point(self, point: QPoint) -> bool:
        icon_rect = QRect(
            self.mapToGlobal(QPoint(0, 0)),
            self.size(),
        )
        return icon_rect.contains(point) or self._popover.geometry().contains(point)


class HelpLabel(QWidget):
    """Compact text label followed by a reusable question-mark help button."""

    def __init__(
        self,
        text: str,
        title: str,
        body: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("contextHelpLabel")
        self.setSizePolicy(
            QSizePolicy.Policy.Maximum,
            QSizePolicy.Policy.Preferred,
        )

        self.label = QLabel(text)
        self.label.setWordWrap(True)
        self.help_button = HelpIconButton(title, body)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        layout.addWidget(self.label)
        layout.addWidget(self.help_button)
