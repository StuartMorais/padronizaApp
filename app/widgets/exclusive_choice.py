from __future__ import annotations

from typing import Any

from PySide6.QtCore import QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QHBoxLayout,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.field_utils import normalize_dropdown_options


class ChoiceOptionCheckBox(QCheckBox):
    """Large, word-wrapped checkbox row used for an exclusive choice.

    It deliberately keeps a square checkbox indicator even though a
    ``QButtonGroup`` makes the options mutually exclusive. The entire row is
    clickable, so long alternatives remain obvious and easy to select.
    """

    INDICATOR_SIZE = 20
    HORIZONTAL_MARGIN = 12
    VERTICAL_MARGIN = 10
    TEXT_GAP = 10
    TEXT_SPACING = 4
    MINIMUM_HEIGHT = 46

    def __init__(
        self,
        label: str,
        value: str | None = None,
        parent=None,
    ) -> None:
        super().__init__(str(label or ""), parent)
        self._primary_text = str(label or "").strip()
        resolved_value = str(value if value is not None else label or "").strip()
        self._secondary_text = (
            resolved_value if resolved_value and resolved_value != self._primary_text else ""
        )
        self.option_value = resolved_value
        self._hovered = False

        self.setObjectName("choiceOptionCheckBox")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.setAccessibleName(self._primary_text or self.option_value)
        if self._secondary_text:
            self.setAccessibleDescription(self._secondary_text)
            self.setToolTip(self._secondary_text)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._calculated_height(max(1, width))

    def sizeHint(self) -> QSize:
        return QSize(420, self._calculated_height(420))

    def minimumSizeHint(self) -> QSize:
        return QSize(220, self._calculated_height(220))

    def hitButton(self, pos: QPoint) -> bool:
        return self.rect().contains(pos)

    def enterEvent(self, event) -> None:
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        palette = self.palette()
        outer = self.rect().adjusted(1, 1, -1, -1)
        highlight = QColor(palette.highlight().color())
        base = QColor(palette.base().color())
        window = QColor(palette.window().color())
        text_color = QColor(palette.text().color())
        muted_color = QColor(palette.placeholderText().color())
        border = QColor(palette.mid().color())

        if self.isChecked():
            background = QColor(highlight)
            background.setAlpha(38 if window.lightness() >= 128 else 54)
            border = QColor(highlight)
        elif self._hovered:
            background = QColor(highlight)
            background.setAlpha(18 if window.lightness() >= 128 else 28)
        else:
            background = base
            background.setAlpha(150 if window.lightness() >= 128 else 105)

        if not self.isEnabled():
            background.setAlpha(max(40, background.alpha() // 2))
            border.setAlpha(100)
            text_color = muted_color

        painter.setPen(QPen(border, 1.5 if self.isChecked() else 1.0))
        painter.setBrush(background)
        painter.drawRoundedRect(outer, 7, 7)

        indicator_x = self.HORIZONTAL_MARGIN
        first_line_height = QFontMetrics(self.font()).height()
        indicator_y = self.VERTICAL_MARGIN + max(
            0, (first_line_height - self.INDICATOR_SIZE) // 2
        )
        indicator = QRect(
            indicator_x,
            indicator_y,
            self.INDICATOR_SIZE,
            self.INDICATOR_SIZE,
        )

        if self.isChecked():
            fill = QColor(highlight)
            indicator_border = QColor(highlight)
        else:
            fill = QColor(base)
            indicator_border = QColor(palette.shadow().color())
            if window.lightness() < 128:
                indicator_border = QColor(palette.midlight().color())

        if not self.isEnabled():
            fill.setAlpha(100)
            indicator_border.setAlpha(100)

        painter.setPen(QPen(indicator_border, 2))
        painter.setBrush(fill)
        painter.drawRoundedRect(indicator, 4, 4)

        if self.isChecked():
            check_pen = QPen(QColor("#ffffff"), 2.3)
            check_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            check_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(check_pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            path = QPainterPath()
            path.moveTo(indicator.left() + 4.5, indicator.top() + 10.5)
            path.lineTo(indicator.left() + 8.2, indicator.top() + 14.0)
            path.lineTo(indicator.left() + 15.5, indicator.top() + 5.5)
            painter.drawPath(path)

        text_left = indicator.right() + self.TEXT_GAP
        text_width = max(
            1,
            self.width() - text_left - self.HORIZONTAL_MARGIN,
        )
        y = self.VERTICAL_MARGIN

        primary_font = QFont(self.font())
        primary_font.setWeight(
            QFont.Weight.DemiBold if self.isChecked() else QFont.Weight.Normal
        )
        primary_metrics = QFontMetrics(primary_font)
        primary_rect = primary_metrics.boundingRect(
            QRect(0, 0, text_width, 10000),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap),
            self._primary_text,
        )
        painter.setFont(primary_font)
        painter.setPen(text_color)
        painter.drawText(
            QRect(text_left, y, text_width, primary_rect.height()),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap),
            self._primary_text,
        )
        y += primary_rect.height()

        if self._secondary_text:
            y += self.TEXT_SPACING
            secondary_font = QFont(self.font())
            secondary_metrics = QFontMetrics(secondary_font)
            secondary_rect = secondary_metrics.boundingRect(
                QRect(0, 0, text_width, 10000),
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap),
                self._secondary_text,
            )
            painter.setFont(secondary_font)
            painter.setPen(muted_color if self.isEnabled() else text_color)
            painter.drawText(
                QRect(text_left, y, text_width, secondary_rect.height()),
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap),
                self._secondary_text,
            )

        if self.hasFocus():
            focus = QColor(highlight)
            focus.setAlpha(210)
            painter.setPen(QPen(focus, 2, Qt.PenStyle.DashLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(outer.adjusted(2, 2, -2, -2), 6, 6)

    def _calculated_height(self, width: int) -> int:
        text_width = max(
            40,
            width
            - (self.HORIZONTAL_MARGIN * 2)
            - self.INDICATOR_SIZE
            - self.TEXT_GAP,
        )
        primary_metrics = QFontMetrics(self.font())
        primary_height = primary_metrics.boundingRect(
            QRect(0, 0, text_width, 10000),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap),
            self._primary_text,
        ).height()
        text_height = primary_height
        if self._secondary_text:
            secondary_height = primary_metrics.boundingRect(
                QRect(0, 0, text_width, 10000),
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap),
                self._secondary_text,
            ).height()
            text_height += self.TEXT_SPACING + secondary_height
        return max(
            self.MINIMUM_HEIGHT,
            self.VERTICAL_MARGIN * 2 + text_height,
            self.VERTICAL_MARGIN * 2 + self.INDICATOR_SIZE,
        )


