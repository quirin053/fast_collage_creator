"""
Export dialog: lets the user configure output path, resolution (px) and
format-specific parameters before exporting. Resolution is locked to the
canvas aspect ratio.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QFormLayout, QGroupBox, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QSlider, QSpinBox,
    QStackedWidget, QVBoxLayout, QWidget, QFileDialog,
)

_SETTINGS_ORG  = "FastCollageCreator"
_SETTINGS_APP  = "ExportDialog"
_KEY_LAST_DIR  = "last_export_dir"
_KEY_FORMAT    = "last_format"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _gcd(a: int, b: int) -> int:
    while b:
        a, b = b, a % b
    return a


class ExportDialog(QDialog):
    """
    Returns export parameters via :meth:`get_params` after exec_().
    """

    # Keep overwrite preference for the lifetime of the app session
    _overwrite_default: bool = False
    _session_params: dict | None = None

    FORMATS = ["JPEG", "PNG", "WebP", "TIFF", "JPEG XL"]
    EXTS    = {
        "JPEG":     ".jpg",
        "PNG":      ".png",
        "WebP":     ".webp",
        "TIFF":     ".tiff",
        "JPEG XL":  ".jxl",
    }

    def __init__(
        self,
        aspect_w: int,
        aspect_h: int,
        default_dir: str = "",
        default_basename: str = "collage",
        preset_params: dict | None = None,
        transparent_bg: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Export Collage")
        self.setMinimumWidth(460)

        self._aspect_w = max(aspect_w, 1)
        self._aspect_h = max(aspect_h, 1)
        self._updating = False          # re-entrancy guard
        self._qs = QSettings(_SETTINGS_ORG, _SETTINGS_APP)

        # Determine starting directory
        saved_dir = self._qs.value(_KEY_LAST_DIR, "") or ""
        if not saved_dir or not Path(saved_dir).is_dir():
            saved_dir = default_dir if default_dir and Path(default_dir).is_dir() \
                        else str(Path.home())

        # Determine default export filename
        last_fmt  = self._qs.value(_KEY_FORMAT, "JPEG") or "JPEG"
        if last_fmt not in self.FORMATS:
            last_fmt = "JPEG"
        base = default_basename or "collage"
        default_name = base + self.EXTS.get(last_fmt, ".jpg")
        self._default_path = str(Path(saved_dir) / default_name)

        self._transparent_bg = transparent_bg
        self._overwrite = ExportDialog._overwrite_default
        self._final_path = self._default_path
        self._requested_path: str | None = None
        self._preset_params = preset_params or ExportDialog._session_params
        self._build_ui(last_fmt)

    # ===================================================================
    # Build UI
    # ===================================================================

    def _build_ui(self, initial_format: str) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(10)

        # ---- Output path ------------------------------------------
        path_group = QGroupBox("Output file")
        pfl = QFormLayout(path_group)
        pfl.setContentsMargins(8, 8, 8, 8)

        path_row = QWidget()
        phl = QHBoxLayout(path_row)
        phl.setContentsMargins(0, 0, 0, 0)
        self._path_edit = QLineEdit(self._default_path)
        if self._preset_params and self._preset_params.get("path"):
            self._path_edit.setText(self._preset_params.get("path"))
        phl.addWidget(self._path_edit)
        browse_btn = QPushButton("…")
        browse_btn.setFixedWidth(30)
        browse_btn.clicked.connect(self._browse)
        phl.addWidget(browse_btn)
        pfl.addRow("Path:", path_row)
        self._overwrite_cb = QCheckBox("Overwrite output file")
        self._overwrite_cb.setChecked(self._overwrite)
        pfl.addRow("", self._overwrite_cb)
        root.addWidget(path_group)

        # ---- Format -----------------------------------------------
        fmt_group = QGroupBox("Format")
        ffl = QFormLayout(fmt_group)
        ffl.setContentsMargins(8, 8, 8, 8)
        self._fmt_combo = QComboBox()
        for f in self.FORMATS:
            self._fmt_combo.addItem(f)
        self._fmt_combo.setCurrentText(initial_format)
        self._fmt_combo.currentTextChanged.connect(self._on_format_changed)
        ffl.addRow("Format:", self._fmt_combo)
        root.addWidget(fmt_group)

        # ---- Resolution -------------------------------------------
        res_group = QGroupBox("Resolution")
        rfl = QFormLayout(res_group)
        rfl.setContentsMargins(8, 8, 8, 8)

        # Width px
        self._w_spin = QSpinBox()
        self._w_spin.setRange(1, 99999)
        self._w_spin.setSuffix(" px")
        self._w_spin.valueChanged.connect(self._on_w_changed)
        rfl.addRow("Width:", self._w_spin)

        # Height px
        self._h_spin = QSpinBox()
        self._h_spin.setRange(1, 99999)
        self._h_spin.setSuffix(" px")
        self._h_spin.valueChanged.connect(self._on_h_changed)
        rfl.addRow("Height:", self._h_spin)

        # aspect ratio label
        g = _gcd(self._aspect_w, self._aspect_h)
        ar_str = f"{self._aspect_w // g} : {self._aspect_h // g}"
        rfl.addRow("Aspect ratio:", QLabel(ar_str))

        root.addWidget(res_group)

        # Set default pixel values (Full HD equivalent kept to aspect)
        self._set_width_px(6000 if self._aspect_w >= self._aspect_h
                          else round(6000 * self._aspect_w / self._aspect_h))

        # ---- Format-specific params --------------------------------
        params_group = QGroupBox("Format options")
        params_layout = QVBoxLayout(params_group)
        params_layout.setContentsMargins(8, 8, 8, 8)

        self._stack = QStackedWidget()

        # JPEG
        jpeg_w = QWidget()
        jfl = QFormLayout(jpeg_w)
        jfl.setContentsMargins(0, 0, 0, 0)
        self._jpeg_q_slider, self._jpeg_q_spin = _quality_row(jfl, "Quality:", 95)
        params_layout.addWidget(self._stack)
        self._stack.addWidget(jpeg_w)          # index 0

        # PNG
        png_w = QWidget()
        pflw = QFormLayout(png_w)
        pflw.setContentsMargins(0, 0, 0, 0)
        self._png_comp = QSpinBox()
        self._png_comp.setRange(0, 9)
        self._png_comp.setValue(6)
        self._png_comp.setToolTip("0 = no compression (fastest), 9 = max compression")
        pflw.addRow("Compression (0–9):", self._png_comp)
        self._stack.addWidget(png_w)           # index 1

        # WebP
        webp_w = QWidget()
        wfl = QFormLayout(webp_w)
        wfl.setContentsMargins(0, 0, 0, 0)
        self._webp_lossless = QCheckBox("Lossless")
        self._webp_lossless.toggled.connect(
            lambda on: self._webp_q_slider.setEnabled(not on))
        wfl.addRow("", self._webp_lossless)
        self._webp_q_slider, self._webp_q_spin = _quality_row(wfl, "Quality:", 90)
        self._stack.addWidget(webp_w)          # index 2

        # TIFF
        tiff_w = QWidget()
        tfl = QFormLayout(tiff_w)
        tfl.setContentsMargins(0, 0, 0, 0)
        self._tiff_comp = QComboBox()
        for c in ("none", "lzw", "deflate", "packbits"):
            self._tiff_comp.addItem(c)
        self._tiff_comp.setCurrentText("lzw")
        tfl.addRow("Compression:", self._tiff_comp)
        self._stack.addWidget(tiff_w)          # index 3

        # JPEG XL
        jxl_w = QWidget()
        xfl = QFormLayout(jxl_w)
        xfl.setContentsMargins(0, 0, 0, 0)
        self._jxl_lossless = QCheckBox("Lossless")
        self._jxl_lossless.toggled.connect(
            lambda on: self._jxl_q_slider.setEnabled(not on))
        xfl.addRow("", self._jxl_lossless)
        self._jxl_q_slider, self._jxl_q_spin = _quality_row(xfl, "Quality:", 90)
        self._stack.addWidget(jxl_w)           # index 4

        root.addWidget(params_group)

        # ---- Transparent background --------------------------------
        self._transp_cb = QCheckBox("Transparent background (PNG / WebP / JXL only)")
        self._transp_cb.setChecked(self._transparent_bg)
        root.addWidget(self._transp_cb)

        # Apply preset parameters if provided (session or project)
        if self._preset_params:
            self._apply_preset(self._preset_params)

        # ---- Buttons ----------------------------------------------
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self._on_ok)
        btns.rejected.connect(self.reject)
        root.addWidget(btns)

        # Switch stack to initial format
        self._on_format_changed(initial_format)

    # ===================================================================
    # Events
    # ===================================================================

    def _on_format_changed(self, fmt: str) -> None:
        idx = self.FORMATS.index(fmt) if fmt in self.FORMATS else 0
        self._stack.setCurrentIndex(idx)
        # Update file extension in path
        cur = Path(self._path_edit.text())
        new_ext = self.EXTS.get(fmt, ".jpg")
        self._path_edit.setText(str(cur.with_suffix(new_ext)))

    def _browse(self) -> None:
        cur = Path(self._path_edit.text())
        fmt = self._fmt_combo.currentText()
        ext = self.EXTS.get(fmt, ".jpg")
        filters = {
            "JPEG":    "JPEG (*.jpg *.jpeg)",
            "PNG":     "PNG (*.png)",
            "WebP":    "WebP (*.webp)",
            "TIFF":    "TIFF (*.tiff *.tif)",
            "JPEG XL": "JPEG XL (*.jxl)",
        }
        path, _ = QFileDialog.getSaveFileName(
            self, "Export as",
            str(cur),
            filters.get(fmt, "All Files (*)"),
        )
        if path:
            self._path_edit.setText(path)

    # -- Resolution synchronisation -----------------------------------

    def _set_width_px(self, w: int) -> None:
        """Set width and derive height from aspect ratio."""
        self._updating = True
        w = max(1, w)
        h = max(1, round(w * self._aspect_h / self._aspect_w))
        self._w_spin.setValue(w)
        self._h_spin.setValue(h)
        self._updating = False

    def _set_height_px(self, h: int) -> None:
        """Set height and derive width from aspect ratio."""
        self._updating = True
        h = max(1, h)
        w = max(1, round(h * self._aspect_w / self._aspect_h))
        self._w_spin.setValue(w)
        self._h_spin.setValue(h)
        self._updating = False

    def _on_w_changed(self, w: int) -> None:
        if self._updating:
            return
        self._set_width_px(w)

    def _on_h_changed(self, h: int) -> None:
        if self._updating:
            return
        self._set_height_px(h)

    # ===================================================================
    # Accept
    # ===================================================================

    def _on_ok(self) -> None:
        path = self._path_edit.text().strip()
        if not path:
            return
        ExportDialog._overwrite_default = self._overwrite_cb.isChecked()
        self._requested_path = path
        if self._overwrite_cb.isChecked():
            final_path = Path(path)
        else:
            final_path = self._unique_path(Path(path))
        self._final_path = str(final_path)
        # Persist settings
        self._qs.setValue(_KEY_LAST_DIR, str(final_path.parent))
        self._qs.setValue(_KEY_FORMAT, self._fmt_combo.currentText())
        session_params = self.get_params()
        # Store the user-requested path so the dialog reopens without suffixes
        session_params["requested_path"] = self._requested_path
        session_params["path"] = self._requested_path or session_params["path"]
        ExportDialog._session_params = session_params
        self.accept()

    def _unique_path(self, base: Path) -> Path:
        """Return a non-existing path by appending (1), (2), ... if needed."""
        if not base.exists():
            return base
        stem = base.stem
        suffix = base.suffix
        parent = base.parent
        idx = 1
        while True:
            candidate = parent / f"{stem} ({idx}){suffix}"
            if not candidate.exists():
                return candidate
            idx += 1
    # ===================================================================
    # Public result
    # ===================================================================

    def get_params(self) -> dict:
        """Return a dict with all export parameters."""
        fmt = self._fmt_combo.currentText()
        params: dict = {
            "path":         self._final_path,
            "requested_path": self._requested_path or self._path_edit.text().strip(),
            "format":       fmt,
            "width":        self._w_spin.value(),
            "height":       self._h_spin.value(),
            "transparent":  self._transp_cb.isChecked(),
        }
        if fmt == "JPEG":
            params["quality"] = self._jpeg_q_spin.value()
        elif fmt == "PNG":
            params["compress_level"] = self._png_comp.value()
        elif fmt == "WebP":
            params["quality"]  = self._webp_q_spin.value()
            params["lossless"] = self._webp_lossless.isChecked()
        elif fmt == "TIFF":
            params["compression"] = self._tiff_comp.currentText()
        elif fmt == "JPEG XL":
            params["quality"]  = self._jxl_q_spin.value()
            params["lossless"] = self._jxl_lossless.isChecked()
        return params

    def _apply_preset(self, params: dict) -> None:
        self._updating = True
        fmt = params.get("format")
        if fmt and fmt in self.FORMATS:
            self._fmt_combo.setCurrentText(fmt)
        w = params.get("width")
        h = params.get("height")
        if isinstance(w, int) and w > 0:
            self._set_width_px(w)
        elif isinstance(h, int) and h > 0:
            self._set_height_px(h)
        transp = params.get("transparent")
        if isinstance(transp, bool):
            self._transp_cb.setChecked(transp)

        # Format-specific
        if fmt == "JPEG":
            q = params.get("quality")
            if isinstance(q, int):
                self._jpeg_q_spin.setValue(max(1, min(100, q)))
        elif fmt == "PNG":
            comp = params.get("compress_level")
            if isinstance(comp, int):
                self._png_comp.setValue(max(0, min(9, comp)))
        elif fmt == "WebP":
            q = params.get("quality")
            if isinstance(q, int):
                self._webp_q_spin.setValue(max(1, min(100, q)))
            lossless = params.get("lossless")
            if isinstance(lossless, bool):
                self._webp_lossless.setChecked(lossless)
        elif fmt == "TIFF":
            comp = params.get("compression")
            if isinstance(comp, str) and comp in ("none", "lzw", "deflate", "packbits"):
                self._tiff_comp.setCurrentText(comp)
        elif fmt == "JPEG XL":
            q = params.get("quality")
            if isinstance(q, int):
                self._jxl_q_spin.setValue(max(1, min(100, q)))
            lossless = params.get("lossless")
            if isinstance(lossless, bool):
                self._jxl_lossless.setChecked(lossless)

        # Path override
        path_for_ui = params.get("requested_path") or params.get("path")
        if path_for_ui:
            self._path_edit.setText(path_for_ui)
        self._updating = False


# ---------------------------------------------------------------------------
# Helper: linked quality slider + spinbox
# ---------------------------------------------------------------------------

def _quality_row(
    form: "QFormLayout",
    label: str,
    default: int,
) -> tuple[QSlider, QSpinBox]:
    row = QWidget()
    hl  = QHBoxLayout(row)
    hl.setContentsMargins(0, 0, 0, 0)
    slider = QSlider(Qt.Orientation.Horizontal)
    slider.setRange(1, 100)
    slider.setValue(default)
    spin = QSpinBox()
    spin.setRange(1, 100)
    spin.setValue(default)
    spin.setFixedWidth(52)
    slider.valueChanged.connect(spin.setValue)
    spin.valueChanged.connect(slider.setValue)
    hl.addWidget(slider)
    hl.addWidget(spin)
    form.addRow(label, row)
    return slider, spin
