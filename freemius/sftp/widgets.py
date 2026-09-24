"""Плитка выбора хоста, страница выбора, страница файлов."""

import os

from PyQt6.QtCore import Qt, QEvent, QMimeData, pyqtSignal
from PyQt6.QtGui import QColor, QDrag
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QStackedWidget,
    QPushButton, QListWidget, QListWidgetItem, QLabel,
    QInputDialog, QMessageBox, QAbstractItemView, QLineEdit,
    QFrame, QScrollArea, QSizePolicy,
)


class FileEntry:
    __slots__ = ("name", "is_dir", "size", "mtime", "path")

    def __init__(self, name, is_dir, size, mtime, path):
        self.name = name
        self.is_dir = is_dir
        self.size = size
        self.mtime = mtime
        self.path = path


def _human_size(n):
    if n is None:
        return ""
    units = ["B", "K", "M", "G", "T", "P"]
    f = float(n)
    for u in units:
        if f < 1024:
            return f"{f:.0f}{u}" if u == "B" else f"{f:.1f}{u}"
        f /= 1024
    return f"{f:.1f}E"


def _fmt_time(ts):
    import time
    try:
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(ts))
    except Exception:
        return ""


class _HostChoiceTile(QFrame):
    def __init__(self, title, subtitle, is_local=False, parent=None):
        super().__init__(parent)
        self.setObjectName("HostChoiceTile")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(64)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setStyleSheet("""
            #HostChoiceTile {
                background-color: #1b2026;
                border: 1px solid #2b3138;
                border-radius: 8px;
            }
            #HostChoiceTile:hover {
                background-color: #232a32;
                border: 1px solid #3f4a55;
            }
        """)

        dot_color = "#88c0d0" if is_local else "#3fa64a"
        dot = QLabel()
        dot.setFixedSize(10, 10)
        dot.setStyleSheet(f"background-color: {dot_color}; border-radius: 5px;")

        self.title_label = QLabel(title)
        f = self.title_label.font()
        f.setPointSize(10)
        f.setBold(True)
        self.title_label.setFont(f)
        self.title_label.setStyleSheet("color: #e5e9f0; background: transparent;")

        self.sub_label = QLabel(subtitle)
        self.sub_label.setStyleSheet("color: #7f8a99; background: transparent;")

        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(1)
        text_col.addWidget(self.title_label)
        text_col.addWidget(self.sub_label)

        row = QHBoxLayout(self)
        row.setContentsMargins(10, 8, 10, 8)
        row.addWidget(dot, 0, Qt.AlignmentFlag.AlignTop)
        row.addSpacing(6)
        row.addLayout(text_col, 1)


class _HostPicker(QWidget):
    def __init__(self, store, on_choose, parent=None):
        super().__init__(parent)
        self.store = store
        self._on_choose = on_choose
        self.setStyleSheet("background-color: #101418;")

        header = QLabel("Выберите хост")
        f = header.font()
        f.setPointSize(12)
        f.setBold(True)
        header.setFont(f)
        header.setStyleSheet("color: #e5e9f0; padding: 6px 4px 0 4px;")

        self.tiles_host = QWidget()
        self.tiles_grid = QGridLayout(self.tiles_host)
        self.tiles_grid.setContentsMargins(4, 4, 4, 4)
        self.tiles_grid.setSpacing(8)
        self.tiles_grid.setAlignment(Qt.AlignmentFlag.AlignTop)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(self.tiles_host)
        scroll.setStyleSheet("QScrollArea { background: transparent; }")

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.addWidget(header)
        root.addWidget(scroll, 1)

        self.refresh()

    def refresh(self):
        while self.tiles_grid.count():
            item = self.tiles_grid.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        names = self.store.names()
        for i, name in enumerate(names, start=0):
            info = self.store.get(name) or {}
            user = info.get("user", "") or ""
            host = info.get("host", "")
            subtitle = f"{user}@{host}" if user else host
            tile = _HostChoiceTile(name, subtitle, is_local=False)
            tile.mouseReleaseEvent = (
                lambda ev, n=name, inf=info: self._on_choose(n, inf)
            )
            row = i // 2
            col = i % 2
            self.tiles_grid.addWidget(tile, row, col)


