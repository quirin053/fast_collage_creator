"""
Collage workspace widget.

Responsibilities:
  - Render the BSP-tree layout (cells + images) using QPainter
  - Allow draggable borders (shared borders move together; Shift = single)
  - Allow pan/zoom of images within their cells (mouse drag + scroll)
  - Accept image drops onto cells
  - Provide a context-menu to split/remove cells, clear/rotate images
  - Provide undo/redo via a simple snapshot stack
"""
from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from PySide6.QtCore import (
    QPoint, QPointF, QRect, QRectF, Qt, QUrl, Signal,
)
from PySide6.QtGui import (
    QBrush, QColor, QContextMenuEvent, QCursor, QDragEnterEvent,
    QDragMoveEvent, QDropEvent, QKeyEvent, QMouseEvent, QPainter,
    QPen, QPixmap, QWheelEvent,
)
from PySide6.QtWidgets import QMenu, QWidget

from models.bsp_tree import (
    ImageState, LeafNode, Node, SplitDirection, SplitNode,
    all_leaves, all_splits, make_default_tree,
    node_from_dict, node_to_dict,
    remove_leaf, split_leaf, update_leaf_image,
)
from utils.image_utils import thumbnail_cache
from widgets.settings_bar import CanvasSettings

# -----------------------------------------------------------------------
# Constants
# -----------------------------------------------------------------------
HIT_RADIUS = 6        # pixels – how close to a border the cursor must be
ALIGN_TOL = 2         # pixels – tolerance for grouping co-linear borders
MAX_UNDO = 50         # maximum undo steps
THUMB_MAX = 1024      # max dimension for in-canvas preview thumbnails


# -----------------------------------------------------------------------
# Data classes
# -----------------------------------------------------------------------
@dataclass
class BorderInfo:
    """Describes one draggable border produced by a SplitNode."""
    node_id: str
    direction: SplitDirection   # direction of the SPLIT (H=left|right, V=top|bottom)
    # Absolute pixel position of the divider line
    # For HORIZONTAL split: x coordinate of the vertical line
    # For VERTICAL   split: y coordinate of the horizontal line
    position: float
    # The pixel rect of the split node's allocated area
    rect: QRect


@dataclass
class CellInfo:
    """Maps a leaf to its pixel rect in the workspace."""
    node_id: str
    rect: QRect


