"""
Left panel: File-system explorer filtered to image files.
Supports drag-and-drop of images into the collection or workspace.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import (
    QDir, QMimeData, QModelIndex, QPoint, QSettings,
    QSortFilterProxyModel, QStandardPaths, Qt, QUrl,
    Signal,
)
from PySide6.QtGui import QDrag
from PySide6.QtWidgets import (
    QFileSystemModel, QHBoxLayout, QLabel, QLineEdit,
    QMenu, QPushButton, QTreeView, QVBoxLayout, QWidget,
)

from utils.image_utils import SUPPORTED_EXTENSIONS

_SETTINGS_KEY = "file_explorer/last_path"


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

    image_double_clicked = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumWidth(200)
        self._settings = QSettings("FastCollageCreator", "FileExplorer")
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
            lambda: self.navigate_to(self._path_edit.text()))
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
        self._tree.setSelectionMode(
            QTreeView.SelectionMode.ExtendedSelection)
        self._tree.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(
            self._on_context_menu)

        # Navigate to saved / fallback path
        saved = self._settings.value(_SETTINGS_KEY, "") or ""
        self.navigate_to(self._resolve_start_path(saved))

        self._tree.doubleClicked.connect(self._on_double_click)
        layout.addWidget(self._tree)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def current_path(self) -> str:
        """Return the path currently shown as the tree root."""
        return self._path_edit.text()

    def navigate_to(self, path: str) -> None:
        """Navigate the tree to *path*, save it to persistent settings."""
        resolved = self._resolve_start_path(path)
        p = Path(resolved)
        self._path_edit.setText(str(p))
        src_idx = self._fs_model.index(str(p))
        proxy_idx = self._proxy.mapFromSource(src_idx)
        self._tree.setRootIndex(proxy_idx)
        self._settings.setValue(_SETTINGS_KEY, str(p))

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _resolve_start_path(self, preferred: str) -> str:
        """Return the first existing directory in the fallback chain:
        preferred → Pictures → home."""
        if preferred and Path(preferred).is_dir():
            return preferred
        pictures = QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.PicturesLocation
        )
        if pictures and Path(pictures).is_dir():
            return pictures
        return QDir.homePath()

    def _go_up(self) -> None:
        cur = Path(self._path_edit.text())
        self.navigate_to(str(cur.parent))

    def _on_double_click(self, proxy_idx: QModelIndex) -> None:
        src_idx = self._proxy.mapToSource(proxy_idx)
        if self._fs_model.isDir(src_idx):
            self.navigate_to(self._fs_model.filePath(src_idx))
        else:
            # print("Double-clicked file:", self._fs_model.filePath(src_idx))
            path = self._fs_model.filePath(src_idx)
            suffix = Path(path).suffix.lower()
            if suffix in SUPPORTED_EXTENSIONS:
                # print("Emitting double-clicked image path:", path)
                self.image_double_clicked.emit(path)

    def _on_context_menu(self, pos: QPoint) -> None:
        proxy_idx = self._tree.indexAt(pos)
        if not proxy_idx.isValid():
            return
        src_idx = self._proxy.mapToSource(proxy_idx)
        if not self._fs_model.isDir(src_idx):
            return
        folder_path = self._fs_model.filePath(src_idx)
        menu = QMenu(self)
        act = menu.addAction(f"📁  Set '{Path(folder_path).name}' as base path")
        chosen = menu.exec(self._tree.viewport().mapToGlobal(pos))
        if chosen is act:
            self.navigate_to(folder_path)


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
