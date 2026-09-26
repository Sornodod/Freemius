"""Виджет терминала: pyte-экран, QPainter, скроллбэк, авто-скролл при выделении."""

import pyte
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject, QRect, QPoint
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

    HISTORY_LINES = 5000

    def __init__(self, cols=80, rows=24, parent=None):
        super().__init__(parent)
        self.cols = cols
        self.rows = rows

        self.screen = pyte.HistoryScreen(columns=cols, lines=rows,
                                          history=self.HISTORY_LINES)
        self.stream = pyte.ByteStream(self.screen)

        self._scroll_offset = 0

        # выделение в АБСОЛЮТНЫХ координатах потока:
        # abs_row = hist_len + row_in_screen  (для живого экрана)
        # abs_row = 0..hist_len-1             (для истории)
        # col = 0..columns-1
        self._sel_start_abs = None  # (abs_row, col)
        self._sel_end_abs = None

        font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        font.setPointSize(11)
        self.setFont(font)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setAutoFillBackground(False)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)

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

        # авто-скролл при выделении: таймер + направление
        self._autoscroll_dir = 0   # -1 вверх, +1 вниз, 0 стоп
        self._autoscroll_timer = QTimer(self)
        self._autoscroll_timer.setInterval(50)
        self._autoscroll_timer.timeout.connect(self._autoscroll_tick)
        self._autoscroll_lines = 1  # сколько строк за тик

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
        self._scroll_offset = 0
        self.resized.emit(w, h)
        self.update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._resize_timer.start()

    def feed(self, data: bytes):
        data = self._sanitize_stream(data)
        if data:
            was_at_bottom = (self._scroll_offset == 0)
            self.stream.feed(data)
            if was_at_bottom:
                self._scroll_offset = 0
            self.update()

    def _sanitize_stream(self, data: bytes) -> bytes:
        buf = self._san_buf + data
        self._san_buf = b""

        if b"cannot change locale" not in buf and b"setlocale" not in buf:
            return buf

        import re
        out = re.sub(
            rb"/bin/bash:\s*warning:\s*setlocale:[^\r\n]*[\r\n]*",
            b"",
            buf,
        )
        out = re.sub(
            rb"[^\r\n]*cannot change locale[^\r\n]*[\r\n]*",
            b"",
            out,
        )
        return out

    # ---------- координаты ----------
    def _history_len(self):
        return len(self.screen.history.top)

    def _max_scroll(self):
        return self._history_len()

    def _abs_from_screen_row(self, screen_row: int) -> int:
        """Абсолютная строка потока для видимой строки."""
        return self._history_len() + screen_row

    def _screen_from_abs(self, abs_row: int):
        """Возвращает ('screen'|'history', index) для абсолютной строки."""
        hist_len = self._history_len()
        if abs_row < hist_len:
            return ("history", abs_row)
        return ("screen", abs_row - hist_len)

    def _get_line_by_abs(self, abs_row: int):
        where, idx = self._screen_from_abs(abs_row)
        if where == "history":
            try:
                return self.screen.history.top[idx]
            except IndexError:
                return None
        else:
            if 0 <= idx < self.screen.lines:
                return self.screen.buffer[idx]
            return None

    # ---------- скролл ----------
    def scroll_up(self, lines=1):
        new = min(self._scroll_offset + lines, self._max_scroll())
        if new != self._scroll_offset:
            self._scroll_offset = new
            self.update()

    def scroll_down(self, lines=1):
        new = max(0, self._scroll_offset - lines)
        if new != self._scroll_offset:
            self._scroll_offset = new
            self.update()

    def scroll_to_bottom(self):
        if self._scroll_offset != 0:
            self._scroll_offset = 0
            self.update()

    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        if delta > 0:
            self.scroll_up(3)
        elif delta < 0:
            self.scroll_down(3)
        event.accept()

    # ---------- автоскролл при выделении ----------
    def _autoscroll_tick(self):
        if self._autoscroll_dir == 0:
            self._autoscroll_timer.stop()
            return
        if self._autoscroll_dir < 0:
            self.scroll_up(self._autoscroll_lines)
        else:
            self.scroll_down(self._autoscroll_lines)

        # расширяем выделение до верхней/нижней видимой строки
        if self._sel_end_abs is not None:
            if self._autoscroll_dir < 0:
                # мы ушли вверх — выделение тянется к верхней строке
                new_abs = self._history_len() - self._scroll_offset
            else:
                # вниз — к нижней
                new_abs = self._history_len() - self._scroll_offset + self.screen.lines - 1
            # обновим только строку, столбец — тот, что был при последнем движении
            self._sel_end_abs = (new_abs, self._sel_end_abs[1])
        self.update()

    def _start_autoscroll(self, direction: int):
        self._autoscroll_dir = direction
        if not self._autoscroll_timer.isActive():
            self._autoscroll_timer.start()

    def _stop_autoscroll(self):
        self._autoscroll_dir = 0
        self._autoscroll_timer.stop()

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
    def _visible_abs_start(self):
        """Абсолютная строка, которая отображается в самой верхней видимой позиции."""
        return self._history_len() - self._scroll_offset

    def _selection_abs_range(self):
        """Возвращает (start_abs, start_col, end_abs, end_col) или None."""
        if self._sel_start_abs is None or self._sel_end_abs is None:
            return None
        a, b = self._sel_start_abs, self._sel_end_abs
        if a <= b:
            return (a[0], a[1], b[0], b[1])
        return (b[0], b[1], a[0], a[1])

    def paintEvent(self, event):
        painter = QPainter(self)
        cw, ch = self._cell_size()
        fm = self.fontMetrics()
        painter.fillRect(self.rect(), DEFAULT_BG)

        abs_top = self._visible_abs_start()

        # выделение рисуем поверх строк
        sel = self._selection_abs_range()

        # сначала фон выделения
        if sel:
            r0, c0, r1, c1 = sel
            for abs_row in range(r0, r1 + 1):
                screen_row = abs_row - abs_top
                if screen_row < 0 or screen_row >= self.screen.lines:
                    continue
                cstart = c0 if abs_row == r0 else 0
                cend = c1 if abs_row == r1 else self.screen.columns - 1
                painter.fillRect(
                    QRect(cstart * cw, screen_row * ch,
                          (cend - cstart + 1) * cw, ch),
                    SELECT_BG,
                )

        for screen_row in range(self.screen.lines):
            abs_row = abs_top + screen_row
            line = self._get_line_by_abs(abs_row)
            if line is None:
                continue
            for x in range(self.screen.columns):
                char = line.get(x)
                if char is None:
                    continue
                ch_ = char.data or " "
                if ch_ == " " and char.bg == "default" and char.fg == "default":
                    continue
                fg = DEFAULT_FG if char.fg == "default" else self._map_color(char.fg, char.bold)
                bg = DEFAULT_BG if char.bg == "default" else self._map_color(char.bg, False)
                x_px, y_px = x * cw, screen_row * ch
                if bg != DEFAULT_BG:
                    painter.fillRect(QRect(x_px, y_px, cw, ch), bg)
                if ch_.strip() == "":
                    continue
                painter.setPen(fg)
                painter.drawText(x_px, y_px + fm.ascent(), ch_)

        if self.hasFocus() and self._cursor_visible and self._scroll_offset == 0:
            cx, cy = self.screen.cursor.x, self.screen.cursor.y
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(DEFAULT_FG)
            painter.drawRect(QRect(cx * cw, cy * ch, cw, ch))

        # индикатор, что мы не внизу
        if self._scroll_offset > 0:
            painter.setBrush(QColor("#d7a13c"))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRect(QRect(0, 0, self.width(), 3))

        painter.end()

    # ---------- мышь ----------
    def _cell_at(self, pos: QPoint):
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
                screen_row, col = cell
                abs_row = self._abs_from_screen_row(screen_row)
                self._sel_start_abs = (abs_row, col)
                self._sel_end_abs = (abs_row, col)
                self.update()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if not (event.buttons() & Qt.MouseButton.LeftButton):
            super().mouseMoveEvent(event)
            return

        if self._sel_start_abs is None:
            super().mouseMoveEvent(event)
            return

        pos = event.position().toPoint()
        cw, ch = self._cell_size()
        if cw <= 0 or ch <= 0:
            super().mouseMoveEvent(event)
            return

        # определяем, за границей ли мышь
        if pos.y() < 0:
            self._start_autoscroll(-1)
            # не трогаем _sel_end_abs — таймер сам расширит
        elif pos.y() >= self.height():
            self._start_autoscroll(+1)
        else:
            self._stop_autoscroll()
            # мышь внутри — обновляем _sel_end_abs
            x = min(max(0, pos.x() // cw), self.screen.columns - 1)
            y = min(max(0, pos.y() // ch), self.screen.lines - 1)
            abs_row = self._abs_from_screen_row(y)
            self._sel_end_abs = (abs_row, x)
            self.update()

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._stop_autoscroll()
        super().mouseReleaseEvent(event)

    def selected_text(self) -> str:
        sel = self._selection_abs_range()
        if not sel:
            return ""
        r0, c0, r1, c1 = sel
        out = []
        for abs_row in range(r0, r1 + 1):
            line = self._get_line_by_abs(abs_row)
            if line is None:
                out.append("")
                continue
            cstart = c0 if abs_row == r0 else 0
            cend = c1 if abs_row == r1 else self.screen.columns - 1
            chars = []
            for col in range(cstart, cend + 1):
                char = line.get(col)
                chars.append(char.data if char and char.data else " ")
            out.append("".join(chars).rstrip())
        return "\n".join(out)

    def _clear_selection(self):
        self._sel_start_abs = None
        self._sel_end_abs = None

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
        """Выделить всё, что есть — историю + экран."""
        self._sel_start_abs = (0, 0)
        last_abs = self._history_len() + self.screen.lines - 1
        self._sel_end_abs = (last_abs, self.screen.columns - 1)
        self.update()

    # ---------- ввод ----------
    def keyPressEvent(self, event: QKeyEvent):
        key = event.key()
        text = event.text()
        mods = event.modifiers()

        if mods & Qt.KeyboardModifier.ShiftModifier:
            if key == Qt.Key.Key_PageUp:
                self.scroll_up(self.screen.lines - 1)
                return
            if key == Qt.Key.Key_PageDown:
                self.scroll_down(self.screen.lines - 1)
                return
            if key == Qt.Key.Key_Up:
                self.scroll_up(1)
                return
            if key == Qt.Key.Key_Down:
                self.scroll_down(1)
                return
            if key == Qt.Key.Key_Home:
                self.scroll_up(self._max_scroll())
                return
            if key == Qt.Key.Key_End:
                self.scroll_to_bottom()
                return

        if key == Qt.Key.Key_PageUp:
            self.scroll_up(self.screen.lines - 1)
            return
        if key == Qt.Key.Key_PageDown:
            self.scroll_down(self.screen.lines - 1)
            return

        if self._scroll_offset != 0:
            self.scroll_to_bottom()

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
            Qt.Key.Key_Insert: b"\x1b[2~", Qt.Key.Key_Delete: b"\x1b[3~",
            Qt.Key.Key_F1: b"\x1bOP", Qt.Key.Key_F2: b"\x1bOQ",
            Qt.Key.Key_F3: b"\x1bOR", Qt.Key.Key_F4: b"\x1bOS",
            Qt.Key.Key_F5: b"\x1b[15~", Qt.Key.Key_F6: b"\x1b[17~",
        }
        if key in mapping:
            self.key_pressed_bytes.emit(mapping[key])
            self._clear_selection()
            self.update()
            return

        if mods & Qt.KeyboardModifier.ControlModifier and text:
            ch = text.lower()
            if "a" <= ch <= "z":
                self.key_pressed_bytes.emit(bytes([ord(ch) - 96]))
                self._clear_selection()
                self.update()
                return

        if text:
            self.key_pressed_bytes.emit(text.encode("utf-8"))
            self._clear_selection()
            self.update()