class _FileView(QWidget):
    def __init__(self, panel, parent=None):
        super().__init__(parent)
        self.panel = panel
        self.setStyleSheet("background-color: #101418;")

        self.host_label = QLabel("—")
        f = self.host_label.font()
        f.setBold(True)
        self.host_label.setFont(f)
        self.host_label.setStyleSheet("color: #e5e9f0; padding: 2px 4px;")

        self.change_btn = QPushButton("Сменить хост")
        self.change_btn.setStyleSheet("""
            QPushButton {
                background-color: #2b3138; color: #d8dee9; border: none;
                border-radius: 4px; padding: 4px 10px; font-size: 11px;
            }
            QPushButton:hover { background-color: #3a434e; }
        """)
        self.change_btn.clicked.connect(self._on_change)

        header = QHBoxLayout()
        header.setContentsMargins(4, 4, 4, 0)
        header.addWidget(self.host_label, 1)
        header.addWidget(self.change_btn)

        self.path_label = QLabel("—")
        self.path_label.setStyleSheet("color: #7f8a99; padding: 2px 4px;")

        self.listw = QListWidget()
        self.listw.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.listw.setAlternatingRowColors(True)
        self.listw.setStyleSheet("""
            QListWidget {
                background-color: #14181d; color: #d8dee9;
                border: 1px solid #2b3138;
            }
            QListWidget::item:selected { background: #2d6cdf; color: white; }
        """)
        self.listw.itemDoubleClicked.connect(self._on_double_click)

        self.listw.setDragEnabled(True)
        self.listw.setAcceptDrops(True)
        self.listw.setDropIndicatorShown(True)
        self.listw.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.listw.viewport().setAcceptDrops(True)
        self.listw.viewport().installEventFilter(self)
        self.listw.setDefaultDropAction(Qt.DropAction.CopyAction)
        self._dragging_entries = []

        self.up_btn = QPushButton("Назад")
        self.up_btn.setToolTip("Перейти в родительскую папку")
        self.up_btn.clicked.connect(self._go_up)
        self.refresh_btn = QPushButton("Обновить")
        self.refresh_btn.clicked.connect(self.refresh)
        self.mkdir_btn = QPushButton("Папка")
        self.mkdir_btn.clicked.connect(self._mkdir)
        self.delete_btn = QPushButton("Удалить")
        self.delete_btn.clicked.connect(self._delete)

        bottom = QHBoxLayout()
        bottom.addWidget(self.up_btn)
        bottom.addWidget(self.refresh_btn)
        bottom.addWidget(self.mkdir_btn)
        bottom.addWidget(self.delete_btn)
        bottom.addStretch(1)

        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.addLayout(header)
        root.addWidget(self.path_label)
        root.addWidget(self.listw, 1)
        root.addLayout(bottom)

    def _on_change(self):
        self.panel._return_to_picker()

    def refresh(self):
        p = self.panel.provider
        if not p:
            return
        self.listw.clear()
        try:
            entries = p.listdir()
        except Exception as e:
            first = str(e).splitlines()[0] if str(e) else "Ошибка"
            QMessageBox.warning(self, "Ошибка", first)
            return
        for e in entries:
            text = (f"{'[DIR] ' if e.is_dir else '      '}"
                    f"{e.name:<40s} {_human_size(e.size):>10s}  {_fmt_time(e.mtime)}")
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, e)
            if e.is_dir:
                item.setForeground(QColor("#88c0d0"))
            self.listw.addItem(item)
        self.path_label.setText(p.label())
        self.host_label.setText(self.panel.host_name or "—")

    def _on_double_click(self, item):
        e = item.data(Qt.ItemDataRole.UserRole)
        if not e:
            return
        if e.is_dir:
            try:
                self.panel.provider.chdir(e.path)
                self.refresh()
            except Exception as ex:
                # показываем только первую значимую строку
                msg = str(ex).splitlines()[0] if str(ex) else "Ошибка"
                QMessageBox.warning(self, "Не удалось открыть папку", msg)

    def _go_up(self):
        if not self.panel.provider:
            return
        try:
            self.panel.provider.cd_up()
            self.refresh()
        except Exception as ex:
            msg = str(ex).splitlines()[0] if str(ex) else "Ошибка"
            QMessageBox.warning(self, "Не удалось перейти выше", msg)

    def _mkdir(self):
        if not self.panel.provider:
            return
        name, ok = QInputDialog.getText(self, "Новая папка", "Имя:")
        if not ok or not name.strip():
            return
        try:
            self.panel.provider.mkdir(name.strip())
        except Exception as ex:
            msg = str(ex).splitlines()[0] if str(ex) else "Ошибка"
            QMessageBox.warning(self, "Ошибка", msg)
        self.refresh()

    def _delete(self):
        entries = self.panel.selected_entries()
        if not entries:
            return
        if QMessageBox.question(
            self, "Удалить", f"Удалить {len(entries)} объект(ов)?"
        ) != QMessageBox.StandardButton.Yes:
            return
        for e in entries:
            try:
                self.panel.provider.remove(e)
            except Exception as ex:
                msg = str(ex).splitlines()[0] if str(ex) else "Ошибка"
                QMessageBox.warning(self, "Ошибка удаления", f"{e.name}: {msg}")
        self.refresh()

    # --- drag & drop ---
    def eventFilter(self, obj, event):
        if obj is self.listw.viewport():
            et = event.type()
            if et == QEvent.Type.MouseButtonPress:
                pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
                item = self.listw.itemAt(pos)
                if item is not None:
                    e = item.data(Qt.ItemDataRole.UserRole)
                    self._dragging_entries = [e] if e else []
                else:
                    self._dragging_entries = []
            elif et == QEvent.Type.MouseMove:
                if event.buttons() & Qt.MouseButton.LeftButton and self._dragging_entries:
                    self._start_drag()
        return super().eventFilter(obj, event)

    def _start_drag(self):
        entries = self.panel.selected_entries() or self._dragging_entries
        if not entries:
            return
        mime = QMimeData()
        mime.setText("freemius-xfer")
        mime.setData("application/x-freemius-src",
                     str(id(self.panel)).encode())
        drag = QDrag(self.listw)
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.CopyAction)

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat("application/x-freemius-src"):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if event.mimeData().hasFormat("application/x-freemius-src"):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        if not event.mimeData().hasFormat("application/x-freemius-src"):
            event.ignore()
            return
        try:
            src_id = int(event.mimeData().data(
                "application/x-freemius-src").data().decode())
        except Exception:
            event.ignore()
            return
        event.acceptProposedAction()
        self.panel.request_drop_from.emit(src_id, self.panel)
