"""Панель файлового менеджера: сначала выбор хоста плитками, потом файлы."""

import os
import stat as stat_module
import time

from PyQt6.QtCore import Qt, QEvent, QMimeData, pyqtSignal
from PyQt6.QtGui import QColor, QDrag
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QStackedWidget,
    QPushButton, QListWidget, QListWidgetItem, QLabel,
    QInputDialog, QMessageBox, QAbstractItemView, QLineEdit,
    QFrame, QScrollArea, QSizePolicy,
)

from scp_provider import SCPProvider


KEYRING_SERVICE = "freemius"


def _keyring_get(name):
    try:
        import keyring
        return keyring.get_password(KEYRING_SERVICE, name)
    except Exception:
        return None


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
    try:
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(ts))
    except Exception:
        return ""


class FileEntry:
    __slots__ = ("name", "is_dir", "size", "mtime", "path")

    def __init__(self, name, is_dir, size, mtime, path):
        self.name = name
        self.is_dir = is_dir
        self.size = size
        self.mtime = mtime
        self.path = path


# ---------- Локальный провайдер ----------
class LocalProvider:
    kind = "local"

    def __init__(self):
        self.cwd = os.path.expanduser("~")

    def listdir(self):
        entries = []
        try:
            for name in os.listdir(self.cwd):
                full = os.path.join(self.cwd, name)
                try:
                    st = os.lstat(full)
                    is_dir = stat_module.S_ISDIR(st.st_mode)
                    entries.append(FileEntry(name, is_dir, st.st_size, st.st_mtime, full))
                except OSError:
                    continue
        except OSError as e:
            raise RuntimeError(str(e))
        entries.sort(key=lambda e: (not e.is_dir, e.name.lower()))
        return entries

    def chdir(self, path):
        self.cwd = os.path.abspath(path)

    def cd_up(self):
        self.cwd = os.path.dirname(self.cwd.rstrip("/")) or "/"

    def mkdir(self, name):
        os.mkdir(os.path.join(self.cwd, name))

    def remove(self, entry: FileEntry):
        if entry.is_dir:
            os.rmdir(entry.path)
        else:
            os.remove(entry.path)

    def open_read(self, path):
        return open(path, "rb")

    def open_write(self, path):
        return open(path, "wb")

    def close(self):
        pass

    def label(self):
        return f"Local: {self.cwd}"


# ---------- Плитка хоста ----------
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


# ---------- Страница выбора хоста ----------
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


# ---------- Страница файлов ----------
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

        # --- drag & drop ---
        self.listw.setDragEnabled(True)
        self.listw.setAcceptDrops(True)
        self.listw.setDropIndicatorShown(True)
        self.listw.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.listw.viewport().setAcceptDrops(True)
        self.listw.viewport().installEventFilter(self)
        self.listw.setDefaultDropAction(Qt.DropAction.CopyAction)
        self._dragging_entries = []

        self.up_btn = QPushButton("..")
        self.up_btn.setFixedWidth(40)
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
            QMessageBox.critical(self, "Ошибка", str(e))
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
                QMessageBox.critical(self, "Ошибка", str(ex))

    def _go_up(self):
        if not self.panel.provider:
            return
        self.panel.provider.cd_up()
        self.refresh()

    def _mkdir(self):
        if not self.panel.provider:
            return
        name, ok = QInputDialog.getText(self, "Новая папка", "Имя:")
        if not ok or not name.strip():
            return
        try:
            self.panel.provider.mkdir(name.strip())
        except Exception as ex:
            QMessageBox.critical(self, "Ошибка", str(ex))
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
                QMessageBox.critical(self, "Ошибка удаления", f"{e.name}: {ex}")
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


# ---------- Публичный виджет ----------
class FilePanel(QWidget):
    """Стек: выбор хоста плитками → файловый менеджер."""

    request_drop_from = pyqtSignal(int, object)  # (src_panel_id, dst_panel)

    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        self.provider = None
        self.host_name = None

        self.stack = QStackedWidget(self)
        self.picker = _HostPicker(store, self._on_host_chosen)
        self.fileview = _FileView(self)
        self.stack.addWidget(self.picker)
        self.stack.addWidget(self.fileview)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self.stack)

        self.stack.setCurrentIndex(0)

    def _on_host_chosen(self, key, info):
        if self.provider:
            try:
                self.provider.close()
            except Exception:
                pass
            self.provider = None

        if key == "__local__":
            self.provider = LocalProvider()
            self.host_name = "Local"
        else:
            info = info or {}
            host = info.get("host", "")
            port = int(info.get("port", 22))
            user = info.get("user", "")
            key_file = info.get("key") or None

            password = _keyring_get(key) if not key_file else None
            if not key_file and not password:
                password, ok = QInputDialog.getText(
                    self, "Пароль SFTP",
                    f"Пароль для {user}@{host}:",
                    QLineEdit.EchoMode.Password,
                )
                if not ok:
                    return
                password = password or None

            try:
                self.provider = SCPProvider(
                    host=host, port=port, user=user,
                    password=password, key=key_file,
                )
                self.host_name = key
            except Exception as e:
                QMessageBox.critical(self, "Ошибка SCP", str(e))
                self.provider = None
                return

        self.fileview.refresh()
        self.stack.setCurrentIndex(1)

    def _return_to_picker(self):
        if self.provider:
            try:
                self.provider.close()
            except Exception:
                pass
            self.provider = None
        self.host_name = None
        self.picker.refresh()
        self.stack.setCurrentIndex(0)

    def refresh(self):
        if self.stack.currentIndex() == 1:
            self.fileview.refresh()
        else:
            self.picker.refresh()

    def selected_entries(self):
        return [
            it.data(Qt.ItemDataRole.UserRole)
            for it in self.fileview.listw.selectedItems()
            if it.data(Qt.ItemDataRole.UserRole)
        ]

    def selected_entry(self):
        items = self.fileview.listw.selectedItems()
        if not items:
            return None
        return items[0].data(Qt.ItemDataRole.UserRole)

    def other_cwd(self):
        return self.provider.cwd if self.provider else ""


# ---------- Передача файлов ----------
def transfer_file(src_panel, dst_panel, entry):
    """Скопировать entry из src_panel в cwd dst_panel. Через /tmp."""
    import shutil
    import tempfile

    if not src_panel.provider or not dst_panel.provider:
        return False

    dst_dir = getattr(dst_panel.provider, "cwd", None)
    if dst_dir is None:
        return False
    dst_path = dst_dir.rstrip("/") + "/" + entry.name

    tmpdir = tempfile.mkdtemp(prefix="freemius_xfer_")
    local_tmp = os.path.join(tmpdir, entry.name)
    try:
        src = src_panel.provider
        if src.kind == "local":
            shutil.copy2(entry.path, local_tmp)
        else:
            src.get_file(entry.path, local_tmp)

        dst = dst_panel.provider
        if dst.kind == "local":
            shutil.copy2(local_tmp, dst_path)
        else:
            dst.put_file(local_tmp, dst_path)
    except Exception as e:
        QMessageBox.critical(src_panel, "Ошибка передачи", str(e))
        return False
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    return True
