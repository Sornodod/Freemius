"""Выезжающая справа панель (drawer) + выбор ключа."""

from pathlib import Path

from PyQt6.QtCore import (
    Qt, pyqtSignal, QPropertyAnimation, QEasingCurve, QPoint,
)
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, QSpinBox,
    QPushButton, QLabel, QFormLayout, QFrame, QCheckBox,
    QFileDialog, QToolButton, QMenu, QMessageBox,
)


def _list_ssh_keys():
    ssh_dir = Path.home() / ".ssh"
    if not ssh_dir.is_dir():
        return []
    skip = {"known_hosts", "known_hosts.old", "config", "authorized_keys"}
    keys = []
    for p in sorted(ssh_dir.iterdir()):
        if not p.is_file():
            continue
        if p.name in skip:
            continue
        if p.suffix == ".pub":
            continue
        if p.name.endswith(".old"):
            continue
        keys.append(str(p))
    return keys


class KeyPickerButton(QToolButton):
    key_selected = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setText("…")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet("""
            QToolButton {
                background-color: #2b3138; color: #d8dee9;
                border: none; border-radius: 4px; padding: 2px 8px;
            }
            QToolButton:hover { background-color: #3a434e; }
        """)
        self.clicked.connect(self._show_menu)

    def _show_menu(self):
        menu = QMenu(self)
        keys = _list_ssh_keys()
        if keys:
            for k in keys:
                act = QAction(Path(k).name, self)
                act.setToolTip(k)
                act.triggered.connect(
                    lambda checked=False, path=k: self.key_selected.emit(path)
                )
                menu.addAction(act)
        else:
            act = QAction("(нет ключей в ~/.ssh)", self)
            act.setEnabled(False)
            menu.addAction(act)
        menu.addSeparator()
        act_other = QAction("Другой файл…", self)
        act_other.triggered.connect(self._pick_file)
        menu.addAction(act_other)
        menu.exec(self.mapToGlobal(self.rect().bottomLeft()))

    def _pick_file(self):
        start = str(Path.home() / ".ssh")
        path, _ = QFileDialog.getOpenFileName(
            self, "Выбрать ключ", start, "Все файлы (*)"
        )
        if path:
            self.key_selected.emit(path)


