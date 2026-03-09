"""
Collection panel: a staging area where the user gathers images
before placing them into the collage.
Accepts drops from the file explorer and from the OS.
Images can be dragged *out* from here into collage cells.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QEvent, QMimeData, QPoint, QSize, Qt, QUrl
from PySide6.QtGui import QDrag, QPainter, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QLabel, QListWidget, QListWidgetItem,
    QSizePolicy, QVBoxLayout, QWidget,
)

from utils.image_utils import SUPPORTED_EXTENSIONS, thumbnail_cache

THUMB = 96  # pixel size for collection thumbnails


class CollectionPanel(QWidget):
    """Staging area for images to be used in the collage."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumWidth(160)
        self._build_ui()

    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 4, 2, 4)
        layout.setSpacing(4)

        header = QLabel("<b>Collection</b>")
        layout.addWidget(header)

        hint = QLabel("Drop images here")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setStyleSheet("color: #888; font-size: 11px;")
        layout.addWidget(hint)
        self._hint = hint

        self._list = _CollectionList()
        self._list.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._list.model().rowsInserted.connect(self._update_hint)
        self._list.model().rowsRemoved.connect(self._update_hint)
        layout.addWidget(self._list)

    def _update_hint(self) -> None:
        self._hint.setVisible(self._list.count() == 0)

    # ------------------------------------------------------------------

    def add_image(self, path: str) -> None:
        """Add an image path to the collection if not already present."""
        p = Path(path)
        if p.suffix.lower() not in SUPPORTED_EXTENSIONS:
            return
        # Prevent duplicates
        for i in range(self._list.count()):
            if self._list.item(i).data(Qt.ItemDataRole.UserRole) == str(p):
                return
        item = QListWidgetItem(p.name)
        item.setData(Qt.ItemDataRole.UserRole, str(p))
        pixmap = thumbnail_cache.load(str(p), THUMB)
        if pixmap:
            item.setIcon(pixmap)           # QPixmap is accepted as QIcon
        item.setToolTip(str(p))
        self._list.addItem(item)


class _CollectionList(QListWidget):
    """List widget that accepts URL drops and starts image URL drags."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setViewMode(QListWidget.ViewMode.IconMode)
        self.setIconSize(QSize(THUMB, THUMB))
        self.setGridSize(QSize(THUMB + 12, THUMB + 20))
        self.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.setMovement(QListWidget.Movement.Static)
        self.setDragEnabled(True)
        # DragOnly lets the list start URL drags outward while the viewport
        # event filter handles all incoming URL drops independently.
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
        self.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setSpacing(4)
        self.setWordWrap(True)
        # Install event filter on viewport to intercept external URL drops
        self.viewport().setAcceptDrops(True)
        self.viewport().installEventFilter(self)

    # -- Accept drops via viewport event filter ------------------------

    def eventFilter(self, obj, event) -> bool:
        if obj is self.viewport():
            t = event.type()
            if t == QEvent.Type.DragEnter and event.mimeData().hasUrls():
                event.acceptProposedAction()
                return True
            if t == QEvent.Type.DragMove and event.mimeData().hasUrls():
                event.acceptProposedAction()
                return True
            if t == QEvent.Type.Drop and event.mimeData().hasUrls():
                for url in event.mimeData().urls():
                    if url.isLocalFile():
                        self._add_path(url.toLocalFile())
                event.acceptProposedAction()
                return True
        return super().eventFilter(obj, event)

    def _add_path(self, path: str) -> None:
        p = Path(path)
        if p.is_dir():
            for child in sorted(p.iterdir()):
                if child.suffix.lower() in SUPPORTED_EXTENSIONS:
                    self._add_path(str(child))
            return
        if p.suffix.lower() not in SUPPORTED_EXTENSIONS:
            return
        for i in range(self.count()):
            if self.item(i).data(Qt.ItemDataRole.UserRole) == str(p):
                return
        item = QListWidgetItem(p.name)
        item.setData(Qt.ItemDataRole.UserRole, str(p))
        px = thumbnail_cache.load(str(p), THUMB)
        if px:
            item.setIcon(px)
        item.setToolTip(str(p))
        self.addItem(item)

    # -- Start drag with URLs ------------------------------------------

    def startDrag(self, supported_actions: Qt.DropAction) -> None:
        items = self.selectedItems()
        if not items:
            return
        urls = [
            QUrl.fromLocalFile(i.data(Qt.ItemDataRole.UserRole))
            for i in items
        ]
        mime = QMimeData()
        mime.setUrls(urls)

        # Use thumbnail as drag pixmap
        if items:
            path = items[0].data(Qt.ItemDataRole.UserRole)
            px = thumbnail_cache.load(path, THUMB)
            drag = QDrag(self)
            drag.setMimeData(mime)
            if px:
                scaled = px.scaled(
                    80, 80,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                drag.setPixmap(scaled)
                drag.setHotSpot(QPoint(scaled.width() // 2, scaled.height() // 2))
            drag.exec(Qt.DropAction.CopyAction)
