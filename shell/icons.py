"""Local SVG icons, with no network requests or icon-font dependency."""
from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

ASSET_ROOT = Path(__file__).resolve().parent.parent / "assets"


@lru_cache(maxsize=96)
def icon(name: str, color: str = "#64748B", size: int = 24) -> QIcon:
    svg = (ASSET_ROOT / "icons" / f"{name}.svg").read_text(encoding="utf-8")
    renderer = QSvgRenderer(QByteArray(svg.replace("currentColor", color).encode("utf-8")))
    if not renderer.isValid():
        raise ValueError(f"Invalid icon: {name}")
    pixmap = QPixmap(size * 2, size * 2)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    pixmap.setDevicePixelRatio(2)
    return QIcon(pixmap)
