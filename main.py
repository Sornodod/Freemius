import json
import os
import sys
from pathlib import Path

import pyte
from PyQt6.QtCore import (
    Qt, QTimer, pyqtSignal, QObject, QRect, QPropertyAnimation,
    QEasingCurve, QPoint, QSize,
)
from PyQt6.QtGui import (
    QFont, QFontDatabase, QKeyEvent, QPainter, QColor, QAction,
    QShortcut, QKeySequence, QIcon, QPixmap,
)
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QGridLayout, QLineEdit, QSpinBox, QPushButton, QLabel,
    QFormLayout, QMessageBox, QTabWidget,
    QMenu, QScrollArea, QFrame, QCheckBox, QSizePolicy,
)

from ssh_client import SSHClient


# ---------- Хранилище подключений ----------
class ConnectionStore:
    def __init__(self):
        self.path = Path.home() / ".config" / "freemius" / "connections.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.data = {}
        self.load()

    def load(self):
        if not self.path.exists():
            self.data = {}
            return
        try:
            raw = json.loads(self.path.read_text("utf-8"))
        except Exception as e:
            print(f"[WARN] Не удалось прочитать {self.path}: {e}")
            self.data = {}
            return

        if isinstance(raw, dict):
            self.data = raw
        elif isinstance(raw, list):
            migrated = {}
            for item in raw:
                if not isinstance(item, dict):
                    continue
                host = item.get("host", "")
                user = item.get("user", "")
                name = f"{user}@{host}" if user else host
                if not name:
                    continue
                migrated[name] = {
                    "host": host,
                    "port": int(item.get("port", 22)),
                    "user": user,
                    "key": item.get("key") or item.get("key_path") or "",
                }
            self.data = migrated
            if migrated:
                self.save()
        else:
            self.data = {}

    def save(self):
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=2, ensure_ascii=False), "utf-8")
        os.chmod(tmp, 0o600)
        tmp.replace(self.path)

    def add(self, name, host, port, user, key):
        self.data[name] = {"host": host, "port": port, "user": user, "key": key}
        self.save()

    def remove(self, name):
        if name in self.data:
            del self.data[name]
            self.save()

    def names(self):
        return sorted(self.data.keys())

    def get(self, name):
        return self.data.get(name)


# ---------- Палитра ----------
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


class Bridge(QObject):
    data_received = pyqtSignal(bytes)
    error_occurred = pyqtSignal(str)
    connection_closed = pyqtSignal()


