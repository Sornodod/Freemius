"""Точка входа приложения: MainWindow."""

import logging
import sys

from PyQt6.QtCore import (
    Qt, pyqtSignal, QPropertyAnimation, QEasingCurve, QPoint,
)
from PyQt6.QtGui import (
    QAction, QShortcut, QKeySequence,
)
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QTabWidget, QInputDialog, QLineEdit,
    QMessageBox,
)

from .config import (
    ConnectionStore, load_settings, save_settings,
    keyring_get, keyring_set, DEFAULT_LOCALHOST_NAME,
)
from .home_tab import HomeTab
from .session_tab import TerminalTab
from .sftp_tab import SftpTab
from .drawer import Drawer
from .ui_helpers import make_status_icon, ACTIVITY_FG, DEFAULT_FG


def _setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] ssh: %(message)s",
        stream=sys.stdout,
    )
    logging.getLogger("paramiko").setLevel(logging.INFO)


class MainWindow(QMainWindow):
    HOME_TAB_TITLE = "Главная"

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Freemius SSH Client")
        self.resize(1200, 760)

        self.store = ConnectionStore()
        self.settings = load_settings()
        self._tab_activity = {}
        self._editing_name = None

        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self.tabs.tabCloseRequested.connect(self._on_tab_close_requested)
        self.tabs.currentChanged.connect(self._on_tab_changed)
        self.tabs.setStyleSheet("""
            QTabWidget::pane { border: 0; background: #101418; }
            QTabBar::tab {
                background: #1b2026; color: #a6adba;
                padding: 6px 12px; margin-right: 2px;
                border-top-left-radius: 4px; border-top-right-radius: 4px;
            }
            QTabBar::tab:selected { background: #101418; color: #e5e9f0; }
        """)

        self.home = HomeTab(self.store)
        self.home.host_activated.connect(self.open_saved_host)
        self.home.host_edit.connect(self.edit_saved_host)
        self.home.host_delete.connect(self.delete_saved_host)
        self.home.new_host_clicked.connect(self.open_new_host_drawer)
        self.home.new_sftp_clicked.connect(self.open_sftp_tab)

        self.home_index = self.tabs.addTab(self.home, self.HOME_TAB_TITLE)
        self.tabs.tabBar().setTabButton(
            self.home_index, self.tabs.tabBar().ButtonPosition.RightSide, None
        )
        self.tabs.tabBar().setTabButton(
            self.home_index, self.tabs.tabBar().ButtonPosition.LeftSide, None
        )

        self.setCentralWidget(self.tabs)

        self.drawer = Drawer(self)
        self.drawer.submitted.connect(self._on_drawer_submit)

        self.home.refresh()
        self._install_shortcuts()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.drawer.setGeometry(self.rect())

    def showEvent(self, event):
        super().showEvent(event)
        self.drawer.setGeometry(self.rect())

    def _install_shortcuts(self):
        QShortcut(QKeySequence("Ctrl+T"), self, activated=self.open_new_host_drawer)
        QShortcut(QKeySequence("Ctrl+W"), self, activated=self.close_current_tab)
        QShortcut(QKeySequence("Ctrl+Tab"), self, activated=lambda: self._cycle_tab(1))
        QShortcut(QKeySequence("Ctrl+Shift+Tab"), self, activated=lambda: self._cycle_tab(-1))
        QShortcut(QKeySequence("Ctrl+PgDown"), self, activated=lambda: self._cycle_tab(1))
        QShortcut(QKeySequence("Ctrl+PgUp"), self, activated=lambda: self._cycle_tab(-1))
        QShortcut(QKeySequence("Escape"), self, activated=self._close_drawer_if_open)

    def _close_drawer_if_open(self):
        if self.drawer.isVisible():
            self.drawer.close_drawer()

    def _cycle_tab(self, delta):
        n = self.tabs.count()
        if n <= 1:
            return
        idx = (self.tabs.currentIndex() + delta) % n
        self.tabs.setCurrentIndex(idx)

    def open_new_host_drawer(self):
        self._editing_name = None
        self.drawer.open_with(save=True)

    def edit_saved_host(self, name):
        info = self.store.get(name) or {}
        password = keyring_get(name) or ""
        self._editing_name = name
        self.drawer.open_with(
            name=name,
            host=info.get("host", ""),
            port=int(info.get("port", 22)),
            user=info.get("user", ""),
            key=info.get("key", ""),
            password=password,
            save=True,
        )

    def _on_drawer_submit(self, data):
        name = data["name"]
        old_name = self._editing_name
        self._editing_name = None

        if old_name and old_name != name:
            self.store.remove(old_name)

        if data["save"]:
            self.store.add(
                name=name,
                host=data["host"],
                port=data["port"],
                user=data["user"],
                key=data["key"] or "",
            )
            if data["password"]:
                keyring_set(name, data["password"])
            else:
                from .config import keyring_delete
                keyring_delete(name)
            self.home.refresh()

        params = {
            "host": data["host"],
            "port": data["port"],
            "user": data["user"],
            "password": data["password"],
            "key": data["key"],
        }
        self._open_session(name, params)
        self.drawer.close_drawer()

    def open_saved_host(self, name):
        info = self.store.get(name)
        if not info:
            return
        params = {
            "host": info.get("host", ""),
            "port": int(info.get("port", 22)),
            "user": info.get("user", ""),
            "password": None,
            "key": info.get("key") or None,
        }
        if not params["key"]:
            password = keyring_get(name)
            if not password:
                password, ok = QInputDialog.getText(
                    self, "Пароль SSH",
                    f"Пароль для {params['user']}@{params['host']}:",
                    QLineEdit.EchoMode.Password,
                )
                if not ok:
                    return
                password = password or None
                if password:
                    keyring_set(name, password)
            params["password"] = password
        self._open_session(name, params)

    def _open_session(self, display_name, params):
        tab = TerminalTab(params)
        tab.closed.connect(self._on_tab_closed)
        tab.status_changed.connect(self._on_tab_status)
        tab.activity.connect(self._on_tab_activity)

        idx = self.tabs.addTab(tab, display_name)
        self.tabs.setTabIcon(idx, make_status_icon("connecting"))
        self._tab_activity[id(tab)] = False
        self.tabs.setCurrentIndex(idx)
        tab.start()

    def open_sftp_tab(self):
        tab = SftpTab(self.store)
        idx = self.tabs.addTab(tab, "SFTP")
        self.tabs.setTabIcon(idx, make_status_icon("connected"))
        self.tabs.setCurrentIndex(idx)

    def close_current_tab(self):
        idx = self.tabs.currentIndex()
        if idx <= self.home_index:
            return
        self._on_tab_close_requested(idx)

    def _on_tab_close_requested(self, idx):
        if idx == self.home_index:
            return
        tab = self.tabs.widget(idx)
        if tab is None:
            return
        if isinstance(tab, TerminalTab):
            try:
                tab.closed.disconnect()
                tab.status_changed.disconnect()
                tab.activity.disconnect()
            except Exception:
                pass
            if tab.ssh:
                tab.ssh.disconnect()
                tab.ssh = None
        elif isinstance(tab, SftpTab):
            for p in (tab.left, tab.right):
                if p.provider:
                    try:
                        p.provider.close()
                    except Exception:
                        pass
        self._tab_activity.pop(id(tab), None)
        self.tabs.removeTab(idx)
        tab.deleteLater()
        self.home_index = self.tabs.indexOf(self.home)

    def _on_tab_closed(self, tab):
        idx = self.tabs.indexOf(tab)
        if idx >= 0:
            self.tabs.removeTab(idx)
            tab.deleteLater()
        self._tab_activity.pop(id(tab), None)
        self.home_index = self.tabs.indexOf(self.home)

    def _on_tab_status(self, tab, state):
        idx = self.tabs.indexOf(tab)
        if idx < 0:
            return
        self.tabs.setTabIcon(idx, make_status_icon(state))

    def _on_tab_activity(self, tab):
        if tab is self.tabs.currentWidget():
            return
        self._tab_activity[id(tab)] = True
        self._update_tab_title(tab)

    def _update_tab_title(self, tab):
        idx = self.tabs.indexOf(tab)
        if idx < 0:
            return
        base = getattr(tab, "_base_title", None) or self.tabs.tabText(idx).lstrip("● ").strip()
        tab._base_title = base
        bar = self.tabs.tabBar()
        if self._tab_activity.get(id(tab)):
            self.tabs.setTabText(idx, "● " + base)
            bar.setTabTextColor(idx, ACTIVITY_FG)
        else:
            self.tabs.setTabText(idx, base)
            bar.setTabTextColor(idx, DEFAULT_FG)

    def _on_tab_changed(self, idx):
        tab = self.tabs.widget(idx) if idx >= 0 else None
        if isinstance(tab, TerminalTab):
            self._tab_activity[id(tab)] = False
            self._update_tab_title(tab)
            tab.terminal.setFocus()

    def delete_saved_host(self, name):
        if name == DEFAULT_LOCALHOST_NAME:
            QMessageBox.information(self, "Нельзя удалить", "localhost — предустановленный хост.")
            return
        if QMessageBox.question(
            self, "Удалить", f"Удалить «{name}» из сохранённых?"
        ) != QMessageBox.StandardButton.Yes:
            return
        self.store.remove(name)
        self.home.refresh()

    def closeEvent(self, event):
        for i in range(self.tabs.count()):
            tab = self.tabs.widget(i)
            if isinstance(tab, TerminalTab) and tab.ssh:
                tab.ssh.disconnect()
                tab.ssh = None
            elif isinstance(tab, SftpTab):
                for p in (tab.left, tab.right):
                    if p.provider:
                        try:
                            p.provider.close()
                        except Exception:
                            pass
        event.accept()


def main():
    _setup_logging()
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())
