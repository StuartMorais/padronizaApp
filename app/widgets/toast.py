from __future__ import annotations

from typing import Final

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QObject,
    QPropertyAnimation,
    QTimer,
    Qt,
)
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QToolButton,
    QVBoxLayout,
    QWidget,
)


_TOAST_MARGIN: Final = 18
_TOAST_SPACING: Final = 10


class _ToastHostFilter(QObject):
    def __init__(self, host: QWidget) -> None:
        super().__init__(host)
        self.host = host

    def eventFilter(
        self,
        watched: QObject,
        event: QEvent,
    ) -> bool:
        if watched is self.host and event.type() in {
            QEvent.Type.Resize,
            QEvent.Type.Move,
            QEvent.Type.Show,
            QEvent.Type.WindowStateChange,
        }:
            QTimer.singleShot(
                0,
                lambda: _reposition_toasts(self.host),
            )
        return False


class ToastNotification(QFrame):
    def __init__(
        self,
        host: QWidget,
        *,
        title: str,
        message: str,
        kind: str,
        duration: int,
    ) -> None:
        super().__init__(host)
        self._host = host
        self._closing = False
        self.setObjectName("toastNotification")
        self.setProperty("kind", kind)
        self.setAttribute(
            Qt.WidgetAttribute.WA_StyledBackground,
            True,
        )
        self.setMinimumWidth(340)
        self.setMaximumWidth(480)

        icon_by_kind = {
            "success": "✓",
            "info": "i",
            "warning": "!",
        }
        self._icon = QLabel(
            icon_by_kind.get(kind, "i")
        )
        self._icon.setObjectName("toastIcon")
        self._icon.setAlignment(
            Qt.AlignmentFlag.AlignCenter
        )
        self._icon.setFixedSize(28, 28)

        title_label = QLabel(title)
        title_label.setObjectName("toastTitle")
        title_label.setWordWrap(True)

        message_label = QLabel(message)
        message_label.setObjectName("toastMessage")
        message_label.setWordWrap(True)
        message_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )

        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(2)
        text_layout.addWidget(title_label)
        text_layout.addWidget(message_label)

        close_button = QToolButton()
        close_button.setObjectName("toastCloseButton")
        close_button.setText("×")
        close_button.setToolTip("Fechar notificação")
        close_button.setAutoRaise(True)
        close_button.clicked.connect(self.close_toast)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 11, 10, 11)
        layout.setSpacing(10)
        layout.addWidget(
            self._icon,
            0,
            Qt.AlignmentFlag.AlignTop,
        )
        layout.addLayout(text_layout, 1)
        layout.addWidget(
            close_button,
            0,
            Qt.AlignmentFlag.AlignTop,
        )

        self._opacity = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._opacity)
        self._opacity.setOpacity(0.0)

        self._animation = QPropertyAnimation(
            self._opacity,
            b"opacity",
            self,
        )
        self._animation.setDuration(160)
        self._animation.setEasingCurve(
            QEasingCurve.Type.OutCubic
        )

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.close_toast)
        if duration > 0:
            self._timer.start(duration)

        self.adjustSize()
        self.show()
        self.raise_()
        self._fade_to(1.0)

    def _fade_to(self, target: float) -> None:
        self._animation.stop()
        self._animation.setStartValue(
            self._opacity.opacity()
        )
        self._animation.setEndValue(target)
        self._animation.start()

    def close_toast(self) -> None:
        if self._closing:
            return
        self._closing = True
        self._timer.stop()
        self._animation.stop()
        self._animation.setDuration(130)
        self._animation.setStartValue(
            self._opacity.opacity()
        )
        self._animation.setEndValue(0.0)
        self._animation.finished.connect(
            self._finish_close
        )
        self._animation.start()

    def _finish_close(self) -> None:
        active = getattr(
            self._host,
            "_padroniza_toasts",
            [],
        )
        if self in active:
            active.remove(self)
        self.hide()
        self.deleteLater()
        _reposition_toasts(self._host)


def show_toast(
    parent: QWidget,
    title: str,
    message: str,
    *,
    kind: str = "success",
    duration: int = 3600,
) -> ToastNotification:
    host = parent.window()
    active = getattr(
        host,
        "_padroniza_toasts",
        None,
    )
    if active is None:
        active = []
        setattr(
            host,
            "_padroniza_toasts",
            active,
        )

        event_filter = _ToastHostFilter(host)
        setattr(
            host,
            "_padroniza_toast_filter",
            event_filter,
        )
        host.installEventFilter(event_filter)

    toast = ToastNotification(
        host,
        title=title,
        message=message,
        kind=kind,
        duration=duration,
    )
    active.append(toast)

    while len(active) > 4:
        oldest = active[0]
        oldest.close_toast()
        break

    _reposition_toasts(host)
    return toast


def _reposition_toasts(host: QWidget) -> None:
    active = [
        toast
        for toast in getattr(
            host,
            "_padroniza_toasts",
            [],
        )
        if toast is not None
        and toast.isVisible()
        and not toast._closing
    ]
    setattr(
        host,
        "_padroniza_toasts",
        active,
    )

    bottom = host.height() - _TOAST_MARGIN
    for toast in reversed(active):
        toast.adjustSize()
        width = min(
            toast.sizeHint().width(),
            max(340, host.width() - 2 * _TOAST_MARGIN),
        )
        toast.resize(
            width,
            toast.sizeHint().height(),
        )
        x = max(
            _TOAST_MARGIN,
            host.width()
            - toast.width()
            - _TOAST_MARGIN,
        )
        y = max(
            _TOAST_MARGIN,
            bottom - toast.height(),
        )
        toast.move(x, y)
        toast.raise_()
        bottom = y - _TOAST_SPACING
