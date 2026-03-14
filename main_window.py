"""
Main application window.

Layout:
    ┌───────────────────────────────────────────────────┐
    │  Settings bar (top)                               │
    ├──────────────┬────────────────────────────────────┤
    │  Collection  │  Collage Workspace                 │
    │   (left)     │   (right)                          │
    └──────────────┴────────────────────────────────────┘
"""
from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import Qt, QSettings
from PySide6.QtWidgets import (
    QFileDialog, QMainWindow, QMessageBox,
    QSplitter, QVBoxLayout, QWidget,
)

from widgets.collection_panel import CollectionPanel
from widgets.collage_workspace import CollageWorkspace
from widgets.export_dialog import ExportDialog
from widgets.settings_bar import SettingsBar


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Fast Collage Creator")
        self.resize(1400, 860)
        self._settings = QSettings("FastCollageCreator", "MainWindow")
        self._project_path: str | None = None
        self._project_dir: str | None = None
        self._last_project_dir: str | None = self._load_last_project_dir()
        self._last_export_params: dict | None = None
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

        # -- Horizontal splitter for collection + workspace --
        self._splitter = QSplitter(Qt.Orientation.Horizontal)
        vbox.addWidget(self._splitter, stretch=1)

        self._collection = CollectionPanel()
        self._workspace = CollageWorkspace()

        self._splitter.addWidget(self._collection)
        self._splitter.addWidget(self._workspace)

        # Give the workspace most of the space
        self._splitter.setSizes([260, 1140])
        self._splitter.setChildrenCollapsible(False)

    def _connect_signals(self) -> None:
        sb = self._settings_bar
        sb.settings_changed.connect(self._workspace.apply_settings)
        sb.export_requested.connect(self._export)
        sb.save_requested.connect(self._save)
        sb.save_as_requested.connect(self._save_as)
        sb.load_requested.connect(self._load)
        sb.undo_requested.connect(self._workspace.undo)
        sb.redo_requested.connect(self._workspace.redo)

        # Apply initial settings
        self._workspace.apply_settings(self._settings_bar.settings())

    # ------------------------------------------------------------------
    # Save / Load / Export
    # ------------------------------------------------------------------

    def _save(self) -> None:
        if self._project_path:
            self._write_project(self._project_path)
        else:
            self._save_as()

    def _save_as(self) -> None:
        start_dir = self._project_start_dir()
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Project As", start_dir,
            "Collage Project (*.collage);;All Files (*)"
        )
        if not path:
            return
        self._write_project(path)

    def _write_project(self, path: str) -> None:
        data = self._workspace.save_project()
        # Persist the last used picker path alongside the project
        data["basepath"] = self._collection.last_path()
        data["collection"] = self._collection.paths()
        if self._last_export_params:
            data["export_settings"] = self._last_export_params
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            self._project_path = path
            self._project_dir = str(Path(path).parent)
            self._record_project_dir(self._project_dir)
            self._update_title()
        except OSError as exc:
            QMessageBox.critical(self, "Save Failed", str(exc))

    def _load(self) -> None:
        start_dir = self._project_start_dir()
        path, _ = QFileDialog.getOpenFileName(
            self, "Load Project", start_dir,
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
            # Restore picker base path saved with the project
            basepath = data.get("basepath", "")
            if basepath:
                self._collection.set_last_path(basepath)
            if "collection" in data:
                self._collection.set_paths(data.get("collection", []))
            self._last_export_params = data.get("export_settings", None)
            if self._last_export_params:
                ExportDialog._session_params = self._last_export_params
            self._project_path = path
            self._project_dir = str(Path(path).parent)
            self._record_project_dir(self._project_dir)
            self._update_title()
        except (OSError, KeyError, ValueError) as exc:
            QMessageBox.critical(self, "Load Failed", str(exc))

    def _export(self) -> None:
        cs = self._settings_bar.settings()
        default_dir = self._project_dir or self._collection.last_path() or str(Path.home())
        default_basename = Path(self._project_path).stem if self._project_path else "collage"
        dlg = ExportDialog(
            aspect_w=cs.aspect_w,
            aspect_h=cs.aspect_h,
            default_dir=default_dir,
            default_basename=default_basename,
            preset_params=self._last_export_params,
            transparent_bg=cs.transparent_bg,
            parent=self,
        )
        if dlg.exec() != ExportDialog.DialogCode.Accepted:
            return

        p = dlg.get_params()
        path = p["path"]
        if not path:
            return

        # Persist export settings in session and for project save
        self._last_export_params = p

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
                         )
            elif fmt == "PNG":
                img.save(path, "PNG",
                         compress_level=p["compress_level"],
                         )
            elif fmt == "WebP":
                img.save(path, "WEBP",
                         quality=p["quality"],
                         lossless=p["lossless"])
            elif fmt == "TIFF":
                compression = p["compression"]
                img.save(path, "TIFF",
                         compression=None if compression == "none" else compression,
                         )
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
                f"Size: {img.width} × {img.height} px",
            )
        except OSError as exc:
            QMessageBox.critical(self, "Export Failed", str(exc))

    def _update_title(self) -> None:
        if self._project_path:
            name = Path(self._project_path).name
            self.setWindowTitle(f"Fast Collage Creator - {name}")
        else:
            self.setWindowTitle("Fast Collage Creator")

    def _project_start_dir(self) -> str:
        if self._project_dir and Path(self._project_dir).is_dir():
            return self._project_dir
        if self._last_project_dir and Path(self._last_project_dir).is_dir():
            return self._last_project_dir
        return str(Path.home())

    def _record_project_dir(self, dir_path: str) -> None:
        if dir_path and Path(dir_path).is_dir():
            self._last_project_dir = dir_path
            self._settings.setValue("project/last_dir", dir_path)

    def _load_last_project_dir(self) -> str | None:
        val = self._settings.value("project/last_dir", "") or ""
        if val and Path(val).is_dir():
            return str(val)
        return None
