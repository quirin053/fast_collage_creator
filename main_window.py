"""
Main application window.

Layout:
  ┌─────────────────────────────────────────────────────┐
  │  Settings bar (top)                                  │
  ├──────────────┬──────────────┬───────────────────────┤
  │ File Explorer│  Collection  │  Collage Workspace     │
  │   (left)     │   (centre)   │   (right)              │
  └──────────────┴──────────────┴───────────────────────┘
"""
from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog, QMainWindow, QMessageBox,
    QSplitter, QVBoxLayout, QWidget,
)

from widgets.collection_panel import CollectionPanel
from widgets.collage_workspace import CollageWorkspace
from widgets.export_dialog import ExportDialog
from widgets.file_explorer_panel import FileExplorerPanel
from widgets.settings_bar import SettingsBar


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Fast Collage Creator")
        self.resize(1400, 860)
        self._build_ui()
        self._connect_signals()

    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        # Central widget with vertical layout (settings top, rest below)
        central = QWidget()
        self.setCentralWidget(central)
        vbox = QVBoxLayout(central)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(0)

        # -- Top settings bar --
        self._settings_bar = SettingsBar()
        self._settings_bar.setFixedHeight(48)
        vbox.addWidget(self._settings_bar)

        # -- Horizontal splitter for the three panels --
        self._splitter = QSplitter(Qt.Orientation.Horizontal)
        vbox.addWidget(self._splitter, stretch=1)

        self._file_explorer = FileExplorerPanel()
        self._collection = CollectionPanel()
        self._workspace = CollageWorkspace()

        self._splitter.addWidget(self._file_explorer)
        self._splitter.addWidget(self._collection)
        self._splitter.addWidget(self._workspace)

        # Give the workspace most of the space
        self._splitter.setSizes([220, 200, 900])
        self._splitter.setChildrenCollapsible(False)

    def _connect_signals(self) -> None:
        sb = self._settings_bar
        sb.settings_changed.connect(self._workspace.apply_settings)
        sb.export_requested.connect(self._export)
        sb.save_requested.connect(self._save)
        sb.load_requested.connect(self._load)
        sb.undo_requested.connect(self._workspace.undo)
        sb.redo_requested.connect(self._workspace.redo)

        # Apply initial settings
        self._workspace.apply_settings(self._settings_bar.settings())

        # File explorer double-clicked
        self._file_explorer.image_double_clicked.connect(
            self._collection.add_image
        )
        # File explorer "Add Images" picker
        self._file_explorer.images_selected.connect(
            lambda paths: [self._collection.add_image(p) for p in paths]
        )

    # ------------------------------------------------------------------
    # Save / Load / Export
    # ------------------------------------------------------------------

    def _save(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Project", str(Path.home()),
            "Collage Project (*.collage);;All Files (*)"
        )
        if not path:
            return
        data = self._workspace.save_project()
        # Persist the current file-explorer base path alongside the project
        data["basepath"] = self._file_explorer.current_path()
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except OSError as exc:
            QMessageBox.critical(self, "Save Failed", str(exc))

    def _load(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Load Project", str(Path.home()),
            "Collage Project (*.collage);;All Files (*)"
        )
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            self._workspace.load_project(data)
            # Sync settings bar to reflect the loaded aspect ratio / gap / BG
            self._settings_bar.apply_settings(self._workspace.current_settings)
            # Restore file-explorer base path saved with the project
            basepath = data.get("basepath", "")
            if basepath:
                self._file_explorer.navigate_to(basepath)
        except (OSError, KeyError, ValueError) as exc:
            QMessageBox.critical(self, "Load Failed", str(exc))

    def _export(self) -> None:
        cs = self._settings_bar.settings()
        default_dir = self._file_explorer.current_path()
        dlg = ExportDialog(
            aspect_w=cs.aspect_w,
            aspect_h=cs.aspect_h,
            default_dir=default_dir,
            transparent_bg=cs.transparent_bg,
            parent=self,
        )
        if dlg.exec() != ExportDialog.DialogCode.Accepted:
            return

        p = dlg.get_params()
        path = p["path"]
        if not path:
            return

        img = self._workspace.export_image(
            width=p["width"],
            height=p["height"],
            transparent=p["transparent"],
        )
        if img is None:
            QMessageBox.critical(self, "Export Failed", "No image to export.")
            return

        fmt = p["format"]
        try:
            if fmt == "JPEG":
                if img.mode == "RGBA":
                    from PIL import Image as PILImage
                    bg_c = self._workspace._settings.background
                    flat = PILImage.new(
                        "RGB", img.size,
                        (bg_c.red(), bg_c.green(), bg_c.blue()),
                    )
                    flat.paste(img, mask=img.split()[3])
                    img = flat
                else:
                    img = img.convert("RGB")
                img.save(path, "JPEG", quality=p["quality"],
                         dpi=(p["dpi"], p["dpi"]))
            elif fmt == "PNG":
                img.save(path, "PNG",
                         compress_level=p["compress_level"],
                         dpi=(p["dpi"], p["dpi"]))
            elif fmt == "WebP":
                img.save(path, "WEBP",
                         quality=p["quality"],
                         lossless=p["lossless"])
            elif fmt == "TIFF":
                compression = p["compression"]
                img.save(path, "TIFF",
                         compression=None if compression == "none" else compression,
                         dpi=(p["dpi"], p["dpi"]))
            elif fmt == "JPEG XL":
                try:
                    save_kwargs = {"quality": p["quality"]}
                    if p["lossless"]:
                        save_kwargs["lossless"] = True
                    img.save(path, **save_kwargs)
                except Exception as exc:
                    QMessageBox.critical(self, "Export Failed",
                                         f"JPEG XL export failed:\n{exc}")
                    return
            else:
                img.save(path)

            QMessageBox.information(
                self, "Export Complete",
                f"Saved to:\n{path}\n"
                f"Size: {img.width} × {img.height} px  |  {p['dpi']} DPI",
            )
        except OSError as exc:
            QMessageBox.critical(self, "Export Failed", str(exc))
