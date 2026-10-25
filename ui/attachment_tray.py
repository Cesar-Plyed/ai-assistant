"""Attachment tray shown above the composer.

Images appear as 72×72 thumbnails with a ``#n`` badge (top-right), an ×
button, drag-to-reorder and click-to-preview. Other files appear as chips
(icon, name, size, badge). Items are numbered 1..n in tray order so the user
can say "compare image 1 with image 2".
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QMimeData, QPoint, Qt, Signal
from PySide6.QtGui import QDrag, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from core import attachments as att
from ui.icons import get_icon

_MIME = "application/x-attachment-index"


class PreviewDialog(QDialog):
    def __init__(self, meta: dict[str, Any], parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"#{meta.get('index')} — {meta.get('name')}")
        layout = QVBoxLayout(self)
        label = QLabel()
        pix = QPixmap(meta.get("model_path") or meta.get("path", ""))
        if not pix.isNull():
            pix = pix.scaled(720, 540, Qt.AspectRatioMode.KeepAspectRatio,
                             Qt.TransformationMode.SmoothTransformation)
            label.setPixmap(pix)
        else:
            label.setText("Preview not available")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(label)
        info = QLabel(f"{meta.get('width', '?')}×{meta.get('height', '?')} · "
                      f"{att.human_size(int(meta.get('size', 0)))}")
        info.setProperty("muted", True)
        layout.addWidget(info)


class AttachmentChip(QFrame):
    removeRequested = Signal(int)   # position in tray
    previewRequested = Signal(int)
    reorderRequested = Signal(int, int)  # from, to

    def __init__(self, meta: dict[str, Any], position: int, parent=None):
        super().__init__(parent)
        self.meta = meta
        self.position = position
        self.setObjectName("attachmentChip")
        self.setAcceptDrops(True)
        self.setAccessibleName(f"Attachment {meta.get('index')}: {meta.get('name')}")
        self.setToolTip(f"#{meta.get('index')} {meta.get('name')}")
        self._press_pos: QPoint | None = None

        is_image = meta.get("kind") == "image"
        lay = QHBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(6)

        if is_image:
            self.setFixedSize(att.THUMB_SIZE + 8, att.THUMB_SIZE + 8)
            thumb = QLabel()
            pix = QPixmap(meta.get("thumb") or meta.get("path", ""))
            if not pix.isNull():
                pix = pix.scaled(att.THUMB_SIZE, att.THUMB_SIZE,
                                 Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                 Qt.TransformationMode.SmoothTransformation)
                thumb.setPixmap(pix.copy(0, 0, att.THUMB_SIZE, att.THUMB_SIZE))
            thumb.setFixedSize(att.THUMB_SIZE, att.THUMB_SIZE)
            lay.addWidget(thumb)
        else:
            self.setMinimumHeight(att.THUMB_SIZE // 2 + 8)
            icon = QLabel()
            icon.setPixmap(get_icon("upload").pixmap(20, 20))
            lay.addWidget(icon)
            col = QVBoxLayout()
            col.setSpacing(0)
            name = QLabel(meta.get("name", "file"))
            name.setMaximumWidth(140)
            size = QLabel(att.human_size(int(meta.get("size", 0))))
            size.setProperty("muted", True)
            col.addWidget(name)
            col.addWidget(size)
            lay.addLayout(col)
            lay.addSpacing(22)

        self.badge = QLabel(f"#{meta.get('index')}", self)
        self.badge.setObjectName("attachmentBadge")
        self.badge.adjustSize()
        self.remove_button = QPushButton("×", self)
        self.remove_button.setProperty("secondary", True)
        self.remove_button.setFixedSize(20, 20)
        self.remove_button.setStyleSheet("padding: 0; font-size: 13px; min-height: 0;")
        self.remove_button.setAccessibleName(f"Remove attachment {meta.get('index')}")
        self.remove_button.clicked.connect(lambda: self.removeRequested.emit(self.position))
        self._place_overlays()

    def _place_overlays(self) -> None:
        self.badge.move(self.width() - self.badge.width() - 3, 3)
        self.remove_button.move(2, self.height() - self.remove_button.height() - 2)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._place_overlays()

    # drag to reorder / click to preview
    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_pos = event.position().toPoint()

    def mouseMoveEvent(self, event) -> None:
        if self._press_pos is None:
            return
        if (event.position().toPoint() - self._press_pos).manhattanLength() < 8:
            return
        drag = QDrag(self)
        mime = QMimeData()
        mime.setData(_MIME, str(self.position).encode())
        drag.setMimeData(mime)
        drag.setPixmap(self.grab())
        self._press_pos = None
        drag.exec(Qt.DropAction.MoveAction)

    def mouseReleaseEvent(self, event) -> None:
        if self._press_pos is not None and event.button() == Qt.MouseButton.LeftButton:
            self.previewRequested.emit(self.position)
        self._press_pos = None

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasFormat(_MIME):
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        if event.mimeData().hasFormat(_MIME):
            src = int(bytes(event.mimeData().data(_MIME)).decode())
            self.reorderRequested.emit(src, self.position)
            event.acceptProposedAction()


class AttachmentTray(QScrollArea):
    """Horizontal strip of attachments. Hidden while empty."""

    changed = Signal()
    rejected = Signal(str)   # human-readable reason (shown as a toast by the window)

    def __init__(self, chat_id_getter, parent=None):
        super().__init__(parent)
        self._chat_id = chat_id_getter
        self.items: list[dict[str, Any]] = []
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setFixedHeight(att.THUMB_SIZE + 24)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setAccessibleName("Attachments")
        self._inner = QWidget()
        self._row = QHBoxLayout(self._inner)
        self._row.setContentsMargins(0, 4, 0, 4)
        self._row.setSpacing(8)
        self._row.addStretch()
        self.setWidget(self._inner)
        self.hide()

    # -- adding ----------------------------------------------------------
    def add_paths(self, paths: list[str]) -> int:
        added = 0
        for path in paths:
            if len(self.items) >= att.MAX_ATTACHMENTS:
                self.rejected.emit(f"Máximo {att.MAX_ATTACHMENTS} adjuntos por mensaje.")
                break
            try:
                meta = att.process_attachment(path, self._chat_id(), len(self.items) + 1)
            except att.AttachmentError as exc:
                self.rejected.emit(str(exc))
                continue
            self.items.append(meta)
            added += 1
        self._rebuild()
        return added

    def add_image_bytes(self, data: bytes, name: str = "pasted.png") -> bool:
        if len(self.items) >= att.MAX_ATTACHMENTS:
            self.rejected.emit(f"Máximo {att.MAX_ATTACHMENTS} adjuntos por mensaje.")
            return False
        try:
            meta = att.process_attachment_bytes(data, name, self._chat_id(), len(self.items) + 1)
        except att.AttachmentError as exc:
            self.rejected.emit(str(exc))
            return False
        self.items.append(meta)
        self._rebuild()
        return True

    # -- editing ---------------------------------------------------------
    def remove_at(self, position: int) -> None:
        if 0 <= position < len(self.items):
            att.remove_attachment_files(self.items.pop(position))
            self._rebuild()

    def move(self, src: int, dst: int) -> None:
        if src == dst or not (0 <= src < len(self.items)) or not (0 <= dst < len(self.items)):
            return
        self.items.insert(dst, self.items.pop(src))
        self._rebuild()

    def take(self) -> list[dict[str, Any]]:
        """Hand the attachments to the sender and empty the tray (files are kept)."""
        taken = att.renumber(list(self.items))
        self.items = []
        self._rebuild()
        return taken

    def clear_discard(self) -> None:
        for meta in self.items:
            att.remove_attachment_files(meta)
        self.items = []
        self._rebuild()

    def _preview(self, position: int) -> None:
        if 0 <= position < len(self.items) and self.items[position].get("kind") == "image":
            PreviewDialog(self.items[position], self).exec()

    def _rebuild(self) -> None:
        att.renumber(self.items)
        while self._row.count() > 1:
            item = self._row.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for pos, meta in enumerate(self.items):
            chip = AttachmentChip(meta, pos)
            chip.removeRequested.connect(self.remove_at)
            chip.previewRequested.connect(self._preview)
            chip.reorderRequested.connect(self.move)
            self._row.insertWidget(pos, chip)
        self.setVisible(bool(self.items))
        self.changed.emit()