class ExclusiveChoiceWidget(QWidget):
    """One-value selector rendered as stacked, checkbox-like alternatives."""

    value_changed = Signal()

    def __init__(
        self,
        options: Any,
        *,
        required: bool = False,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._options = normalize_dropdown_options(options)
        self._value = ""
        self._updating = False
        self._required = bool(required)
        self._buttons: list[ChoiceOptionCheckBox] = []
        self._button_group = QButtonGroup(self)
        self._button_group.setExclusive(True)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(7)

        for option in self._options:
            button = ChoiceOptionCheckBox(
                option.get("label", ""),
                option.get("value", ""),
                self,
            )
            button.toggled.connect(
                lambda checked, current=button: self._option_toggled(current, checked)
            )
            self._button_group.addButton(button)
            self._buttons.append(button)
            root.addWidget(button)

        self.clear_button = QToolButton()
        self.clear_button.setObjectName("clearChoiceButton")
        self.clear_button.setText("Limpar seleção")
        self.clear_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clear_button.clicked.connect(lambda: self.clear(emit_signal=True))
        self.clear_button.setVisible(False)

        clear_row = QHBoxLayout()
        clear_row.setContentsMargins(0, 0, 0, 0)
        clear_row.addStretch()
        clear_row.addWidget(self.clear_button)
        root.addLayout(clear_row)

    def current_value(self) -> str:
        return self._value

    def set_value(self, value: Any, *, emit_signal: bool = False) -> None:
        resolved = str(value or "").strip()
        allowed = {str(option.get("value", "")).strip() for option in self._options}
        new_value = resolved if resolved in allowed else ""
        changed = new_value != self._value
        self._updating = True
        try:
            self._button_group.setExclusive(False)
            for button in self._buttons:
                button.setChecked(button.option_value == new_value and bool(new_value))
            self._button_group.setExclusive(True)
            self._value = new_value
            self._refresh_clear_button()
        finally:
            self._updating = False
        if changed and emit_signal:
            self.value_changed.emit()

    def clear(self, *, emit_signal: bool = False) -> None:
        self.set_value("", emit_signal=emit_signal)

    def focus_selector(self) -> None:
        selected = next((button for button in self._buttons if button.isChecked()), None)
        target = selected or (self._buttons[0] if self._buttons else None)
        if target is not None:
            target.setFocus(Qt.FocusReason.OtherFocusReason)

    def _option_toggled(self, button: ChoiceOptionCheckBox, checked: bool) -> None:
        if self._updating or not checked:
            return
        new_value = button.option_value
        if new_value == self._value:
            return
        self._value = new_value
        self._refresh_clear_button()
        self.value_changed.emit()

    def _refresh_clear_button(self) -> None:
        self.clear_button.setVisible(bool(self._value) and not self._required)
