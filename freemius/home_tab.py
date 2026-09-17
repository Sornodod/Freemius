"""Домашняя вкладка: плитки сохранённых хостов."""

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QPushButton,
    QLabel, QMenu, QScrollArea, QFrame, QSizePolicy,
)

from .config import DEFAULT_LOCALHOST_NAME
from .themes import THEMES
from .ui_helpers import make_status_icon


class HostTile(QFrame):
    clicked = pyqtSignal(str)
    edit_requested = pyqtSignal(str)
    delete_requested = pyqtSignal(str)

    def __init__(self, name, info, parent=None):
        super().__init__(parent)
        self.name = name
        self.info = info
        self.setObjectName("HostTile")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(72)
        self.setMinimumWidth(220)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setStyleSheet("""
            #HostTile {
                background-color: #1b2026;
                border: 1px solid #2b3138;
                border-radius: 8px;
            }
            #HostTile:hover {
                background-color: #232a32;
                border: 1px solid #3f4a55;
            }
        """)

        user = info.get("user", "") or ""
        host = info.get("host", "")
        subtitle = f"{user}@{host}" if user else host

        self.title_label = QLabel(name)
        f = self.title_label.font()
        f.setPointSize(11)
        f.setBold(True)
        self.title_label.setFont(f)
        self.title_label.setStyleSheet("color: #e5e9f0; background: transparent;")

        self.sub_label = QLabel(subtitle)
        self.sub_label.setStyleSheet("color: #7f8a99; background: transparent;")

        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(2)
        text_col.addWidget(self.title_label)
        text_col.addWidget(self.sub_label)

        dot = QLabel()
        dot.setPixmap(make_status_icon("disconnected").pixmap(12, 12))

        row = QHBoxLayout(self)
        row.setContentsMargins(14, 12, 14, 12)
        row.addWidget(dot, 0, Qt.AlignmentFlag.AlignTop)
        row.addLayout(text_col, 1)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.name)
        elif event.button() == Qt.MouseButton.RightButton:
            self._context_menu(event.globalPosition().toPoint())

    def _context_menu(self, global_pos):
        menu = QMenu(self)
        act_open = QAction("Открыть", self)
        act_open.triggered.connect(lambda: self.clicked.emit(self.name))
        act_edit = QAction("Редактировать", self)
        act_edit.triggered.connect(lambda: self.edit_requested.emit(self.name))
        act_del = QAction("Удалить", self)
        act_del.setEnabled(self.name != DEFAULT_LOCALHOST_NAME)
        act_del.triggered.connect(lambda: self.delete_requested.emit(self.name))
        menu.addAction(act_open)
        menu.addAction(act_edit)
        menu.addSeparator()
        menu.addAction(act_del)
        menu.exec(global_pos)


class HomeTab(QWidget):
    host_activated = pyqtSignal(str)
    host_edit = pyqtSignal(str)
    host_delete = pyqtSignal(str)
    new_host_clicked = pyqtSignal()
    new_sftp_clicked = pyqtSignal()
    theme_change_requested = pyqtSignal(str)

    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        self.setStyleSheet("background-color: #101418;")

        new_btn = QPushButton("+ Новый хост")
        new_btn.setStyleSheet("""
            QPushButton {
                background-color: #2d6cdf; color: white; border: none;
                border-radius: 6px; padding: 8px 16px; font-weight: bold;
            }
            QPushButton:hover { background-color: #3a7ce8; }
            QPushButton:pressed { background-color: #245bbd; }
        """)
        new_btn.clicked.connect(self.new_host_clicked.emit)

        sftp_btn = QPushButton("SFTP сессия")
        sftp_btn.setStyleSheet("""
            QPushButton {
                background-color: #2b3138; color: #d8dee9; border: none;
                border-radius: 6px; padding: 8px 16px;
            }
            QPushButton:hover { background-color: #3a434e; }
        """)
        sftp_btn.clicked.connect(self.new_sftp_clicked.emit)

        self.theme_btn = QPushButton("🎨 Тема")
        self.theme_btn.setStyleSheet("""
            QPushButton {
                background-color: #2b3138; color: #d8dee9; border: none;
                border-radius: 6px; padding: 8px 16px;
            }
            QPushButton:hover { background-color: #3a434e; }
        """)
        self.theme_btn.clicked.connect(self._show_theme_menu)

        top = QHBoxLayout()
        top.setContentsMargins(24, 20, 24, 0)
        top.addWidget(new_btn)
        top.addWidget(sftp_btn)
        top.addWidget(self.theme_btn)
        top.addStretch(1)

        self.tiles_host = QWidget()
        self.tiles_grid = QGridLayout(self.tiles_host)
        self.tiles_grid.setContentsMargins(24, 20, 24, 24)
        self.tiles_grid.setSpacing(14)
        self.tiles_grid.setAlignment(
            Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft
        )

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(self.tiles_host)
        scroll.setStyleSheet("QScrollArea { background: transparent; }")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addLayout(top)
        root.addWidget(scroll, 1)

    def _show_theme_menu(self):
        menu = QMenu(self)
        for key, t in THEMES.items():
            act = QAction(t["name"], self)
            act.triggered.connect(
                lambda checked=False, k=key: self.theme_change_requested.emit(k)
            )
            menu.addAction(act)
        menu.exec(self.theme_btn.mapToGlobal(self.theme_btn.rect().bottomLeft()))

    def refresh(self):
        while self.tiles_grid.count():
            item = self.tiles_grid.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        names = self.store.names()
        if not names:
            empty = QLabel("Нет сохранённых хостов.\nНажмите «+ Новый хост» сверху.")
            empty.setStyleSheet("color: #6b7784; padding: 40px; font-size: 13px;")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.tiles_grid.addWidget(empty, 0, 0)
            return

        cols = self._column_count()
        for i, name in enumerate(names):
            info = self.store.get(name)
            tile = HostTile(name, info)
            tile.clicked.connect(self.host_activated.emit)
            tile.edit_requested.connect(self.host_edit.emit)
            tile.delete_requested.connect(self.host_delete.emit)
            self.tiles_grid.addWidget(tile, i // cols, i % cols)
        for c in range(cols):
            self.tiles_grid.setColumnStretch(c, 1)

    def _column_count(self):
        w = self.width() or 1200
        return max(1, (w - 48) // 260)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        new_cols = self._column_count()
        if getattr(self, "_last_cols", None) != new_cols:
            self._last_cols = new_cols
            self.refresh()
