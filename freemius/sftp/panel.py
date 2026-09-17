"""Публичный виджет FilePanel: стек (выбор хоста → файлы)."""

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QStackedWidget, QInputDialog,
    QMessageBox, QLineEdit,
)

from ..config import keyring_get
from .providers import LocalProvider, SCPProvider
from .widgets import _HostPicker, _FileView


class FilePanel(QWidget):
    """Стек: выбор хоста плитками → файловый менеджер."""

    request_drop_from = pyqtSignal(int, object)

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

            password = keyring_get(key) if not key_file else None
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
