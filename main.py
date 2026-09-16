import json
import os
import sys
from pathlib import Path

import pyte
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject, QRect
from PyQt6.QtGui import QFont, QFontDatabase, QKeyEvent, QPainter, QColor
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLineEdit, QSpinBox, QPushButton, QLabel, QComboBox,
    QFormLayout, QGroupBox, QMessageBox, QInputDialog
)

from ssh_client import SSHClient


# ---------- Хранилище подключений ----------
class ConnectionStore:
    """Сохраняет подключения в ~/.config/freemius/connections.json."""

    def __init__(self):
        self.path = Path.home() / ".config" / "freemius" / "connections.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.data = {}  # {name: {host, port, user, key}}
        self.load()

    def load(self):
        if self.path.exists():
            try:
                self.data = json.loads(self.path.read_text("utf-8"))
            except Exception as e:
                print(f"[WARN] Не удалось прочитать {self.path}: {e}")
                self.data = {}

    def save(self):
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=2, ensure_ascii=False), "utf-8")
        os.chmod(tmp, 0o600)
        tmp.replace(self.path)

    def add(self, name, host, port, user, key):
        self.data[name] = {
            "host": host, "port": port, "user": user, "key": key,
        }
        self.save()

    def remove(self, name):
        if name in self.data:
            del self.data[name]
            self.save()

    def names(self):
        return sorted(self.data.keys())

    def get(self, name):
        return self.data.get(name)


# ---------- Палитра xterm ----------
DEFAULT_FG = QColor("#d8dee9")
DEFAULT_BG = QColor("#101418")

ANSI_COLORS = [
    QColor("#000000"), QColor("#cd0000"), QColor("#00cd00"), QColor("#cdcd00"),
    QColor("#0000ee"), QColor("#cd00cd"), QColor("#00cdcd"), QColor("#e5e5e5"),
    QColor("#7f7f7f"), QColor("#ff0000"), QColor("#00ff00"), QColor("#ffff00"),
    QColor("#5c5cff"), QColor("#ff00ff"), QColor("#00ffff"), QColor("#ffffff"),
]


class Bridge(QObject):
    data_received = pyqtSignal(bytes)
    error_occurred = pyqtSignal(str)
    connection_closed = pyqtSignal()


