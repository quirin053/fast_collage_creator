"""
Left panel: File-system explorer filtered to image files.
Supports drag-and-drop of images into the collection or workspace.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import (
    QDir, QMimeData, QModelIndex, QSortFilterProxyModel, Qt, QUrl,
)
from PySide6.QtCore import QStandardPaths
from PySide6.QtGui import QDrag
from PySide6.QtWidgets import (
    QFileSystemModel, QLabel, QLineEdit, QPushButton,
    QTreeView, QVBoxLayout, QWidget, QHBoxLayout,
)

from utils.image_utils import SUPPORTED_EXTENSIONS


class ImageFilterProxy(QSortFilterProxyModel):
    """Show only directories and supported image files."""

    def filterAcceptsRow(self, source_row: int,
                         source_parent: QModelIndex) -> bool:
        model: QFileSystemModel = self.sourceModel()  # type: ignore
        idx = model.index(source_row, 0, source_parent)
        if model.isDir(idx):
            return True
        suffix = Path(model.filePath(idx)).suffix.lower()
        return suffix in SUPPORTED_EXTENSIONS


class FileExplorerPanel(QWidget):
    """File-system tree panel with drag support."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumWidth(200)
        self._build_ui()

    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 4, 2, 4)
        layout.setSpacing(4)

        # -- Header row
        header = QWidget()
        hl = QHBoxLayout(header)
        hl.setContentsMargins(0, 0, 0, 0)
        lbl = QLabel("<b>Files</b>")
        hl.addWidget(lbl)
        hl.addStretch()
        up_btn = QPushButton("↑ Up")
        up_btn.setFixedWidth(55)
        up_btn.clicked.connect(self._go_up)
        hl.addWidget(up_btn)
        layout.addWidget(header)

        # -- Path bar
        self._path_edit = QLineEdit()
        self._path_edit.setPlaceholderText("Directory path…")
        self._path_edit.returnPressed.connect(
            lambda: self._navigate(self._path_edit.text()))
        layout.addWidget(self._path_edit)

        # -- Tree
        self._fs_model = QFileSystemModel()
        self._fs_model.setRootPath(QDir.rootPath())
        self._fs_model.setFilter(
            QDir.Filter.AllDirs | QDir.Filter.Files | QDir.Filter.NoDotAndDotDot
        )

        self._proxy = ImageFilterProxy()
        self._proxy.setSourceModel(self._fs_model)

        self._tree = _DraggableTreeView()
        self._tree.setModel(self._proxy)
        self._tree.setHeaderHidden(False)
        self._tree.hideColumn(1)
        self._tree.hideColumn(2)
        self._tree.hideColumn(3)
        self._tree.setDragEnabled(True)
        self._tree.setDragDropMode(QTreeView.DragDropMode.DragOnly)

        # Navigate to Pictures folder initially, fall back to home
        pictures = QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.PicturesLocation
        )
        start = pictures if pictures else QDir.homePath()
        self._navigate(start)

        self._tree.doubleClicked.connect(self._on_double_click)
        layout.addWidget(self._tree)

    # ------------------------------------------------------------------

    def _navigate(self, path: str) -> None:
        p = Path(path)
        if not p.is_dir():
            return
        self._path_edit.setText(str(p))
        src_idx = self._fs_model.index(str(p))
        proxy_idx = self._proxy.mapFromSource(src_idx)
        self._tree.setRootIndex(proxy_idx)

    def _go_up(self) -> None:
        cur = Path(self._path_edit.text())
        self._navigate(str(cur.parent))

    def _on_double_click(self, proxy_idx: QModelIndex) -> None:
        src_idx = self._proxy.mapToSource(proxy_idx)
        if self._fs_model.isDir(src_idx):
            self._navigate(self._fs_model.filePath(src_idx))


# ------------------------------------------------------------------

class _DraggableTreeView(QTreeView):
    """Tree view that starts a URL-based drag on image files."""

    def startDrag(self, supported_actions: Qt.DropAction) -> None:
        indexes = self.selectedIndexes()
        if not indexes:
            return

        model: QFileSystemModel = self.model().sourceModel()  # type: ignore
        proxy: ImageFilterProxy = self.model()  # type: ignore

        urls: list[QUrl] = []
        for proxy_idx in indexes:
            if proxy_idx.column() != 0:
                continue
            src_idx = proxy.mapToSource(proxy_idx)
            path = model.filePath(src_idx)
            if not model.isDir(src_idx):
                urls.append(QUrl.fromLocalFile(path))

        if not urls:
            return

        mime = QMimeData()
        mime.setUrls(urls)
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.CopyAction)
