"""Передача файлов между панелями с прогрессом."""

import os
import shutil
import tempfile

from PyQt6.QtCore import Qt, QObject, pyqtSignal
from PyQt6.QtWidgets import (
    QMessageBox, QDialog, QVBoxLayout, QLabel, QProgressBar, QPushButton,
)


class TransferProgress(QDialog):
    """Модальное окно прогресса передачи файла."""

    cancelled = pyqtSignal()

    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Передача")
        self.setModal(True)
        self.setMinimumWidth(400)
        self._cancelled = False

        self.label = QLabel(title)
        self.label.setWordWrap(True)

        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setValue(0)

        self.detail = QLabel("0 / 0")
        self.detail.setStyleSheet("color: #7f8a99;")

        self.cancel_btn = QPushButton("Отмена")
        self.cancel_btn.clicked.connect(self._on_cancel)

        v = QVBoxLayout(self)
        v.addWidget(self.label)
        v.addWidget(self.bar)
        v.addWidget(self.detail)
        v.addWidget(self.cancel_btn)

    def _on_cancel(self):
        self._cancelled = True
        self.cancelled.emit()
        self.reject()

    def is_cancelled(self):
        return self._cancelled

    def update_progress(self, got, total):
        if total > 0:
            pct = int(got * 100 / total)
            self.bar.setRange(0, 100)
            self.bar.setValue(min(100, pct))
            self.detail.setText(f"{_human(got)} / {_human(total)}")
        else:
            self.bar.setRange(0, 0)  # indeterminate
            self.detail.setText(_human(got))


def _human(n):
    units = ["B", "K", "M", "G", "T"]
    f = float(n)
    for u in units:
        if f < 1024:
            return f"{f:.0f}{u}" if u == "B" else f"{f:.1f}{u}"
        f /= 1024
    return f"{f:.1f}P"


def transfer_file(src_panel, dst_panel, entry, parent=None):
    """Скопировать entry из src_panel в cwd dst_panel с прогрессом."""
    if not src_panel.provider or not dst_panel.provider:
        return False

    dst_dir = getattr(dst_panel.provider, "cwd", None)
    if dst_dir is None:
        return False
    dst_path = dst_dir.rstrip("/") + "/" + entry.name

    dlg = TransferProgress(f"Копирование: {entry.name}", parent)
    dlg.show()

    ok = False
    try:
        src = src_panel.provider
        dst = dst_panel.provider

        # --- определяем размер для прогресса ---
        if src.kind == "local":
            try:
                total = os.path.getsize(entry.path)
            except OSError:
                total = 0
        else:
            total = getattr(src, "size_of", lambda p: 0)(entry.path)

        # --- качаем во временный файл ---
        tmpdir = tempfile.mkdtemp(prefix="freemius_xfer_")
        local_tmp = os.path.join(tmpdir, entry.name)

        def cb(got, tot):
            if dlg.is_cancelled():
                raise RuntimeError("Отменено пользователем")
            dlg.update_progress(got, tot or total)

        if src.kind == "local":
            shutil.copy2(entry.path, local_tmp)
        else:
            src.stream_download(entry.path, local_tmp, progress_cb=cb)

        # --- заливаем из временного ---
        if dst.kind == "local":
            shutil.copy2(local_tmp, dst_path)
        else:
            dst.stream_upload(local_tmp, dst_path, progress_cb=cb)

        shutil.rmtree(tmpdir, ignore_errors=True)
        ok = True
    except Exception as e:
        QMessageBox.critical(parent, "Ошибка передачи", str(e))
    finally:
        dlg.close()

    return ok