class TerminalWidget(QWidget):
    key_pressed_bytes = pyqtSignal(bytes)
    resized = pyqtSignal(int, int)

    def __init__(self, cols=80, rows=24, parent=None):
        super().__init__(parent)
        self.cols = cols
        self.rows = rows

        self.screen = pyte.Screen(columns=cols, lines=rows)
        self.stream = pyte.ByteStream(self.screen)

        font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        font.setPointSize(11)
        self.setFont(font)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setAutoFillBackground(False)

        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.setInterval(50)
        self._resize_timer.timeout.connect(self._recompute_grid)

    def _cell_size(self):
        fm = self.fontMetrics()
        return fm.horizontalAdvance("M"), fm.height()

    def _recompute_grid(self):
        cw, ch = self._cell_size()
        if cw <= 0 or ch <= 0:
            return
        w = max(1, self.width() // cw)
        h = max(1, self.height() // ch)
        if (w, h) == (self.cols, self.rows):
            return
        self.cols, self.rows = w, h
        self.screen.resize(lines=h, columns=w)
        self.resized.emit(w, h)
        self.update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._resize_timer.start()

    def feed(self, data: bytes):
        self.stream.feed(data)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        cw, ch = self._cell_size()
        fm = self.fontMetrics()
        painter.fillRect(self.rect(), DEFAULT_BG)

        buffer = self.screen.buffer
        for y in range(self.screen.lines):
            line = buffer.get(y, {})
            for x in range(self.screen.columns):
                char = line.get(x)
                if char is None:
                    continue
                ch_ = char.data or " "
                if ch_ == " " and char.bg == "default" and char.fg == "default":
                    continue

                fg = DEFAULT_FG if char.fg == "default" else self._map_color(char.fg, char.bold)
                bg = DEFAULT_BG if char.bg == "default" else self._map_color(char.bg, False)

                x_px, y_px = x * cw, y * ch
                if bg != DEFAULT_BG:
                    painter.fillRect(QRect(x_px, y_px, cw, ch), bg)
                if ch_.strip() == "":
                    continue
                painter.setPen(fg)
                painter.drawText(x_px, y_px + fm.ascent(), ch_)

        if self.hasFocus():
            cx, cy = self.screen.cursor.x, self.screen.cursor.y
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(DEFAULT_FG)
            painter.drawRect(QRect(cx * cw, cy * ch, cw, ch))
        painter.end()

    def _map_color(self, name, bold):
        mapping = {
            "black": 0, "red": 1, "green": 2, "brown": 3, "yellow": 3,
            "blue": 4, "magenta": 5, "cyan": 6, "white": 7,
            "brightblack": 8, "brightred": 9, "brightgreen": 10,
            "brightyellow": 11, "brightblue": 12, "brightmagenta": 13,
            "brightcyan": 14, "brightwhite": 15,
        }
        if name in mapping:
            idx = mapping[name]
            if bold and idx < 8:
                idx += 8
            return ANSI_COLORS[idx]
        if isinstance(name, str) and name.startswith("color"):
            try:
                return ANSI_COLORS[int(name[5:]) % 16]
            except Exception:
                pass
        return DEFAULT_FG

    def keyPressEvent(self, event: QKeyEvent):
        key = event.key()
        text = event.text()
        mods = event.modifiers()

        mapping = {
            Qt.Key.Key_Return: b"\r", Qt.Key.Key_Enter: b"\r",
            Qt.Key.Key_Backspace: b"\x7f", Qt.Key.Key_Tab: b"\t",
            Qt.Key.Key_Escape: b"\x1b",
            Qt.Key.Key_Up: b"\x1b[A", Qt.Key.Key_Down: b"\x1b[B",
            Qt.Key.Key_Right: b"\x1b[C", Qt.Key.Key_Left: b"\x1b[D",
            Qt.Key.Key_Home: b"\x1b[H", Qt.Key.Key_End: b"\x1b[F",
            Qt.Key.Key_PageUp: b"\x1b[5~", Qt.Key.Key_PageDown: b"\x1b[6~",
            Qt.Key.Key_Insert: b"\x1b[2~", Qt.Key.Key_Delete: b"\x1b[3~",
            Qt.Key.Key_F1: b"\x1bOP", Qt.Key.Key_F2: b"\x1bOQ",
            Qt.Key.Key_F3: b"\x1bOR", Qt.Key.Key_F4: b"\x1bOS",
            Qt.Key.Key_F5: b"\x1b[15~", Qt.Key.Key_F6: b"\x1b[17~",
        }
        if key in mapping:
            self.key_pressed_bytes.emit(mapping[key])
            return

        if mods & Qt.KeyboardModifier.ControlModifier and text:
            ch = text.lower()
            if "a" <= ch <= "z":
                self.key_pressed_bytes.emit(bytes([ord(ch) - 96]))
                return

        if text:
            self.key_pressed_bytes.emit(text.encode("utf-8"))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Freemius SSH Client")
        self.resize(1000, 700)

        self.ssh = None
        self.store = ConnectionStore()

        self.bridge = Bridge()
        self.bridge.data_received.connect(self._on_data)
        self.bridge.error_occurred.connect(self._on_error)
        self.bridge.connection_closed.connect(self._on_closed)

        # --- панель подключения ---
        self.saved_combo = QComboBox()
        self.saved_combo.setMinimumWidth(220)
        self.saved_combo.currentTextChanged.connect(self._on_saved_selected)

        self.host_edit = QLineEdit("127.0.0.1")
        self.port_spin = QSpinBox()
        self.port_spin.setRange(1, 65535)
        self.port_spin.setValue(22)
        self.user_edit = QLineEdit()
        self.pass_edit = QLineEdit()
        self.pass_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.key_edit = QLineEdit()
        self.key_edit.setPlaceholderText("Путь к приватному ключу (опционально)")

        self.save_btn = QPushButton("Сохранить")
        self.delete_btn = QPushButton("Удалить")
        self.connect_btn = QPushButton("Подключиться")
        self.disconnect_btn = QPushButton("Отключиться")
        self.disconnect_btn.setEnabled(False)

        self.save_btn.clicked.connect(self.save_connection)
        self.delete_btn.clicked.connect(self.delete_connection)
        self.connect_btn.clicked.connect(self.connect_ssh)
        self.disconnect_btn.clicked.connect(self.disconnect_ssh)

        # --- форма ---
        form = QFormLayout()
        form.addRow("Сохранённые:", self.saved_combo)
        form.addRow("Хост:", self.host_edit)
        form.addRow("Порт:", self.port_spin)
        form.addRow("Пользователь:", self.user_edit)
        form.addRow("Пароль:", self.pass_edit)
        form.addRow("Ключ:", self.key_edit)

        btn_row = QHBoxLayout()
        btn_row.addWidget(self.save_btn)
        btn_row.addWidget(self.delete_btn)
        btn_row.addStretch(1)
        btn_row.addWidget(self.connect_btn)
        btn_row.addWidget(self.disconnect_btn)

        form_box = QGroupBox("Подключение SSH")
        v = QVBoxLayout()
        v.addLayout(form)
        v.addLayout(btn_row)
        form_box.setLayout(v)

        self.status_label = QLabel("Готово")

        # --- терминал ---
        self.terminal = TerminalWidget(cols=80, rows=24)
        self.terminal.key_pressed_bytes.connect(self._send_bytes)
        self.terminal.resized.connect(self._resize_pty)

        root = QWidget()
        layout = QVBoxLayout(root)
        layout.addWidget(form_box)
        layout.addWidget(self.terminal, stretch=1)
        layout.addWidget(self.status_label)
        self.setCentralWidget(root)

        self._refresh_saved_list()

    # --- сохранённые подключения ---
    def _refresh_saved_list(self, keep=None):
        self.saved_combo.blockSignals(True)
        self.saved_combo.clear()
        self.saved_combo.addItem("")  # пустой
        for name in self.store.names():
            self.saved_combo.addItem(name)
        if keep:
            idx = self.saved_combo.findText(keep)
            if idx >= 0:
                self.saved_combo.setCurrentIndex(idx)
        self.saved_combo.blockSignals(False)

    def _on_saved_selected(self, name):
        if not name:
            return
        item = self.store.get(name)
        if not item:
            return
        self.host_edit.setText(item.get("host", ""))
        self.port_spin.setValue(int(item.get("port", 22)))
        self.user_edit.setText(item.get("user", ""))
        self.key_edit.setText(item.get("key", "") or "")
        self.pass_edit.clear()
        self.status_label.setText(f"Загружено: {name}")

    def save_connection(self):
        host = self.host_edit.text().strip()
        user = self.user_edit.text().strip()
        if not host:
            QMessageBox.warning(self, "Ошибка", "Укажите хост перед сохранением")
            return

        default_name = f"{user}@{host}" if user else host
        name, ok = QInputDialog.getText(
            self, "Сохранить подключение",
            "Имя подключения:", text=default_name
        )
        if not ok or not name.strip():
            return
        name = name.strip()

        self.store.add(
            name=name,
            host=host,
            port=self.port_spin.value(),
            user=user,
            key=self.key_edit.text().strip(),
        )
        self._refresh_saved_list(keep=name)
        self.status_label.setText(f"Сохранено: {name}")

    def delete_connection(self):
        name = self.saved_combo.currentText()
        if not name:
            QMessageBox.information(self, "Удаление", "Выберите подключение из списка")
            return
        if QMessageBox.question(
            self, "Удалить подключение",
            f"Удалить «{name}»?"
        ) != QMessageBox.StandardButton.Yes:
            return
        self.store.remove(name)
        self._refresh_saved_list()
        self.status_label.setText(f"Удалено: {name}")

    # --- SSH ---
    def connect_ssh(self):
        host = self.host_edit.text().strip()
        if not host:
            QMessageBox.warning(self, "Ошибка", "Укажите хост")
            return

        self.connect_btn.setEnabled(False)
        self.status_label.setText("Подключение…")

        self.ssh = SSHClient(
            on_data=lambda d: self.bridge.data_received.emit(d),
            on_error=lambda e: self.bridge.error_occurred.emit(e),
            on_close=lambda: self.bridge.connection_closed.emit(),
        )

        try:
            self.ssh.connect(
                host=host,
                port=self.port_spin.value(),
                username=self.user_edit.text().strip(),
                password=self.pass_edit.text() or None,
                key_filename=self.key_edit.text().strip() or None,
                cols=self.terminal.cols,
                rows=self.terminal.rows,
            )
        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"[ERROR] Не удалось подключиться: {e}", flush=True)
            QMessageBox.critical(self, "Ошибка подключения", str(e))
            self.ssh = None
            self.connect_btn.setEnabled(True)
            self.status_label.setText("Ошибка подключения")
            return

        self.disconnect_btn.setEnabled(True)
        self.status_label.setText(f"Подключено к {host}")
        self.terminal.setFocus()

    def disconnect_ssh(self):
        if self.ssh:
            self.ssh.disconnect()

    def _send_bytes(self, data: bytes):
        if self.ssh:
            self.ssh.send(data)

    def _resize_pty(self, cols, rows):
        if self.ssh:
            self.ssh.resize(cols, rows)

    # --- Колбэки ---
    def _on_data(self, data: bytes):
        self.terminal.feed(data)

    def _on_error(self, msg: str):
        self.status_label.setText(f"Ошибка: {msg}")

    def _on_closed(self):
        self.status_label.setText("Соединение закрыто")
        self.connect_btn.setEnabled(True)
        self.disconnect_btn.setEnabled(False)
        self.ssh = None

    def closeEvent(self, event):
        if self.ssh:
            self.ssh.disconnect()
        event.accept()


def main():
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
