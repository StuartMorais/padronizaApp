from __future__ import annotations

from PySide6.QtCore import (
    QSize,
    Qt,
)
from PySide6.QtGui import (
    QColor,
    QFontMetrics,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import (
    QCheckBox,
    QStyle,
    QStyleOptionFocusRect,
)


class ReadableCheckBox(QCheckBox):
    """
    Checkbox with a clearly drawn indicator in both light and dark themes.

    Qt's platform checkbox indicator can become nearly invisible under a dark
    application stylesheet. This widget draws its own bordered box and check
    mark while keeping normal keyboard and mouse checkbox behavior.
    """

    INDICATOR_SIZE = 19
    TEXT_GAP = 9

    def sizeHint(self) -> QSize:
        metrics = QFontMetrics(
            self.font()
        )

        return QSize(
            self.INDICATOR_SIZE
            + self.TEXT_GAP
            + metrics.horizontalAdvance(
                self.text()
            )
            + 8,
            max(
                30,
                metrics.height() + 10,
            ),
        )

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(
            QPainter.RenderHint
            .Antialiasing,
            True,
        )

        palette = self.palette()
        window_color = palette.window().color()
        dark_theme = (
            window_color.lightness() < 128
        )

        box_size = self.INDICATOR_SIZE
        box_x = 1
        box_y = (
            self.height() - box_size
        ) // 2

        if self.isChecked():
            fill = QColor("#1677e8")
            border = QColor("#58a6ff")
        else:
            fill = QColor(
                "#11171d"
                if dark_theme
                else "#ffffff"
            )
            border = QColor(
                "#91a0ae"
                if dark_theme
                else "#637487"
            )

        if not self.isEnabled():
            fill.setAlpha(120)
            border.setAlpha(120)

        painter.setPen(
            QPen(
                border,
                2,
            )
        )
        painter.setBrush(fill)
        painter.drawRoundedRect(
            box_x,
            box_y,
            box_size,
            box_size,
            4,
            4,
        )

        if self.isChecked():
            check_pen = QPen(
                QColor("#ffffff"),
                2.3,
            )
            check_pen.setCapStyle(
                Qt.PenCapStyle.RoundCap
            )
            check_pen.setJoinStyle(
                Qt.PenJoinStyle.RoundJoin
            )
            painter.setPen(check_pen)
            painter.setBrush(
                Qt.BrushStyle.NoBrush
            )

            path = QPainterPath()
            path.moveTo(
                box_x + 4.5,
                box_y + 10,
            )
            path.lineTo(
                box_x + 8.2,
                box_y + 14,
            )
            path.lineTo(
                box_x + 15.2,
                box_y + 5.5,
            )
            painter.drawPath(path)

        text_color = (
            palette.text().color()
        )

        if not self.isEnabled():
            text_color = (
                palette.placeholderText()
                .color()
            )

        painter.setPen(text_color)

        text_rect = self.rect().adjusted(
            box_size + self.TEXT_GAP,
            0,
            0,
            0,
        )

        painter.drawText(
            text_rect,
            Qt.AlignmentFlag.AlignLeft
            | Qt.AlignmentFlag.AlignVCenter,
            self.text(),
        )

        if self.hasFocus():
            option = QStyleOptionFocusRect()
            option.initFrom(self)
            option.rect = self.rect().adjusted(
                0,
                1,
                -1,
                -1,
            )
            option.backgroundColor = (
                palette.window().color()
            )
            self.style().drawPrimitive(
                QStyle.PrimitiveElement
                .PE_FrameFocusRect,
                option,
                painter,
                self,
            )