# ---------- Терминал ----------
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
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)

        self._sel_start = None
        self._sel_end = None

        self._cursor_visible = True
        self._blink_timer = QTimer(self)
        self._blink_timer.setInterval(500)
        self._blink_timer.timeout.connect(self._blink)
        self._blink_timer.start()

        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.setInterval(50)
        self._resize_timer.timeout.connect(self._recompute_grid)

    def _blink(self):
        self._cursor_visible = not self._cursor_visible
        self.update()

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

    def paintEvent(self, event):
        painter = QPainter(self)
        cw, ch = self._cell_size()
        fm = self.fontMetrics()
        painter.fillRect(self.rect(), DEFAULT_BG)

        sel = self._selection_rect()
        if sel:
            r0, c0, r1, c1 = sel
            for row in range(r0, r1 + 1):
                cstart = c0 if row == r0 else 0
                cend = c1 if row == r1 else self.screen.columns - 1
                painter.fillRect(
                    QRect(cstart * cw, row * ch,
                          (cend - cstart + 1) * cw, ch),
                    SELECT_BG,
                )

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

        if self.hasFocus() and self._cursor_visible:
            cx, cy = self.screen.cursor.x, self.screen.cursor.y
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(DEFAULT_FG)
            painter.drawRect(QRect(cx * cw, cy * ch, cw, ch))
        painter.end()

    def _selection_rect(self):
        if self._sel_start is None or self._sel_end is None:
            return None
        a, b = self._sel_start, self._sel_end
        if a <= b:
            return (a[0], a[1], b[0], b[1])
        return (b[0], b[1], a[0], a[1])

    def _cell_at(self, pos):
        cw, ch = self._cell_size()
        if cw <= 0 or ch <= 0:
            return None
        x = min(max(0, pos.x() // cw), self.screen.columns - 1)
        y = min(max(0, pos.y() // ch), self.screen.lines - 1)
        return (y, x)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            cell = self._cell_at(event.position().toPoint())
            if cell:
                self._sel_start = cell
                self._sel_end = cell
                self.update()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton and self._sel_start is not None:
            cell = self._cell_at(event.position().toPoint())
            if cell:
                self._sel_end = cell
                self.update()
        super().mouseMoveEvent(event)

    def selected_text(self) -> str:
        sel = self._selection_rect()
        if not sel:
            return ""
        r0, c0, r1, c1 = sel
        buffer = self.screen.buffer
        out = []
        for row in range(r0, r1 + 1):
            line = buffer.get(row, {})
            cstart = c0 if row == r0 else 0
            cend = c1 if row == r1 else self.screen.columns - 1
            chars = []
            for col in range(cstart, cend + 1):
                char = line.get(col)
                chars.append(char.data if char and char.data else " ")
            out.append("".join(chars).rstrip())
        return "\n".join(out)

    def _show_context_menu(self, pos):
        menu = QMenu(self)
        act_copy = QAction("Копировать", self)
        act_copy.setEnabled(bool(self.selected_text()))
        act_copy.triggered.connect(self._copy_selection)
        act_paste = QAction("Вставить", self)
        act_paste.triggered.connect(self._paste_from_clipboard)
        act_all = QAction("Выделить всё", self)
        act_all.triggered.connect(self._select_all)
        menu.addAction(act_copy)
        menu.addAction(act_paste)
        menu.addSeparator()
        menu.addAction(act_all)
        menu.exec(self.mapToGlobal(pos))

    def _copy_selection(self):
        text = self.selected_text()
        if text:
            QApplication.clipboard().setText(text)

    def _paste_from_clipboard(self):
        text = QApplication.clipboard().text()
        if text:
            self.key_pressed_bytes.emit(text.encode("utf-8"))

    def _select_all(self):
        self._sel_start = (0, 0)
        self._sel_end = (self.screen.lines - 1, self.screen.columns - 1)
        self.update()

    def keyPressEvent(self, event: QKeyEvent):
        key = event.key()
        text = event.text()
        mods = event.modifiers()

        if mods & Qt.KeyboardModifier.ControlModifier and mods & Qt.KeyboardModifier.ShiftModifier:
            if key == Qt.Key.Key_C:
                self._copy_selection()
                return
            if key == Qt.Key.Key_V:
                self._paste_from_clipboard()
                return
            if key == Qt.Key.Key_A:
                self._select_all()
                return

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
            self._sel_start = self._sel_end = None
            self.update()
            return

        if mods & Qt.KeyboardModifier.ControlModifier and text:
            ch = text.lower()
            if "a" <= ch <= "z":
                self.key_pressed_bytes.emit(bytes([ord(ch) - 96]))
                self._sel_start = self._sel_end = None
                self.update()
                return

        if text:
            self.key_pressed_bytes.emit(text.encode("utf-8"))
            self._sel_start = self._sel_end = None
            self.update()


# ---------- Вкладка = одна SSH-сессия ----------
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


# ---------- Плитка хоста ----------
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
        act_del.triggered.connect(lambda: self.delete_requested.emit(self.name))
        menu.addAction(act_open)
        menu.addAction(act_edit)
        menu.addSeparator()
        menu.addAction(act_del)
        menu.exec(global_pos)


# ---------- Домашняя вкладка (плитки) ----------
class HomeTab(QWidget):
    """Отдельная вкладка с плитками сохранённых хостов."""

    host_activated = pyqtSignal(str)
    host_edit = pyqtSignal(str)
    host_delete = pyqtSignal(str)
    new_host_clicked = pyqtSignal()

    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        self.setStyleSheet("background-color: #101418;")

        # Кнопка "Новый хост" сверху
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

        top = QHBoxLayout()
        top.setContentsMargins(24, 20, 24, 0)
        top.addWidget(new_btn)
        top.addStretch(1)

        # Скроллируемая область с плитками
        self.tiles_host = QWidget()
        self.tiles_grid = QGridLayout(self.tiles_host)
        self.tiles_grid.setContentsMargins(24, 20, 24, 24)
        self.tiles_grid.setSpacing(14)
        self.tiles_grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(self.tiles_host)
        scroll.setStyleSheet("QScrollArea { background: transparent; }")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addLayout(top)
        root.addWidget(scroll, 1)

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

        # Автоматическое количество колонок по ширине
        cols = self._column_count()
        for i, name in enumerate(names):
            info = self.store.get(name)
            tile = HostTile(name, info)
            tile.clicked.connect(self.host_activated.emit)
            tile.edit_requested.connect(self.host_edit.emit)
            tile.delete_requested.connect(self.host_delete.emit)
            self.tiles_grid.addWidget(tile, i // cols, i % cols)

        # растянуть колонки равномерно
        for c in range(cols):
            self.tiles_grid.setColumnStretch(c, 1)

    def _column_count(self):
        # ширину окна делим на ~260px на плитку
        w = self.width() or 1200
        return max(1, (w - 48) // 260)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Перестраиваем сетку при заметном изменении ширины
        new_cols = self._column_count()
        if getattr(self, "_last_cols", None) != new_cols:
            self._last_cols = new_cols
            self.refresh()


# ---------- Drawer ----------
class Drawer(QWidget):
    submitted = pyqtSignal(dict)
    cancelled = pyqtSignal()

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
        self.key_edit = QLineEdit()
        self.key_edit.setPlaceholderText("~/.ssh/id_ed25519 (опционально)")

        self.save_check = QCheckBox("Сохранить в список")
        self.save_check.setChecked(True)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.addRow("Имя:", self.name_edit)
        form.addRow("Хост:", self.host_edit)
        form.addRow("Порт:", self.port_spin)
        form.addRow("Пользователь:", self.user_edit)
        form.addRow("Пароль:", self.pass_edit)
        form.addRow("Ключ:", self.key_edit)

        title = QLabel("Новое подключение")
        f = title.font()
        f.setPointSize(14)
        f.setBold(True)
        title.setFont(f)
        title.setStyleSheet("color: #e5e9f0;")

        hint = QLabel("Пароль не сохраняется на диск.")
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

    def open_with(self, name="", host="", port=22, user="", key="", save=True):
        self.name_edit.setText(name)
        self.host_edit.setText(host)
        self.port_spin.setValue(port)
        self.user_edit.setText(user)
        self.pass_edit.clear()
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
        self.cancelled.emit()
        self.close_drawer()


# ---------- Главное окно ----------
class MainWindow(QMainWindow):
    HOME_TAB_TITLE = "Главная"

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Freemius SSH Client")
        self.resize(1200, 760)

        self.store = ConnectionStore()
        self._tab_activity = {}

        # Табы
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

        # Домашняя вкладка
        self.home = HomeTab(self.store)
        self.home.host_activated.connect(self.open_saved_host)
        self.home.host_edit.connect(self.edit_saved_host)
        self.home.host_delete.connect(self.delete_saved_host)
        self.home.new_host_clicked.connect(self.open_new_host_drawer)

        self.home_index = self.tabs.addTab(self.home, self.HOME_TAB_TITLE)
        # убрать крестик с домашней вкладки
        self.tabs.tabBar().setTabButton(self.home_index, self.tabs.tabBar().ButtonPosition.RightSide, None)
        self.tabs.tabBar().setTabButton(self.home_index, self.tabs.tabBar().ButtonPosition.LeftSide, None)

        self.setCentralWidget(self.tabs)

        # Drawer
        self.drawer = Drawer(self)
        self.drawer.submitted.connect(self._on_drawer_submit)

        self.home.refresh()
        self._install_shortcuts()

    # --- геометрия drawer ---
    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.drawer.setGeometry(self.rect())

    def showEvent(self, event):
        super().showEvent(event)
        self.drawer.setGeometry(self.rect())

    # --- шорткаты ---
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

    # --- drawer ---
    def open_new_host_drawer(self):
        self.drawer.open_with(save=True)

    def edit_saved_host(self, name):
        info = self.store.get(name) or {}
        self.drawer.open_with(
            name=name,
            host=info.get("host", ""),
            port=int(info.get("port", 22)),
            user=info.get("user", ""),
            key=info.get("key", ""),
            save=True,
        )

    def _on_drawer_submit(self, data):
        name = data["name"]
        if data["save"]:
            self.store.add(
                name=name,
                host=data["host"],
                port=data["port"],
                user=data["user"],
                key=data["key"] or "",
            )
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

    # --- открытие сессии ---
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

    # --- управление табами ---
    def close_current_tab(self):
        idx = self.tabs.currentIndex()
        if idx <= self.home_index:
            return  # домашнюю не закрываем
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
        self._tab_activity.pop(id(tab), None)
        self.tabs.removeTab(idx)
        tab.deleteLater()
        # индекс домашней вкладки мог сдвинуться — обновим
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

    # --- удаление плитки ---
    def delete_saved_host(self, name):
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
        event.accept()


def main():
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
