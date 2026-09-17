"""Общие визуальные хелперы: иконки статуса, цвета."""

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QIcon, QPainter, QPixmap


DEFAULT_FG = QColor("#d8dee9")
DEFAULT_BG = QColor("#101418")
SELECT_BG = QColor("#3b4252")
ACTIVITY_FG = QColor("#e5c07b")

ANSI_COLORS = [
    QColor("#000000"), QColor("#cd0000"), QColor("#00cd00"), QColor("#cdcd00"),
    QColor("#0000ee"), QColor("#cd00cd"), QColor("#00cdcd"), QColor("#e5e5e5"),
    QColor("#7f7f7f"), QColor("#ff0000"), QColor("#00ff00"), QColor("#ffff00"),
    QColor("#5c5cff"), QColor("#ff00ff"), QColor("#00ffff"), QColor("#ffffff"),
]

STATUS_COLORS = {
    "connecting": QColor("#d7a13c"),
    "connected": QColor("#3fa64a"),
    "disconnected": QColor("#c74242"),
}


def make_status_icon(state: str) -> QIcon:
    px = QPixmap(12, 12)
    px.fill(Qt.GlobalColor.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(STATUS_COLORS.get(state, STATUS_COLORS["disconnected"]))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(1, 1, 10, 10)
    p.end()
    return QIcon(px)