class Drawer(QWidget):
    submitted = pyqtSignal(dict)

    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet("background-color: rgba(0,0,0,140);")
        self.hide()

        width = 400

        self.panel = QFrame(self)
        self.panel.setObjectName("DrawerPanel")
        self.panel.setStyleSheet("""
            #DrawerPanel {
                background-color: #1b2026;
                border-left: 1px solid #2b3138;
            }
        """)
        self.panel.setFixedWidth(width)

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Например: Домашний сервер")
        self.host_edit = QLineEdit()
        self.host_edit.setPlaceholderText("192.168.1.10 или example.com")
        self.port_spin = QSpinBox()
        self.port_spin.setRange(1, 65535)
        self.port_spin.setValue(22)
        self.user_edit = QLineEdit()
        self.pass_edit = QLineEdit()
        self.pass_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.pass_edit.setPlaceholderText("Пароль SSH")

        self.key_edit = QLineEdit()
        self.key_edit.setPlaceholderText("~/.ssh/id_ed25519 (опционально)")
        self.key_btn = KeyPickerButton()
        self.key_btn.key_selected.connect(self.key_edit.setText)

        key_row = QHBoxLayout()
        key_row.setContentsMargins(0, 0, 0, 0)
        key_row.setSpacing(4)
        key_row.addWidget(self.key_edit, 1)
        key_row.addWidget(self.key_btn)

        self.save_check = QCheckBox("Сохранить в список")
        self.save_check.setChecked(True)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.addRow("Имя:", self.name_edit)
        form.addRow("Хост:", self.host_edit)
        form.addRow("Порт:", self.port_spin)
        form.addRow("Пользователь:", self.user_edit)
        form.addRow("Пароль:", self.pass_edit)
        form.addRow("Ключ:", key_row)

        title = QLabel("Новое подключение")
        f = title.font()
        f.setPointSize(14)
        f.setBold(True)
        title.setFont(f)
        title.setStyleSheet("color: #e5e9f0;")

        hint = QLabel("Пароль хранится в системном keyring.")
        hint.setStyleSheet("color: #7f8a99; font-size: 11px;")

        btn_ok = QPushButton("Подключиться")
        btn_ok.setStyleSheet("""
            QPushButton {
                background-color: #2d6cdf; color: white; border: none;
                border-radius: 6px; padding: 8px 12px; font-weight: bold;
            }
            QPushButton:hover { background-color: #3a7ce8; }
        """)
        btn_cancel = QPushButton("Отмена")
        btn_cancel.setStyleSheet("""
            QPushButton {
                background-color: #2b3138; color: #d8dee9; border: none;
                border-radius: 6px; padding: 8px 12px;
            }
            QPushButton:hover { background-color: #3a434e; }
        """)
        btn_ok.clicked.connect(self._on_submit)
        btn_cancel.clicked.connect(self._on_cancel)

        btns = QHBoxLayout()
        btns.addWidget(btn_cancel)
        btns.addStretch(1)
        btns.addWidget(btn_ok)

        pv = QVBoxLayout(self.panel)
        pv.setContentsMargins(20, 20, 20, 20)
        pv.setSpacing(12)
        pv.addWidget(title)
        pv.addLayout(form)
        pv.addWidget(hint)
        pv.addWidget(self.save_check)
        pv.addStretch(1)
        pv.addLayout(btns)

        self._width = width
        self._anim = QPropertyAnimation(self.panel, b"pos", self)
        self._anim.setDuration(180)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.panel.resize(self._width, self.height())
        if self.isVisible() and not self._anim.state():
            self.panel.move(self.width() - self._width, 0)

    def open_with(self, name="", host="", port=22, user="", key="",
                  password="", save=True):
        self.name_edit.setText(name)
        self.host_edit.setText(host)
        self.port_spin.setValue(port)
        self.user_edit.setText(user)
        self.pass_edit.setEchoMode(QLineEdit.EchoMode.Normal)
        self.pass_edit.setText(password or "")
        self.key_edit.setText(key or "")
        self.save_check.setChecked(save)
        self.show()
        self.raise_()
        self.panel.resize(self._width, self.height())
        self.panel.move(self.width(), 0)
        self._anim.stop()
        self._anim.setStartValue(QPoint(self.width(), 0))
        self._anim.setEndValue(QPoint(self.width() - self._width, 0))
        self._anim.start()
        self.host_edit.setFocus()

    def close_drawer(self):
        self._anim.stop()
        self._anim.setStartValue(self.panel.pos())
        self._anim.setEndValue(QPoint(self.width(), 0))
        self._anim.finished.connect(self._after_close)
        self._anim.start()

    def _after_close(self):
        try:
            self._anim.finished.disconnect(self._after_close)
        except Exception:
            pass
        self.hide()

    def mousePressEvent(self, event):
        if not self.panel.geometry().contains(event.position().toPoint()):
            self._on_cancel()

    def _on_submit(self):
        name = self.name_edit.text().strip()
        host = self.host_edit.text().strip()
        if not host:
            QMessageBox.warning(self, "Ошибка", "Укажите хост")
            return
        if not name:
            user = self.user_edit.text().strip()
            name = f"{user}@{host}" if user else host
        self.submitted.emit({
            "name": name,
            "host": host,
            "port": self.port_spin.value(),
            "user": self.user_edit.text().strip(),
            "password": self.pass_edit.text() or None,
            "key": self.key_edit.text().strip() or None,
            "save": self.save_check.isChecked(),
        })

    def _on_cancel(self):
        self.close_drawer()
