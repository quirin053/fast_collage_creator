"""
Left panel: File-system explorer filtered to image files.
Supports drag-and-drop of images into the collection or workspace.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import (
    QDir, QMimeData, QModelIndex, QPoint, QSettings,
    QSortFilterProxyModel, QStandardPaths, Qt, QUrl,
    Signal, Slot,
)
from PySide6.QtGui import QDrag
from PySide6.QtWidgets import (
    QFileDialog, QFileSystemModel, QHBoxLayout, QLabel, QLineEdit,
    QMenu, QPushButton, QStyle, QTreeView, QVBoxLayout, QWidget,
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
    images_selected = Signal(list)  # list[str] – paths picked via file dialog

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumWidth(200)
        self._settings = QSettings("FastCollageCreator", "FileExplorer")
        self._model_initialized = False
        self._fs_model: QFileSystemModel | None = None
        self._proxy: ImageFilterProxy | None = None
        self._tree: _DraggableTreeView | None = None
        self._build_ui()

    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        """Build static UI shell (header + path bar). Tree is deferred."""
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
        browse_btn = QPushButton("📂 Browse")
        browse_btn.setToolTip("Choose root folder")
        browse_btn.clicked.connect(self._browse_folder)
        hl.addWidget(browse_btn)
        add_btn = QPushButton("＋ Add Images")
        add_btn.setToolTip("Pick image files and add them to the collection")
        add_btn.clicked.connect(self._add_images_via_picker)
        hl.addWidget(add_btn)
        up_btn = QPushButton("↑ Up")
        up_btn.setFixedWidth(55)
        up_btn.clicked.connect(self._go_up)
        hl.addWidget(up_btn)
        layout.addWidget(header)

        # -- Path bar
        path_row = QWidget()
        pl = QHBoxLayout(path_row)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.setSpacing(2)
        self._path_edit = QLineEdit()
        self._path_edit.setPlaceholderText("Directory path…")
        self._path_edit.returnPressed.connect(
            lambda: self.navigate_to(self._path_edit.text()))
        pl.addWidget(self._path_edit)
        go_btn = QPushButton()
        go_btn.setToolTip("Navigate to path")
        go_btn.setFixedWidth(26)
        go_btn.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon)
        )
        go_btn.clicked.connect(lambda: self.navigate_to(self._path_edit.text()))
        pl.addWidget(go_btn)
        layout.addWidget(path_row)

        # Tree placeholder – filled in showEvent
        self._tree_placeholder_layout = layout

    def _init_model(self) -> None:
        """Create the filesystem model and tree (called lazily on first show)."""
        if self._model_initialized:
            return
        self._model_initialized = True

        saved = self._settings.value(_SETTINGS_KEY, "") or ""
        has_saved = bool(saved and Path(saved).is_dir())
        start = saved if has_saved else ""

        if has_saved:
            self._path_edit.setText(start)

        # Use a concrete root for the model to avoid scanning the entire FS.
        # Falls back to home only as an internal model anchor (not shown).
        model_root = start if has_saved else QDir.homePath()
        self._fs_model = QFileSystemModel()
        self._fs_model.setFilter(
            QDir.Filter.AllDirs | QDir.Filter.Files | QDir.Filter.NoDotAndDotDot
        )
        self._fs_model.setRootPath(model_root)

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
        self._tree.customContextMenuRequested.connect(self._on_context_menu)
        self._tree.doubleClicked.connect(self._on_double_click)

        self._tree_placeholder_layout.addWidget(self._tree)
        # Re-apply the root index once the model finishes loading a directory
        # so folder icons are shown correctly (e.g. after pressing "Up").
        self._fs_model.directoryLoaded.connect(self._on_directory_loaded)
        if has_saved:
            self._apply_root(start)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._init_model()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def current_path(self) -> str:
        """Return the path currently shown as the tree root."""
        return self._path_edit.text()

    def navigate_to(self, path: str) -> None:
        """Navigate the tree to *path*, save it to persistent settings."""
        resolved = self._resolve_start_path(path)
        self._path_edit.setText(resolved)
        self._settings.setValue(_SETTINGS_KEY, resolved)
        if self._model_initialized:
            self._apply_root(resolved)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _apply_root(self, path: str) -> None:
        """Point the tree at *path*.  Only call after the model is ready."""
        # Always update the model root so going up past the initial scope works.
        self._fs_model.setRootPath(path)
        self._pending_root = path
        src_idx = self._fs_model.index(path)
        proxy_idx = self._proxy.mapFromSource(src_idx)
        self._tree.setRootIndex(proxy_idx)

    @Slot(str)
    def _on_directory_loaded(self, loaded_path: str) -> None:
        """Re-set tree root index after the model loads a directory.
        This ensures folder icons appear even for newly scoped directories."""
        pending = getattr(self, "_pending_root", None)
        if pending and Path(loaded_path) == Path(pending):
            src_idx = self._fs_model.index(pending)
            proxy_idx = self._proxy.mapFromSource(src_idx)
            self._tree.setRootIndex(proxy_idx)

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

    def _browse_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self,
            "Choose Root Folder",
            self._path_edit.text() or QDir.homePath(),
            QFileDialog.Option.ShowDirsOnly
        )
        if folder:
            self.navigate_to(folder)

    def _add_images_via_picker(self) -> None:
        """Open a file picker for images and emit them to the collection."""
        ext_list = " ".join(f"*{e}" for e in sorted(SUPPORTED_EXTENSIONS))
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Select Images",
            self._path_edit.text() or QDir.homePath(),
            f"Images ({ext_list});;All Files (*)",
        )
        if files:
            # Navigate the tree to the folder of the first picked file
            first_dir = str(Path(files[0]).parent)
            self.navigate_to(first_dir)
            self.images_selected.emit(files)

    def _go_up(self) -> None:
        cur = Path(self._path_edit.text())
        parent = cur.parent
        # Avoid navigating above the filesystem root
        if parent != cur:
            self.navigate_to(str(parent))

    def _on_double_click(self, proxy_idx: QModelIndex) -> None:
        src_idx = self._proxy.mapToSource(proxy_idx)
        if self._fs_model.isDir(src_idx):
            self.navigate_to(self._fs_model.filePath(src_idx))
        else:
            path = self._fs_model.filePath(src_idx)
            suffix = Path(path).suffix.lower()
            if suffix in SUPPORTED_EXTENSIONS:
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
