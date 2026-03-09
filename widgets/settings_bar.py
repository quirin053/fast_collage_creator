"""
Top settings bar: aspect ratio, gap size, background colour, undo/redo/save/load/export.

The canvas `CanvasSettings` still stores width/height for the workspace preview
(auto-computed from aspect ratio at a fixed preview resolution).
Actual export resolution is configured inside the export dialog.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from PySide6.QtCore import Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QColorDialog, QComboBox, QHBoxLayout, QLabel,
    QPushButton, QSpinBox, QToolButton, QWidget,
)


# ---------------------------------------------------------------------------
# Preview resolution: the long side of the workspace canvas (px)
# ---------------------------------------------------------------------------
_PREVIEW_LONG_SIDE = 1920


def _compute_preview_size(aw: int, ah: int) -> tuple[int, int]:
    """Return (width, height) for the preview canvas at _PREVIEW_LONG_SIDE."""
    if aw <= 0 or ah <= 0:
        return _PREVIEW_LONG_SIDE, _PREVIEW_LONG_SIDE
    if aw >= ah:
        w = _PREVIEW_LONG_SIDE
        h = max(1, round(w * ah / aw))
    else:
        h = _PREVIEW_LONG_SIDE
        w = max(1, round(h * aw / ah))
    return w, h


# ---------------------------------------------------------------------------
# Aspect ratio presets  (label → (aspect_w, aspect_h))
# ---------------------------------------------------------------------------
_ASPECT_PRESETS: dict[str, tuple[int, int]] = {
    "16 : 9":           (16, 9),
    "4 : 3":            (4, 3),
    "3 : 2":            (3, 2),
    "1 : 1  (Square)":  (1, 1),
    "4 : 5":            (4, 5),
    "9 : 16":           (9, 16),
    "3 : 4":            (3, 4),
    "A4  Portrait":     (210, 297),
    "A4  Landscape":    (297, 210),
    "Custom":           (0, 0),
}
_DEFAULT_PRESET = "16 : 9"


@dataclass
class CanvasSettings:
    # Aspect ratio (used by export dialog and workspace layout)
    aspect_w: int = 16
    aspect_h: int = 9
    # Preview dimensions (auto-derived; workspace uses these for rendering)
    width: int = field(init=False)
    height: int = field(init=False)
    # Gap between cells in the exported image (px)
    gap_px: int = 8
    # Background colour and hit-width of draggable borders
    background: QColor = None
    border_width_ui: int = 4
    # transparent_bg kept for backward compat with save/load
    transparent_bg: bool = False

    def __post_init__(self):
        if self.background is None:
            self.background = QColor("#ffffff")
        self.width, self.height = _compute_preview_size(self.aspect_w, self.aspect_h)

    def set_aspect(self, aw: int, ah: int) -> None:
        self.aspect_w = max(1, aw)
        self.aspect_h = max(1, ah)
        self.width, self.height = _compute_preview_size(self.aspect_w, self.aspect_h)


class SettingsBar(QWidget):
    """Emits settings_changed whenever any value changes."""

    settings_changed = Signal(CanvasSettings)
    export_requested = Signal()
    save_requested   = Signal()
    load_requested   = Signal()
    undo_requested   = Signal()
    redo_requested   = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._settings = CanvasSettings()
        self._building  = False
        self._build_ui()

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        self._building = True
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(8)

        # ---- Aspect-ratio preset combo ----------------------------
        layout.addWidget(QLabel("Aspect:"))
        self._aspect_combo = QComboBox()
        for label in _ASPECT_PRESETS:
            self._aspect_combo.addItem(label)
        self._aspect_combo.setCurrentText(_DEFAULT_PRESET)
        self._aspect_combo.currentTextChanged.connect(self._on_aspect_preset)
        layout.addWidget(self._aspect_combo)

        # ---- Custom ratio spinboxes (hidden when preset != Custom) ----
        self._wh_label = QLabel("W:H")
        layout.addWidget(self._wh_label)

        self._aw_spin = QSpinBox()
        self._aw_spin.setRange(1, 9999)
        self._aw_spin.setValue(self._settings.aspect_w)
        self._aw_spin.setFixedWidth(56)
        self._aw_spin.valueChanged.connect(self._on_custom_ratio)
        layout.addWidget(self._aw_spin)

        self._colon_label = QLabel(":")
        layout.addWidget(self._colon_label)

        self._ah_spin = QSpinBox()
        self._ah_spin.setRange(1, 9999)
        self._ah_spin.setValue(self._settings.aspect_h)
        self._ah_spin.setFixedWidth(56)
        self._ah_spin.valueChanged.connect(self._on_custom_ratio)
        layout.addWidget(self._ah_spin)

        # Hide custom inputs initially (16:9 is the default)
        self._set_custom_visible(False)

        # ---- Gap --------------------------------------------------
        layout.addWidget(QLabel("Gap:"))
        self._gap_spin = QSpinBox()
        self._gap_spin.setRange(0, 200)
        self._gap_spin.setValue(self._settings.gap_px)
        self._gap_spin.setSuffix(" px")
        self._gap_spin.valueChanged.connect(self._on_change)
        layout.addWidget(self._gap_spin)

        # ---- Background colour ------------------------------------
        layout.addWidget(QLabel("BG:"))
        self._bg_btn = QToolButton()
        self._bg_btn.setFixedSize(28, 24)
        self._update_bg_btn()
        self._bg_btn.clicked.connect(self._pick_bg)
        layout.addWidget(self._bg_btn)

        layout.addStretch()

        # ---- Undo / Redo ------------------------------------------
        undo_btn = QPushButton("↩ Undo")
        undo_btn.clicked.connect(self.undo_requested)
        layout.addWidget(undo_btn)
        redo_btn = QPushButton("↪ Redo")
        redo_btn.clicked.connect(self.redo_requested)
        layout.addWidget(redo_btn)

        # ---- Save / Load ------------------------------------------
        save_btn = QPushButton("💾 Save")
        save_btn.clicked.connect(self.save_requested)
        layout.addWidget(save_btn)
        load_btn = QPushButton("📂 Load")
        load_btn.clicked.connect(self.load_requested)
        layout.addWidget(load_btn)

        # ---- Export -----------------------------------------------
        export_btn = QPushButton("⬇ Export")
        export_btn.setStyleSheet(
            "QPushButton { background: #2d8a4e; color: white; "
            "font-weight: bold; padding: 4px 12px; border-radius: 4px; }"
            "QPushButton:hover { background: #37a85f; }"
        )
        export_btn.clicked.connect(self.export_requested)
        layout.addWidget(export_btn)

        self._building = False

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _set_custom_visible(self, visible: bool) -> None:
        for w in (self._wh_label, self._aw_spin, self._colon_label, self._ah_spin):
            w.setVisible(visible)

    def settings(self) -> CanvasSettings:
        return self._settings

    def _update_bg_btn(self) -> None:
        c = self._settings.background
        self._bg_btn.setStyleSheet(
            f"background: {c.name()}; border: 1px solid #555;"
        )
        self._bg_btn.setToolTip(f"Background colour: {c.name()}")

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def _on_aspect_preset(self, label: str) -> None:
        if self._building:
            return
        aw, ah = _ASPECT_PRESETS.get(label, (0, 0))
        is_custom = (aw == 0)
        self._set_custom_visible(is_custom)
        if is_custom:
            self._on_custom_ratio()
            return
        self._building = True
        self._aw_spin.setValue(aw)
        self._ah_spin.setValue(ah)
        self._building = False
        self._settings.set_aspect(aw, ah)
        self.settings_changed.emit(self._settings)

    def _on_custom_ratio(self) -> None:
        if self._building:
            return
        self._settings.set_aspect(self._aw_spin.value(), self._ah_spin.value())
        self.settings_changed.emit(self._settings)

    def _on_change(self) -> None:
        if self._building:
            return
        self._settings.gap_px = self._gap_spin.value()
        self.settings_changed.emit(self._settings)

    def _pick_bg(self) -> None:
        colour = QColorDialog.getColor(
            self._settings.background, self, "Background colour"
        )
        if colour.isValid():
            self._settings.background = colour
            self._update_bg_btn()
            self.settings_changed.emit(self._settings)

    # ------------------------------------------------------------------
    # Programmatic update (e.g. after loading a project)
    # ------------------------------------------------------------------

    def apply_settings(self, cs: "CanvasSettings") -> None:
        """Sync the settings bar UI to the given CanvasSettings."""
        from math import gcd
        self._building = True
        try:
            # Find a matching preset by reducing the aspect ratio with GCD
            g = gcd(cs.aspect_w, cs.aspect_h)
            aw, ah = cs.aspect_w // g, cs.aspect_h // g
            matched_label: str | None = None
            for label, (pw, ph) in _ASPECT_PRESETS.items():
                if pw == 0:
                    continue
                pg = gcd(pw, ph)
                if pw // pg == aw and ph // pg == ah:
                    matched_label = label
                    break
            if matched_label:
                self._aspect_combo.setCurrentText(matched_label)
                self._set_custom_visible(False)
            else:
                self._aspect_combo.setCurrentText("Custom")
                self._aw_spin.setValue(cs.aspect_w)
                self._ah_spin.setValue(cs.aspect_h)
                self._set_custom_visible(True)

            self._gap_spin.setValue(cs.gap_px)
            self._settings.aspect_w = cs.aspect_w
            self._settings.aspect_h = cs.aspect_h
            self._settings.gap_px   = cs.gap_px
            self._settings.background = cs.background
            self._update_bg_btn()
        finally:
            self._building = False