# -----------------------------------------------------------------------
# Collage Workspace
# -----------------------------------------------------------------------
class CollageWorkspace(QWidget):
    """The central canvas for building the collage."""

    tree_changed = Signal()         # emitted after any structural change

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self._settings: CanvasSettings = CanvasSettings()
        self._root: Node = make_default_tree()

        # Layout cache (rebuilt on repaint / resize)
        self._cells: list[CellInfo] = []
        self._borders: list[BorderInfo] = []

        # Drag state for borders
        self._dragging_borders: list[BorderInfo] = []
        self._drag_start_pos: float = 0.0         # absolute pixel at drag start
        self._drag_start_ratios: dict[str, float] = {}  # node_id → original ratio

        # Drag state for image pan
        self._panning_cell: Optional[str] = None  # leaf node_id
        self._pan_start_mouse: QPoint = QPoint()
        self._pan_start_value: tuple[float, float] = (0.0, 0.0)

        # Hover state
        self._hovered_border: Optional[BorderInfo] = None
        self._hovered_cell: Optional[str] = None

        # Drop highlight
        self._drop_target_cell: Optional[str] = None

        # Undo stack (stores serialised trees)
        self._undo_stack: list[dict] = []
        self._redo_stack: list[dict] = []
        self._push_undo()   # save initial state

        # Background fill
        self.setAutoFillBackground(True)
        bg = self.palette()
        bg.setColor(self.backgroundRole(), QColor("#3a3a3a"))
        self.setPalette(bg)

    # ===================================================================
    # Public API
    # ===================================================================

    def apply_settings(self, settings: CanvasSettings) -> None:
        self._settings = settings
        self.update()

    def undo(self) -> None:
        if len(self._undo_stack) < 2:
            return
        self._redo_stack.append(self._undo_stack.pop())
        self._root = node_from_dict(copy.deepcopy(self._undo_stack[-1]))
        self._invalidate_layout()
        self.tree_changed.emit()

    def redo(self) -> None:
        if not self._redo_stack:
            return
        state = self._redo_stack.pop()
        self._undo_stack.append(state)
        self._root = node_from_dict(copy.deepcopy(state))
        self._invalidate_layout()
        self.tree_changed.emit()

    def save_project(self) -> dict:
        return {
            "version": 1,
            "settings": {
                "width": self._settings.width,
                "height": self._settings.height,
                "gap_px": self._settings.gap_px,
                "background": self._settings.background.name(),
            },
            "tree": node_to_dict(self._root),
        }

    def load_project(self, data: dict) -> None:
        self._push_undo()
        s = data.get("settings", {})
        from PySide6.QtGui import QColor
        self._settings.width = s.get("width", 1920)
        self._settings.height = s.get("height", 1080)
        self._settings.gap_px = s.get("gap_px", 8)
        self._settings.background = QColor(s.get("background", "#ffffff"))
        self._root = node_from_dict(data["tree"])
        self._invalidate_layout()
        self.tree_changed.emit()

    # ===================================================================
    # Layout computation
    # ===================================================================

    def _canvas_rect(self) -> QRect:
        """The pixel rect used for rendering inside the widget."""
        w, h = self.width(), self.height()
        aspect = self._settings.width / max(self._settings.height, 1)
        if w / max(h, 1) > aspect:
            rh = h - 20
            rw = int(rh * aspect)
        else:
            rw = w - 20
            rh = int(rw / aspect)
        rx = (w - rw) // 2
        ry = (h - rh) // 2
        return QRect(rx, ry, rw, rh)

    def _compute_layout(self) -> None:
        self._cells = []
        self._borders = []
        self._traverse(self._root, self._canvas_rect())

    def _traverse(self, node: Node, rect: QRect) -> None:
        if isinstance(node, LeafNode):
            self._cells.append(CellInfo(node.id, QRect(rect)))
            return
        # SplitNode
        if node.direction == SplitDirection.HORIZONTAL:
            # Vertical divider line  (left | right)
            split_x = rect.left() + node.ratio * rect.width()
            self._borders.append(BorderInfo(
                node_id=node.id,
                direction=SplitDirection.HORIZONTAL,
                position=split_x,
                rect=QRect(rect),
            ))
            left_rect = QRect(rect.left(), rect.top(),
                              int(split_x - rect.left()), rect.height())
            right_rect = QRect(int(split_x), rect.top(),
                               rect.right() - int(split_x) + 1, rect.height())
            self._traverse(node.first, left_rect)
            self._traverse(node.second, right_rect)
        else:
            # Horizontal divider line (top / bottom)
            split_y = rect.top() + node.ratio * rect.height()
            self._borders.append(BorderInfo(
                node_id=node.id,
                direction=SplitDirection.VERTICAL,
                position=split_y,
                rect=QRect(rect),
            ))
            top_rect = QRect(rect.left(), rect.top(),
                             rect.width(), int(split_y - rect.top()))
            bottom_rect = QRect(rect.left(), int(split_y),
                                rect.width(), rect.bottom() - int(split_y) + 1)
            self._traverse(node.first, top_rect)
            self._traverse(node.second, bottom_rect)

    def _invalidate_layout(self) -> None:
        self._cells = []
        self._borders = []
        self.update()

    # ===================================================================
    # Painting
    # ===================================================================

    def paintEvent(self, _event) -> None:  # noqa: N802
        self._compute_layout()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        canvas = self._canvas_rect()

        # -- Canvas background (gap colour)
        gap_colour = self._settings.background
        painter.fillRect(canvas, QBrush(gap_colour))

        gap = self._settings.gap_px
        # Scale gap from export-pixels to widget-pixels
        px_per_export_px = canvas.width() / max(self._settings.width, 1)
        ui_gap = max(1, int(gap * px_per_export_px))

        # -- Draw each cell
        for cell in self._cells:
            cell_rect = cell.rect.adjusted(
                ui_gap // 2, ui_gap // 2,
                -(ui_gap - ui_gap // 2), -(ui_gap - ui_gap // 2),
            )
            if cell_rect.width() < 1 or cell_rect.height() < 1:
                continue

            # Background of empty cell
            painter.fillRect(cell_rect,
                             QBrush(QColor("#555555") if cell.node_id != self._hovered_cell
                                    else QColor("#666666")))

            # Image
            leaf = self._get_leaf(cell.node_id)
            if leaf and leaf.image:
                self._draw_image(painter, leaf.image, cell_rect)
            else:
                # Empty placeholder
                pen = QPen(QColor("#888888"))
                pen.setStyle(Qt.PenStyle.DashLine)
                painter.setPen(pen)
                painter.drawRect(cell_rect.adjusted(2, 2, -2, -2))
                painter.setPen(QColor("#999999"))
                painter.drawText(cell_rect, Qt.AlignmentFlag.AlignCenter,
                                 "Drop image here")

            # Drop highlight overlay
            if cell.node_id == self._drop_target_cell:
                painter.fillRect(cell_rect,
                                 QBrush(QColor(100, 160, 255, 80)))
                pen = QPen(QColor(100, 160, 255), 3)
                painter.setPen(pen)
                painter.drawRect(cell_rect)

        # -- Draw borders
        for border in self._borders:
            is_hovered = (
                self._hovered_border is not None
                and self._hovered_border.node_id == border.node_id
            )
            is_dragging = any(
                b.node_id == border.node_id for b in self._dragging_borders
            )
            if is_dragging:
                colour = QColor("#ffcc00")
                width = 3
            elif is_hovered:
                colour = QColor("#aaddff")
                width = 2
            else:
                colour = gap_colour
                width = ui_gap

            pen = QPen(colour, width)
            painter.setPen(pen)
            p = int(border.position)
            r = border.rect
            if border.direction == SplitDirection.HORIZONTAL:
                painter.drawLine(p, r.top(), p, r.bottom())
            else:
                painter.drawLine(r.left(), p, r.right(), p)

        # -- Canvas border
        pen = QPen(QColor("#222222"), 1)
        painter.setPen(pen)
        painter.drawRect(canvas)

        painter.end()

    def _draw_image(self, painter: QPainter,
                    img_state: ImageState, rect: QRect) -> None:
        pixmap: Optional[QPixmap] = thumbnail_cache.load(
            img_state.path, THUMB_MAX)
        if pixmap is None or pixmap.isNull():
            return

        # Apply rotation if needed
        if img_state.rotation != 0:
            transform = painter.transform()
            cx = rect.center().x()
            cy = rect.center().y()
            painter.translate(cx, cy)
            painter.rotate(img_state.rotation)
            painter.translate(-cx, -cy)

        img_w = pixmap.width()
        img_h = pixmap.height()
        cell_w = rect.width()
        cell_h = rect.height()

        # "Cover" scale
        base_scale = max(cell_w / max(img_w, 1), cell_h / max(img_h, 1))
        scale = base_scale * img_state.zoom

        disp_w = img_w * scale
        disp_h = img_h * scale

        # Pan expressed as fraction of cell dimension
        # pan_x=0 → image centred horizontally
        offset_x = rect.left() + (cell_w - disp_w) / 2 + img_state.pan_x * cell_w
        offset_y = rect.top() + (cell_h - disp_h) / 2 + img_state.pan_y * cell_h

        target = QRectF(offset_x, offset_y, disp_w, disp_h)

        painter.save()
        painter.setClipRect(rect)
        painter.drawPixmap(target, pixmap, QRectF(pixmap.rect()))
        painter.restore()

        if img_state.rotation != 0:
            painter.setTransform(painter.transform().inverted()[0])

    # ===================================================================
    # Mouse events
    # ===================================================================

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        pos = event.position().toPoint()

        if event.button() == Qt.MouseButton.LeftButton:
            # Try to hit a border first
            border = self._border_at(pos)
            if border is not None:
                self._start_border_drag(border, pos, event.modifiers())
                return
            # Otherwise start panning inside a cell
            cell = self._cell_at(pos)
            if cell is not None:
                self._panning_cell = cell.node_id
                self._pan_start_mouse = pos
                leaf = self._get_leaf(cell.node_id)
                if leaf and leaf.image:
                    self._pan_start_value = (leaf.image.pan_x, leaf.image.pan_y)
                else:
                    self._pan_start_value = (0.0, 0.0)
                self.setCursor(QCursor(Qt.CursorShape.ClosedHandCursor))

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        pos = event.position().toPoint()

        if self._dragging_borders:
            self._update_border_drag(pos)
            return

        if self._panning_cell is not None:
            self._update_pan(pos)
            return

        # Update hover
        self._update_hover(pos)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            if self._dragging_borders:
                self._push_undo()
                self._dragging_borders = []
                self._drag_start_ratios = {}
                self.tree_changed.emit()
            if self._panning_cell is not None:
                self._push_undo()
                self._panning_cell = None
                self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802
        pos = event.position().toPoint()
        cell = self._cell_at(pos)
        if cell is None:
            return
        leaf = self._get_leaf(cell.node_id)
        if leaf is None or leaf.image is None:
            return

        delta = event.angleDelta().y()
        factor = 1.1 if delta > 0 else 1 / 1.1
        new_zoom = max(0.1, min(10.0, leaf.image.zoom * factor))

        new_image = copy.copy(leaf.image)
        new_image.zoom = new_zoom
        # Re-clamp pan for the new zoom level
        cw = max(cell.rect.width(), 1)
        ch = max(cell.rect.height(), 1)
        new_image.pan_x, new_image.pan_y = _clamp_pan(
            new_image.pan_x, new_image.pan_y, new_image, cw, ch)
        self._root = update_leaf_image(self._root, leaf.id, new_image)
        self._invalidate_layout()

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Z and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                self.redo()
            else:
                self.undo()
        elif event.key() == Qt.Key.Key_Y and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.redo()
        else:
            super().keyPressEvent(event)

    # ===================================================================
    # Context menu
    # ===================================================================

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:  # noqa: N802
        pos = event.pos()
        cell = self._cell_at(pos)
        if cell is None:
            return
        leaf = self._get_leaf(cell.node_id)
        if leaf is None:
            return

        menu = QMenu(self)

        # Split actions
        split_h = menu.addAction("Split Left | Right")
        split_v = menu.addAction("Split Top | Bottom")
        menu.addSeparator()

        # Remove cell
        can_remove = not isinstance(self._root, LeafNode) or self._root.id != leaf.id
        remove_act = menu.addAction("Remove Cell")
        remove_act.setEnabled(can_remove and _count_leaves(self._root) > 1)
        menu.addSeparator()

        # Image actions
        clear_act = menu.addAction("Clear Image")
        clear_act.setEnabled(leaf.image is not None)
        rotate_cw = menu.addAction("Rotate 90° CW")
        rotate_cw.setEnabled(leaf.image is not None)
        rotate_ccw = menu.addAction("Rotate 90° CCW")
        rotate_ccw.setEnabled(leaf.image is not None)
        fit_act = menu.addAction("Reset Pan / Zoom")
        fit_act.setEnabled(leaf.image is not None)

        chosen = menu.exec(event.globalPos())
        if chosen is None:
            return

        self._push_undo()
        if chosen == split_h:
            old_ids = {ln.id for ln in all_leaves(self._root)}
            self._root = split_leaf(
                self._root, leaf.id, SplitDirection.HORIZONTAL)
            self._copy_image_to_new_leaf(old_ids, leaf)
        elif chosen == split_v:
            old_ids = {ln.id for ln in all_leaves(self._root)}
            self._root = split_leaf(
                self._root, leaf.id, SplitDirection.VERTICAL)
            self._copy_image_to_new_leaf(old_ids, leaf)
        elif chosen == remove_act and can_remove:
            new_root = remove_leaf(self._root, leaf.id)
            if new_root is not None:
                self._root = new_root
        elif chosen == clear_act:
            self._root = update_leaf_image(self._root, leaf.id, None)
        elif chosen == rotate_cw and leaf.image:
            img = copy.copy(leaf.image)
            img.rotation = (img.rotation + 90) % 360
            self._root = update_leaf_image(self._root, leaf.id, img)
        elif chosen == rotate_ccw and leaf.image:
            img = copy.copy(leaf.image)
            img.rotation = (img.rotation - 90) % 360
            self._root = update_leaf_image(self._root, leaf.id, img)
        elif chosen == fit_act and leaf.image:
            img = copy.copy(leaf.image)
            img.pan_x, img.pan_y, img.zoom = 0.0, 0.0, 1.0
            self._root = update_leaf_image(self._root, leaf.id, img)

        self._invalidate_layout()
        self.tree_changed.emit()

    # ===================================================================
    # Drag & Drop (image files → cells)
    # ===================================================================

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            cell = self._cell_at(event.position().toPoint())
            self._drop_target_cell = cell.node_id if cell else None
            self.update()
            event.acceptProposedAction()

    def dragLeaveEvent(self, _event) -> None:  # noqa: N802
        self._drop_target_cell = None
        self.update()

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        self._drop_target_cell = None
        pos = event.position().toPoint()
        cell = self._cell_at(pos)
        if cell is None:
            self.update()
            return

        urls = [u for u in event.mimeData().urls() if u.isLocalFile()]
        if not urls:
            self.update()
            return

        # When multiple images are dragged onto one cell, use only the first
        path = urls[0].toLocalFile()
        self._push_undo()
        self._root = update_leaf_image(
            self._root, cell.node_id, ImageState(path=path))
        self._invalidate_layout()
        self.tree_changed.emit()
        event.acceptProposedAction()

    # ===================================================================
    # Border dragging helpers
    # ===================================================================

    def _start_border_drag(self, border: BorderInfo, pos: QPoint,
                           modifiers: Qt.KeyboardModifier) -> None:
        if border.direction == SplitDirection.HORIZONTAL:
            self._drag_start_pos = float(pos.x())
        else:
            self._drag_start_pos = float(pos.y())

        if modifiers & Qt.KeyboardModifier.ShiftModifier:
            grouped = [border]
        else:
            grouped = self._find_aligned_borders(border)

        self._dragging_borders = grouped
        # Store original ratios for each border
        self._drag_start_ratios = {}
        for b in grouped:
            node = self._get_split(b.node_id)
            if node:
                self._drag_start_ratios[b.node_id] = node.ratio

    def _update_border_drag(self, pos: QPoint) -> None:
        if not self._dragging_borders:
            return

        ref = self._dragging_borders[0]
        if ref.direction == SplitDirection.HORIZONTAL:
            current_pos = float(pos.x())
        else:
            current_pos = float(pos.y())

        delta = current_pos - self._drag_start_pos

        for b in self._dragging_borders:
            node = self._get_split(b.node_id)
            if node is None:
                continue
            original_ratio = self._drag_start_ratios.get(b.node_id, node.ratio)
            if b.direction == SplitDirection.HORIZONTAL:
                dim = b.rect.width()
                original_abs = b.rect.left() + original_ratio * dim
                new_abs = original_abs + delta
                new_ratio = (new_abs - b.rect.left()) / max(dim, 1)
            else:
                dim = b.rect.height()
                original_abs = b.rect.top() + original_ratio * dim
                new_abs = original_abs + delta
                new_ratio = (new_abs - b.rect.top()) / max(dim, 1)

            new_ratio = max(0.05, min(0.95, new_ratio))
            self._set_split_ratio(b.node_id, new_ratio)

        self._invalidate_layout()

    def _find_aligned_borders(self, target: BorderInfo) -> list[BorderInfo]:
        """Return all borders of the same orientation at the same pixel position."""
        result = [target]
        for b in self._borders:
            if b.node_id == target.node_id:
                continue
            if b.direction != target.direction:
                continue
            if abs(b.position - target.position) <= ALIGN_TOL:
                result.append(b)
        return result

    # ===================================================================
    # Hover
    # ===================================================================

    def _update_hover(self, pos: QPoint) -> None:
        border = self._border_at(pos)
        old_border = self._hovered_border
        self._hovered_border = border

        cell = self._cell_at(pos)
        old_cell = self._hovered_cell
        self._hovered_cell = cell.node_id if cell else None

        if border is not None:
            if border.direction == SplitDirection.HORIZONTAL:
                self.setCursor(QCursor(Qt.CursorShape.SizeHorCursor))
            else:
                self.setCursor(QCursor(Qt.CursorShape.SizeVerCursor))
        elif self._cell_at(pos) is not None:
            leaf = self._get_leaf(self._hovered_cell) if self._hovered_cell else None
            if leaf and leaf.image:
                self.setCursor(QCursor(Qt.CursorShape.OpenHandCursor))
            else:
                self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
        else:
            self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))

        if old_border != border or old_cell != self._hovered_cell:
            self.update()

    # ===================================================================
    # Pan helpers
    # ===================================================================

    def _update_pan(self, pos: QPoint) -> None:
        if self._panning_cell is None:
            return
        leaf = self._get_leaf(self._panning_cell)
        if leaf is None or leaf.image is None:
            return

        cell_info = next(
            (c for c in self._cells if c.node_id == self._panning_cell), None)
        if cell_info is None:
            return

        dx = pos.x() - self._pan_start_mouse.x()
        dy = pos.y() - self._pan_start_mouse.y()

        cw = max(cell_info.rect.width(), 1)
        ch = max(cell_info.rect.height(), 1)
        new_pan_x = self._pan_start_value[0] + dx / cw
        new_pan_y = self._pan_start_value[1] + dy / ch

        # Clamp so the image can never be dragged to reveal the cell background.
        new_pan_x, new_pan_y = _clamp_pan(
            new_pan_x, new_pan_y,
            leaf.image, cw, ch,
        )

        new_image = copy.copy(leaf.image)
        new_image.pan_x = new_pan_x
        new_image.pan_y = new_pan_y
        self._root = update_leaf_image(self._root, leaf.id, new_image)
        self._invalidate_layout()

    # ===================================================================
    # Hit testing
    # ===================================================================

    def _border_at(self, pos: QPoint) -> Optional[BorderInfo]:
        if not self._borders:
            self._compute_layout()
        best: Optional[BorderInfo] = None
        best_dist = HIT_RADIUS + 1
        for b in self._borders:
            if b.direction == SplitDirection.HORIZONTAL:
                # Vertical line at x = b.position, clamped to b.rect
                if b.rect.top() <= pos.y() <= b.rect.bottom():
                    dist = abs(pos.x() - b.position)
                    if dist < best_dist:
                        best_dist = dist
                        best = b
            else:
                if b.rect.left() <= pos.x() <= b.rect.right():
                    dist = abs(pos.y() - b.position)
                    if dist < best_dist:
                        best_dist = dist
                        best = b
        return best

    def _cell_at(self, pos: QPoint) -> Optional[CellInfo]:
        if not self._cells:
            self._compute_layout()
        for c in self._cells:
            if c.rect.contains(pos):
                return c
        return None

    # ===================================================================
    # Tree helpers
    # ===================================================================

    def _get_leaf(self, node_id: str) -> Optional[LeafNode]:
        from models.bsp_tree import find_node
        node = find_node(self._root, node_id)
        return node if isinstance(node, LeafNode) else None

    def _get_split(self, node_id: str) -> Optional[SplitNode]:
        from models.bsp_tree import find_node
        node = find_node(self._root, node_id)
        return node if isinstance(node, SplitNode) else None

    def _set_split_ratio(self, node_id: str, ratio: float) -> None:
        self._root = _set_ratio(self._root, node_id, ratio)

    def _copy_image_to_new_leaf(self, old_ids: set[str],
                                 source_leaf: LeafNode) -> None:
        """After a split, find the newly created leaf and give it the same
        image as *source_leaf* (so both halves show the same picture)."""
        if source_leaf.image is None:
            return
        new_ids = {ln.id for ln in all_leaves(self._root)}
        fresh = new_ids - old_ids
        for new_id in fresh:
            self._root = update_leaf_image(
                self._root, new_id, copy.deepcopy(source_leaf.image))

    # ===================================================================
    # Undo / redo
    # ===================================================================

    def _push_undo(self) -> None:
        state = node_to_dict(self._root)
        if self._undo_stack and self._undo_stack[-1] == state:
            return
        self._undo_stack.append(state)
        if len(self._undo_stack) > MAX_UNDO:
            self._undo_stack.pop(0)
        self._redo_stack.clear()

    # ===================================================================
    # Export
    # ===================================================================

    def export_image(self) -> Optional["PIL.Image.Image"]:  # noqa: F821
        """Render the collage at full export resolution using Pillow."""
        from PIL import Image as PILImage, ImageDraw

        W = self._settings.width
        H = self._settings.height
        gap = self._settings.gap_px
        bg = self._settings.background
        transparent = self._settings.transparent_bg

        if transparent:
            out = PILImage.new("RGBA", (W, H), (0, 0, 0, 0))
        else:
            out = PILImage.new(
                "RGB", (W, H),
                (bg.red(), bg.green(), bg.blue()),
            )

        # Compute layout at export scale
        root_rect = QRect(0, 0, W, H)
        cells: list[CellInfo] = []
        borders_dummy: list[BorderInfo] = []
        _traverse_export(self._root, root_rect, cells, borders_dummy)

        for cell in cells:
            r = cell.rect.adjusted(
                gap // 2, gap // 2,
                -(gap - gap // 2), -(gap - gap // 2),
            )
            if r.width() < 1 or r.height() < 1:
                continue
            leaf = self._get_leaf(cell.node_id)
            if leaf is None or leaf.image is None:
                if not transparent:
                    # Fill with a placeholder colour
                    region = PILImage.new(
                        "RGB", (r.width(), r.height()), (80, 80, 80))
                    out.paste(region, (r.left(), r.top()))
                continue

            try:
                from PIL import Image, ImageOps
                img = Image.open(leaf.image.path)
                img = ImageOps.exif_transpose(img)
                if leaf.image.rotation:
                    img = img.rotate(-leaf.image.rotation, expand=True)
                img = img.convert("RGBA" if transparent else "RGB")
            except Exception as exc:
                print(f"[export] cannot open {leaf.image.path}: {exc}")
                continue

            cw, ch = r.width(), r.height()
            iw, ih = img.size
            scale = max(cw / max(iw, 1), ch / max(ih, 1)) * leaf.image.zoom
            new_iw = max(1, int(iw * scale))
            new_ih = max(1, int(ih * scale))
            img = img.resize((new_iw, new_ih), PILImage.LANCZOS)

            ox = int((cw - new_iw) / 2 + leaf.image.pan_x * cw)
            oy = int((ch - new_ih) / 2 + leaf.image.pan_y * ch)

            # Clip to cell
            # Determine what portion of the resized image to paste
            src_x = max(0, -ox)
            src_y = max(0, -oy)
            dst_x = max(0, ox) + r.left()
            dst_y = max(0, oy) + r.top()
            src_w = min(new_iw - src_x, cw - max(0, ox))
            src_h = min(new_ih - src_y, ch - max(0, oy))
            if src_w > 0 and src_h > 0:
                crop = img.crop((src_x, src_y, src_x + src_w, src_y + src_h))
                if transparent:
                    out.paste(crop, (dst_x, dst_y), mask=crop.split()[3])
                else:
                    out.paste(crop, (dst_x, dst_y))

        return out


# ===================================================================
# Module-level helpers (avoid import issues)
# ===================================================================

def _clamp_pan(pan_x: float, pan_y: float,
               img_state: "ImageState",
               cell_w: int, cell_h: int) -> tuple[float, float]:
    """Return (pan_x, pan_y) clamped so the image always covers the cell.

    The display size is:
        disp_w = img_w * max(cell_w/img_w, cell_h/img_h) * zoom
    The furthest the image centre can shift without revealing the background
    on one side is half the overhang / cell_dim.
    """
    px = thumbnail_cache.get(img_state.path, THUMB_MAX)
    if px is None:
        px = thumbnail_cache.load(img_state.path, THUMB_MAX)
    if px is None or px.isNull():
        return 0.0, 0.0

    img_w = px.width()
    img_h = px.height()

    # Account for 90/270° rotation swapping dimensions
    if img_state.rotation in (90, 270):
        img_w, img_h = img_h, img_w

    if img_w <= 0 or img_h <= 0:
        return 0.0, 0.0

    zoom = img_state.zoom
    base_scale = max(cell_w / img_w, cell_h / img_h)
    scale = base_scale * zoom
    disp_w = img_w * scale
    disp_h = img_h * scale

    # Half-overhang as a fraction of cell size → max allowed pan
    max_pan_x = max(0.0, (disp_w - cell_w) / 2.0) / cell_w
    max_pan_y = max(0.0, (disp_h - cell_h) / 2.0) / cell_h

    pan_x = max(-max_pan_x, min(max_pan_x, pan_x))
    pan_y = max(-max_pan_y, min(max_pan_y, pan_y))
    return pan_x, pan_y


def _set_ratio(root: Node, node_id: str, ratio: float) -> Node:
    import copy
    if isinstance(root, LeafNode):
        return root
    if root.id == node_id:
        root = copy.copy(root)
        root.ratio = ratio
        return root
    root = copy.copy(root)
    root.first = _set_ratio(root.first, node_id, ratio)
    root.second = _set_ratio(root.second, node_id, ratio)
    return root


def _count_leaves(root: Node) -> int:
    if isinstance(root, LeafNode):
        return 1
    return _count_leaves(root.first) + _count_leaves(root.second)


def _traverse_export(node: Node, rect: QRect,
                     cells: list[CellInfo],
                     borders: list[BorderInfo]) -> None:
    if isinstance(node, LeafNode):
        cells.append(CellInfo(node.id, QRect(rect)))
        return
    if node.direction == SplitDirection.HORIZONTAL:
        split_x = rect.left() + node.ratio * rect.width()
        left_rect = QRect(rect.left(), rect.top(),
                          int(split_x - rect.left()), rect.height())
        right_rect = QRect(int(split_x), rect.top(),
                           rect.right() - int(split_x) + 1, rect.height())
        _traverse_export(node.first, left_rect, cells, borders)
        _traverse_export(node.second, right_rect, cells, borders)
    else:
        split_y = rect.top() + node.ratio * rect.height()
        top_rect = QRect(rect.left(), rect.top(),
                         rect.width(), int(split_y - rect.top()))
        bottom_rect = QRect(rect.left(), int(split_y),
                            rect.width(), rect.bottom() - int(split_y) + 1)
        _traverse_export(node.first, top_rect, cells, borders)
        _traverse_export(node.second, bottom_rect, cells, borders)
