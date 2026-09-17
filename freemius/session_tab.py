"""Вкладка одной SSH-сессии."""

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QMessageBox

from .ssh_client import SSHClient
from .terminal import Bridge, TerminalWidget


class TerminalTab(QWidget):
    closed = pyqtSignal(object)
    status_changed = pyqtSignal(object, str)
    activity = pyqtSignal(object)

    def __init__(self, params, parent=None):
        super().__init__(parent)
        self.params = params
        self.ssh = None
        self.state = "disconnected"

        self.bridge = Bridge()
        self.bridge.data_received.connect(self._on_data)
        self.bridge.error_occurred.connect(self._on_error)
        self.bridge.connection_closed.connect(self._on_closed)

        self.terminal = TerminalWidget(cols=80, rows=24)
        self.terminal.key_pressed_bytes.connect(self._send_bytes)
        self.terminal.resized.connect(self._resize_pty)

        self.status_label = QLabel("Готово")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.terminal, stretch=1)
        layout.addWidget(self.status_label)

    def start(self):
        self._set_state("connecting")
        self.ssh = SSHClient(
            on_data=lambda d: self.bridge.data_received.emit(d),
            on_error=lambda e: self.bridge.error_occurred.emit(e),
            on_close=lambda: self.bridge.connection_closed.emit(),
        )
        self.status_label.setText("Подключение…")
        try:
            self.ssh.connect(
                host=self.params["host"],
                port=self.params["port"],
                username=self.params["user"],
                password=self.params.get("password") or None,
                key_filename=self.params.get("key") or None,
                cols=self.terminal.cols,
                rows=self.terminal.rows,
            )
        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"[ERROR] Не удалось подключиться: {e}", flush=True)
            QMessageBox.critical(self, "Ошибка подключения", str(e))
            self.ssh = None
            self._set_state("disconnected")
            self.status_label.setText("Ошибка подключения")
            return
        self._set_state("connected")
        self.status_label.setText(f"Подключено к {self.params['host']}")
        self.terminal.setFocus()

    def disconnect(self):
        if self.ssh:
            self.ssh.disconnect()
            self.ssh = None
        self._set_state("disconnected")

    def _set_state(self, state):
        self.state = state
        self.status_changed.emit(self, state)

    def _send_bytes(self, data: bytes):
        if self.ssh:
            self.ssh.send(data)

    def _resize_pty(self, cols, rows):
        if self.ssh:
            self.ssh.resize(cols, rows)

    def _on_data(self, data: bytes):
        self.terminal.feed(data)
        self.activity.emit(self)

    def _on_error(self, msg: str):
        self.status_label.setText(f"Ошибка: {msg}")

    def _on_closed(self):
        self.status_label.setText("Соединение закрыто")
        self.ssh = None
        self._set_state("disconnected")
