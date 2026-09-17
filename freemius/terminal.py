"""Виджет терминала: рисует pyte-экран QPainter-ом."""

import pyte
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject, QRect
from PyQt6.QtGui import (
    QFont, QFontDatabase, QKeyEvent, QPainter, QColor, QAction,
)
from PyQt6.QtWidgets import QWidget, QApplication, QMenu

from .ui_helpers import (
    DEFAULT_FG, DEFAULT_BG, SELECT_BG, ANSI_COLORS,
)


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
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)

        self._sel_start = None
        self._sel_end = None

        # буфер незавершённой строки для потокового фильтра мусора
        self._san_buf = b""

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

    # ---------- вывод + фильтр ----------
    def feed(self, data: bytes):
        data = self._sanitize_stream(data)
        if data:
            self.stream.feed(data)
            self.update()

    def _sanitize_stream(self, data: bytes) -> bytes:
        """Потоковый фильтр мусора: работает с чанками, а не со строками.

        bash и sshd могут слать warning «setlocale» и ANSI-мусор кусками,
        между которыми нет \\n. Поэтому держим накопительный буфер и
        вырезаем строку целиком, когда она завершится.
        """
        buf = self._san_buf + data

        if b"\n" not in buf:
            self._san_buf = buf
            # защита от бесконечного роста, если \n так и не придёт
            if len(self._san_buf) > 64 * 1024:
                self._san_buf = self._san_buf[-1024:]
            return b""

        lines = buf.split(b"\n")
        self._san_buf = lines[-1]  # последняя без \n — оставляем до следующего раза
        out = []
        for line in lines[:-1]:
            out.append(self._filter_line(line) + b"\n")
        return b"".join(out)

    @staticmethod
    def _filter_line(line: bytes) -> bytes:
        """Убирает warning-строки про локаль из одной строки."""
        low = line.lower()
        if b"cannot change locale" in low:
            return b""
        if b"setlocale" in low and b"warning" in low:
            return b""
        return line

    # ---------- палитра ----------
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

    # ---------- отрисовка ----------
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

    # ---------- выделение ----------
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

    # ---------- контекстное меню ----------
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

    # ---------- ввод ----------
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
