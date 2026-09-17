"""Панель файлового менеджера: локальная ФС или удалённая по SFTP."""

import os
import stat as stat_module
import time

import paramiko
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QComboBox, QPushButton,
    QListWidget, QListWidgetItem, QLabel, QInputDialog,
    QMessageBox, QAbstractItemView, QLineEdit,
)


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


# ---------- SFTP-провайдер ----------
class SFTPProvider:
    kind = "sftp"

    def __init__(self, host, port, user, password=None, key=None):
        self.ssh = paramiko.SSHClient()
        self.ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        # См. ssh_client.py — та же логика, чтобы не ловить
        # "Too many authentication failures".
        kwargs = dict(hostname=host, port=port, username=user, timeout=10)
        if key:
            kwargs["key_filename"] = key
            kwargs["password"] = password or None
            kwargs["look_for_keys"] = False
            kwargs["allow_agent"] = False
        elif password:
            kwargs["password"] = password
            kwargs["look_for_keys"] = False
            kwargs["allow_agent"] = False
        else:
            kwargs["look_for_keys"] = True
            kwargs["allow_agent"] = True

        self.ssh.connect(**kwargs)
        self.sftp = self.ssh.open_sftp()
        try:
            self.cwd = self.sftp.normalize(".")
        except Exception:
            self.cwd = "."

    def listdir(self):
        entries = []
        for attr in self.sftp.listdir_attr(self.cwd):
            is_dir = stat_module.S_ISDIR(attr.st_mode or 0)
            full = self.cwd.rstrip("/") + "/" + attr.filename
            entries.append(FileEntry(
                attr.filename, is_dir, attr.st_size, attr.st_mtime, full
            ))
        entries.sort(key=lambda e: (not e.is_dir, e.name.lower()))
        return entries

    def chdir(self, path):
        try:
            self.cwd = self.sftp.normalize(path)
        except Exception:
            self.cwd = path

    def cd_up(self):
        parent = self.cwd.rstrip("/").rsplit("/", 1)[0] or "/"
        self.chdir(parent)

    def mkdir(self, name):
        self.sftp.mkdir(self.cwd.rstrip("/") + "/" + name)

    def remove(self, entry: FileEntry):
        if entry.is_dir:
            self.sftp.rmdir(entry.path)
        else:
            self.sftp.remove(entry.path)

    def open_read(self, path):
        return self.sftp.open(path, "rb")

    def open_write(self, path):
        return self.sftp.open(path, "wb")

    def close(self):
        try:
            self.sftp.close()
        except Exception:
            pass
        try:
            self.ssh.close()
        except Exception:
            pass

    def label(self):
        return f"SFTP: {self.cwd}"


# ---------- Виджет панели ----------
class FilePanel(QWidget):
    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        self.provider = None

        self.host_combo = QComboBox()
        self.host_combo.addItem("Local (этот компьютер)", "__local__")
        for name in self.store.names():
            self.host_combo.addItem(name, name)

        self.connect_btn = QPushButton("Подключить")
        self.connect_btn.clicked.connect(self._on_connect_clicked)

        top = QHBoxLayout()
        top.addWidget(self.host_combo, 1)
        top.addWidget(self.connect_btn)

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
        root.addLayout(top)
        root.addWidget(self.path_label)
        root.addWidget(self.listw, 1)
        root.addLayout(bottom)

        self._enable_actions(False)

    # --- подключение ---
    def _on_connect_clicked(self):
        key = self.host_combo.currentData()
        if key == "__local__":
            self._connect_local()
        else:
            info = self.store.get(key) or {}
            self._connect_sftp(key, info)

    def _connect_local(self):
        if self.provider:
            self.provider.close()
        self.provider = LocalProvider()
        self._enable_actions(True)
        self.refresh()

    def _connect_sftp(self, name, info):
        host = info.get("host", "")
        port = int(info.get("port", 22))
        user = info.get("user", "")
        key = info.get("key") or None

        password = None
        if not key:
            password, ok = QInputDialog.getText(
                self, "Пароль SFTP",
                f"Пароль для {user}@{host}:",
                QLineEdit.EchoMode.Password,
            )
            if not ok:
                return

        if self.provider:
            self.provider.close()
            self.provider = None

        try:
            self.provider = SFTPProvider(
                host=host, port=port, user=user,
                password=password, key=key,
            )
        except Exception as e:
            QMessageBox.critical(self, "Ошибка SFTP", str(e))
            self.provider = None
            self._enable_actions(False)
            return

        self._enable_actions(True)
        self.refresh()

    def _enable_actions(self, on):
        for w in (self.up_btn, self.refresh_btn, self.mkdir_btn, self.delete_btn):
            w.setEnabled(on)
        self.listw.setEnabled(on)

    # --- работа со списком ---
    def refresh(self):
        if not self.provider:
            return
        self.listw.clear()
        try:
            entries = self.provider.listdir()
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

        self.path_label.setText(self.provider.label())

    def _selected_entries(self):
        out = []
        for item in self.listw.selectedItems():
            e = item.data(Qt.ItemDataRole.UserRole)
            if e:
                out.append(e)
        return out

    def _on_double_click(self, item):
        e = item.data(Qt.ItemDataRole.UserRole)
        if not e:
            return
        if e.is_dir:
            self.provider.chdir(e.path)
            self.refresh()

    def _go_up(self):
        if not self.provider:
            return
        self.provider.cd_up()
        self.refresh()

    def _mkdir(self):
        if not self.provider:
            return
        name, ok = QInputDialog.getText(self, "Новая папка", "Имя:")
        if not ok or not name.strip():
            return
        try:
            self.provider.mkdir(name.strip())
        except Exception as ex:
            QMessageBox.critical(self, "Ошибка", str(ex))
        self.refresh()

    def _delete(self):
        entries = self._selected_entries()
        if not entries:
            return
        if QMessageBox.question(
            self, "Удалить",
            f"Удалить {len(entries)} объект(ов)?"
        ) != QMessageBox.StandardButton.Yes:
            return
        for e in entries:
            try:
                self.provider.remove(e)
            except Exception as ex:
                QMessageBox.critical(self, "Ошибка удаления", f"{e.name}: {ex}")
        self.refresh()

    def selected_entry(self):
        items = self.listw.selectedItems()
        if not items:
            return None
        return items[0].data(Qt.ItemDataRole.UserRole)

    def other_cwd(self):
        return self.provider.cwd if self.provider else ""


def transfer_file(src_panel: FilePanel, dst_panel: FilePanel, entry: FileEntry):
    """Скопировать entry из src_panel в cwd dst_panel."""
    if not src_panel.provider or not dst_panel.provider:
        return False
    dst_path = dst_panel.provider.cwd.rstrip("/") + "/" + entry.name
    try:
        with src_panel.provider.open_read(entry.path) as fin, \
             dst_panel.provider.open_write(dst_path) as fout:
            while True:
                chunk = fin.read(65536)
                if not chunk:
                    break
                fout.write(chunk)
    except Exception as e:
        QMessageBox.critical(src_panel, "Ошибка передачи", str(e))
        return False
    return True
