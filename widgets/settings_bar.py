"""
Top settings bar: canvas dimensions, gap size, background colour, export.
"""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox, QColorDialog, QComboBox, QHBoxLayout, QLabel,
    QPushButton, QSpinBox, QToolButton, QWidget,
)


@dataclass
class CanvasSettings:
    width: int = 1920
    height: int = 1080
    gap_px: int = 8          # gap between cells in the exported image
    background: QColor = None  # colour shown behind cells / in gaps
    border_width_ui: int = 4  # hit-width of draggable borders in the UI
    transparent_bg: bool = False  # export with transparent background

    def __post_init__(self):
        if self.background is None:
            self.background = QColor("#ffffff")


class SettingsBar(QWidget):
    """Emits settings_changed whenever any value changes."""

    settings_changed = Signal(CanvasSettings)
    export_requested = Signal()
    save_requested = Signal()
    load_requested = Signal()
    undo_requested = Signal()
    redo_requested = Signal()

    # Common presets (label → (w, h))
    _PRESETS: dict[str, tuple[int, int]] = {
        "Custom": (0, 0),
        "Full HD  1920×1080": (1920, 1080),
        "4K       3840×2160": (3840, 2160),
        "Square   2000×2000": (2000, 2000),
        "A4 300dpi 2480×3508": (2480, 3508),
        "Instagram 1:1 1080×1080": (1080, 1080),
        "Instagram 4:5 1080×1350": (1080, 1350),
        "Instagram 16:9 1080×608": (1080, 608),
    }

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._settings = CanvasSettings()
        self._building = False
        self._build_ui()

    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        self._building = True
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(8)

        # Preset combo
        layout.addWidget(QLabel("Preset:"))
        self._preset_combo = QComboBox()
        for label in self._PRESETS:
            self._preset_combo.addItem(label)
        self._preset_combo.setCurrentIndex(1)  # Full HD default
        self._preset_combo.currentIndexChanged.connect(self._on_preset)
        layout.addWidget(self._preset_combo)

        # Width / Height
        layout.addWidget(QLabel("W:"))
        self._w_spin = QSpinBox()
        self._w_spin.setRange(100, 99999)
        self._w_spin.setValue(self._settings.width)
        self._w_spin.setSuffix(" px")
        self._w_spin.valueChanged.connect(self._on_change)
        layout.addWidget(self._w_spin)

        layout.addWidget(QLabel("H:"))
        self._h_spin = QSpinBox()
        self._h_spin.setRange(100, 99999)
        self._h_spin.setValue(self._settings.height)
        self._h_spin.setSuffix(" px")
        self._h_spin.valueChanged.connect(self._on_change)
        layout.addWidget(self._h_spin)

        # Gap
        layout.addWidget(QLabel("Gap:"))
        self._gap_spin = QSpinBox()
        self._gap_spin.setRange(0, 200)
        self._gap_spin.setValue(self._settings.gap_px)
        self._gap_spin.setSuffix(" px")
        self._gap_spin.valueChanged.connect(self._on_change)
        layout.addWidget(self._gap_spin)

        # Background colour
        layout.addWidget(QLabel("BG:"))
        self._bg_btn = QToolButton()
        self._bg_btn.setFixedSize(28, 24)
        self._update_bg_btn()
        self._bg_btn.clicked.connect(self._pick_bg)
        layout.addWidget(self._bg_btn)

        # Transparent background checkbox
        self._transp_cb = QCheckBox("Transparent")
        self._transp_cb.setToolTip(
            "Export with transparent background (PNG / WebP only).\n"
            "Unsupported formats fall back to the colour above."
        )
        self._transp_cb.stateChanged.connect(self._on_change)
        layout.addWidget(self._transp_cb)

        layout.addStretch()

        # Undo / Redo
        undo_btn = QPushButton("↩ Undo")
        undo_btn.clicked.connect(self.undo_requested)
        layout.addWidget(undo_btn)
        redo_btn = QPushButton("↪ Redo")
        redo_btn.clicked.connect(self.redo_requested)
        layout.addWidget(redo_btn)

        # Save / Load
        save_btn = QPushButton("💾 Save")
        save_btn.clicked.connect(self.save_requested)
        layout.addWidget(save_btn)
        load_btn = QPushButton("📂 Load")
        load_btn.clicked.connect(self.load_requested)
        layout.addWidget(load_btn)

        # Export
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

    def settings(self) -> CanvasSettings:
        return self._settings

    def _update_bg_btn(self) -> None:
        c = self._settings.background
        self._bg_btn.setStyleSheet(
            f"background: {c.name()}; border: 1px solid #555;"
        )
        self._bg_btn.setToolTip(f"Background colour: {c.name()}")

    def _on_preset(self) -> None:
        if self._building:
            return
        label = self._preset_combo.currentText()
        w, h = self._PRESETS[label]
        if w == 0:
            return  # Custom – leave spinboxes as-is
        self._building = True
        self._w_spin.setValue(w)
        self._h_spin.setValue(h)
        self._building = False
        self._on_change()

    def _on_change(self) -> None:
        if self._building:
            return
        self._settings.width = self._w_spin.value()
        self._settings.height = self._h_spin.value()
        self._settings.gap_px = self._gap_spin.value()
        self._settings.transparent_bg = self._transp_cb.isChecked()
        self.settings_changed.emit(self._settings)

    def _pick_bg(self) -> None:
        colour = QColorDialog.getColor(
            self._settings.background, self, "Background colour"
        )
        if colour.isValid():
            self._settings.background = colour
            self._update_bg_btn()
            self.settings_changed.emit(self._settings)
