"""Вкладка SFTP: две панели."""

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QPushButton,
)

from .sftp.panel import FilePanel
from .sftp.transfer import transfer_file


class SftpTab(QWidget):
    closed = pyqtSignal(object)

    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store

        self.left = FilePanel(store)
        self.right = FilePanel(store)
        self.left.request_drop_from.connect(self._on_drop)
        self.right.request_drop_from.connect(self._on_drop)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.left)
        splitter.addWidget(self.right)
        splitter.setSizes([500, 500])

        self.to_left_btn = QPushButton("◀  Скачать влево")
        self.to_right_btn = QPushButton("Загрузить вправо  ▶")
        self.to_left_btn.clicked.connect(self._transfer_to_left)
        self.to_right_btn.clicked.connect(self._transfer_to_right)

        center = QHBoxLayout()
        center.setContentsMargins(0, 4, 0, 4)
        center.addStretch(1)
        center.addWidget(self.to_left_btn)
        center.addWidget(self.to_right_btn)
        center.addStretch(1)

        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.addWidget(splitter, 1)
        root.addLayout(center)

    def _on_drop(self, src_id, dst_panel):
        src_panel = self.left if id(self.left) == src_id else self.right
        if src_panel is dst_panel:
            return
        entries = src_panel.selected_entries()
        if not entries:
            return
        for entry in entries:
            transfer_file(src_panel, dst_panel, entry)
        dst_panel.refresh()

    def _transfer_to_left(self):
        src, dst = self.right, self.left
        entry = src.selected_entry()
        if not entry:
            return
        if transfer_file(src, dst, entry):
            dst.refresh()

    def _transfer_to_right(self):
        src, dst = self.left, self.right
        entry = src.selected_entry()
        if not entry:
            return
        if transfer_file(src, dst, entry):
            dst.refresh()
