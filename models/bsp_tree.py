"""
BSP (Binary Space Partitioning) tree model for the collage layout.

A tree node is either:
- LeafNode  : a cell that can hold an image
- SplitNode : a split into two sub-trees along a direction
"""
from __future__ import annotations

import copy
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Union


class SplitDirection(Enum):
    HORIZONTAL = "horizontal"  # split left | right
    VERTICAL = "vertical"      # split top  | bottom


@dataclass
class ImageState:
    """Stores image placement within a cell."""
    path: str
    # Pan in *normalised* cell coordinates (fraction of cell size).
    # (0, 0) centres the image.
    pan_x: float = 0.0
    pan_y: float = 0.0
    # Zoom multiplier on top of the default "cover" scale.
    zoom: float = 1.0
    # Rotation in degrees (0, 90, 180, 270)
    rotation: int = 0


@dataclass
class LeafNode:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    image: Optional[ImageState] = None

    def clone(self) -> "LeafNode":
        return copy.deepcopy(self)


@dataclass
class SplitNode:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    direction: SplitDirection = SplitDirection.HORIZONTAL
    # ratio is where the divider sits: 0.0 = all first, 1.0 = all second
    ratio: float = 0.5
    first: "Node" = None   # left  (H) or top    (V)
    second: "Node" = None  # right (H) or bottom (V)

    def clone(self) -> "SplitNode":
        return copy.deepcopy(self)


Node = Union[LeafNode, SplitNode]


# ---------------------------------------------------------------------------
# Tree helpers
# ---------------------------------------------------------------------------

def make_default_tree() -> SplitNode:
    """Return the initial two-cell layout (left | right)."""
    return SplitNode(
        direction=SplitDirection.HORIZONTAL,
        ratio=0.5,
        first=LeafNode(),
        second=LeafNode(),
    )


def split_leaf(root: Node, leaf_id: str,
               direction: SplitDirection) -> Node:
    """Replace the leaf with leaf_id by a new SplitNode containing two leaves
    (the original image stays in the first child)."""
    if isinstance(root, LeafNode):
        if root.id == leaf_id:
            existing = copy.deepcopy(root)
            new_leaf = LeafNode()
            return SplitNode(
                direction=direction,
                ratio=0.5,
                first=existing,
                second=new_leaf,
            )
        return root
    # SplitNode
    root = copy.copy(root)
    root.first = split_leaf(root.first, leaf_id, direction)
    root.second = split_leaf(root.second, leaf_id, direction)
    return root


def remove_leaf(root: Node, leaf_id: str) -> Optional[Node]:
    """Remove a leaf and replace its parent split with the sibling.
    Returns None if root itself is the only leaf and it matches."""
    if isinstance(root, LeafNode):
        return None if root.id == leaf_id else root

    # Check if either child is the target leaf
    if isinstance(root.first, LeafNode) and root.first.id == leaf_id:
        return root.second
    if isinstance(root.second, LeafNode) and root.second.id == leaf_id:
        return root.first

    root = copy.copy(root)
    root.first = remove_leaf(root.first, leaf_id)
    root.second = remove_leaf(root.second, leaf_id)
    return root


def find_node(root: Node, node_id: str) -> Optional[Node]:
    if root.id == node_id:
        return root
    if isinstance(root, SplitNode):
        result = find_node(root.first, node_id)
        if result:
            return result
        return find_node(root.second, node_id)
    return None


def update_leaf_image(root: Node, leaf_id: str,
                      image: Optional[ImageState]) -> Node:
    if isinstance(root, LeafNode):
        if root.id == leaf_id:
            root = copy.copy(root)
            root.image = image
        return root
    root = copy.copy(root)
    root.first = update_leaf_image(root.first, leaf_id, image)
    root.second = update_leaf_image(root.second, leaf_id, image)
    return root


def all_leaves(root: Node) -> list[LeafNode]:
    if isinstance(root, LeafNode):
        return [root]
    return all_leaves(root.first) + all_leaves(root.second)


def all_splits(root: Node) -> list[SplitNode]:
    if isinstance(root, LeafNode):
        return []
    return [root] + all_splits(root.first) + all_splits(root.second)


# ---------------------------------------------------------------------------
# Serialisation (plain dict / JSON-compatible)
# ---------------------------------------------------------------------------

def node_to_dict(node: Node) -> dict:
    if isinstance(node, LeafNode):
        img = None
        if node.image:
            img = {
                "path": node.image.path,
                "pan_x": node.image.pan_x,
                "pan_y": node.image.pan_y,
                "zoom": node.image.zoom,
                "rotation": node.image.rotation,
            }
        return {"type": "leaf", "id": node.id, "image": img}
    return {
        "type": "split",
        "id": node.id,
        "direction": node.direction.value,
        "ratio": node.ratio,
        "first": node_to_dict(node.first),
        "second": node_to_dict(node.second),
    }


def node_from_dict(d: dict) -> Node:
    if d["type"] == "leaf":
        img = None
        if d.get("image"):
            i = d["image"]
            img = ImageState(
                path=i["path"],
                pan_x=i.get("pan_x", 0.0),
                pan_y=i.get("pan_y", 0.0),
                zoom=i.get("zoom", 1.0),
                rotation=i.get("rotation", 0),
            )
        return LeafNode(id=d["id"], image=img)
    return SplitNode(
        id=d["id"],
        direction=SplitDirection(d["direction"]),
        ratio=d["ratio"],
        first=node_from_dict(d["first"]),
        second=node_from_dict(d["second"]),
    )


def _perp(d: SplitDirection) -> SplitDirection:
    """Return the perpendicular split direction."""
    if d == SplitDirection.HORIZONTAL:
        return SplitDirection.VERTICAL
    return SplitDirection.HORIZONTAL


# ---------------------------------------------------------------------------
# Rect helper (simple tuple: left, top, width, height)
# ---------------------------------------------------------------------------
Rect = tuple[float, float, float, float]  # (left, top, w, h)


def _split_rect(rect: Rect, direction: SplitDirection,
                ratio: float) -> tuple[Rect, Rect]:
    """Split *rect* into two sub-rects according to *direction* and *ratio*."""
    left, top, w, h = rect
    if direction == SplitDirection.HORIZONTAL:
        # Vertical divider – first = left, second = right
        w1 = w * ratio
        return (left, top, w1, h), (left + w1, top, w - w1, h)
    else:
        # Horizontal divider – first = top, second = bottom
        h1 = h * ratio
        return (left, top, w, h1), (left, top + h1, w, h - h1)


def _abs_position(rect: Rect, direction: SplitDirection,
                  ratio: float) -> float:
    """Absolute pixel position for a split inside *rect*."""
    left, top, w, h = rect
    if direction == SplitDirection.HORIZONTAL:
        return left + ratio * w
    else:
        return top + ratio * h


# ---------------------------------------------------------------------------
# Find parent of a node
# ---------------------------------------------------------------------------
def find_parent(root: Node, target_id: str) -> Optional[SplitNode]:
    """Return the SplitNode whose first or second child has id == target_id,
    or None if target_id is root."""
    if isinstance(root, LeafNode):
        return None
    if (root.first and root.first.id == target_id) or \
       (root.second and root.second.id == target_id):
        return root
    result = find_parent(root.first, target_id)
    if result:
        return result
    return find_parent(root.second, target_id)


# ---------------------------------------------------------------------------
# Split a border at its crossing point  (tree rotation, no cell duplication)
# ---------------------------------------------------------------------------
def rotate_split(root: Node, split_id: str) -> Optional[Node]:
    """Rotate the SplitNode so its border becomes two independent segments.

    Only succeeds when both children of the target are SplitNodes in the
    perpendicular direction with approximately equal ratios (~2% tolerance).

    Pattern (before):
      S(border_dir, ratio,
          first  = S(cross_dir, cross_r, A, B),
          second = S(cross_dir, cross_r, C, D))

    Result (after):
      S(cross_dir, cross_r,
          first  = S(border_dir, ratio, A, C),
          second = S(border_dir, ratio, B, D))

    Returns the updated tree, or ``None`` if the pattern does not match.
    No cells are created or duplicated — the four leaf subtrees (A, B, C, D)
    are simply rearranged.
    """
    node = find_node(root, split_id)
    if not isinstance(node, SplitNode):
        return None
    if not isinstance(node.first, SplitNode) or \
       not isinstance(node.second, SplitNode):
        return None

    a, b = node.first, node.second
    perp = _perp(node.direction)
    if a.direction != perp or b.direction != perp:
        return None
    if abs(a.ratio - b.ratio) > 0.02:
        return None

    avg_cross = (a.ratio + b.ratio) / 2.0

    replacement = SplitNode(
        direction=perp,
        ratio=avg_cross,
        first=SplitNode(
            direction=node.direction,
            ratio=node.ratio,
            first=a.first,
            second=b.first,
        ),
        second=SplitNode(
            direction=node.direction,
            ratio=node.ratio,
            first=a.second,
            second=b.second,
        ),
    )

    return _replace_node(root, split_id, replacement)


def _replace_node(root: Node, target_id: str, replacement: Node) -> Node:
    """Return a copy of *root* with the node matching *target_id* swapped
    for *replacement*."""
    if root.id == target_id:
        return replacement
    if isinstance(root, LeafNode):
        return root
    root = copy.copy(root)
    root.first = _replace_node(root.first, target_id, replacement)
    root.second = _replace_node(root.second, target_id, replacement)
    return root


# ---------------------------------------------------------------------------
# Merge two co-linear borders back into one  (reverse rotation)
# ---------------------------------------------------------------------------
def try_merge_borders(root: Node, id_a: str, id_b: str) -> Optional[Node]:
    """Attempt to merge two co-linear SplitNodes back into a unified border.

    The two nodes must be children (direct or indirect) of a common parent
    that splits perpendicular to them, and the parent's structure must match
    the pattern produced by ``split_border``.

    Returns a new tree if the merge succeeded, or None if not possible.
    """
    # Find the lowest common ancestor that is a direct parent of one of
    # the two nodes.  The typical pattern is:
    #   parent (cross_dir)
    #     first:  SplitNode a (border_dir, ratio ≈ same)
    #     second: SplitNode b (border_dir, ratio ≈ same)
    #
    # We search for a SplitNode whose first/second are SplitNodes with
    # ids matching id_a and id_b (or containing them).

    parent_a = find_parent(root, id_a)
    parent_b = find_parent(root, id_b)

    # Case 1: both are immediate children of the same parent
    if (parent_a is not None and parent_b is not None
            and parent_a.id == parent_b.id):
        return _do_merge(root, parent_a)

    # Case 2: one is a child of the other's subtree — walk upward
    # Try finding a common ancestor that has the right structure.
    # Collect ancestors of id_a.
    ancestors_a: dict[str, SplitNode] = {}
    _collect_ancestors(root, id_a, ancestors_a)
    ancestors_b: dict[str, SplitNode] = {}
    _collect_ancestors(root, id_b, ancestors_b)

    # Find lowest common ancestor
    for aid in ancestors_a:
        if aid in ancestors_b:
            lca = find_node(root, aid)
            if isinstance(lca, SplitNode):
                result = _do_merge(root, lca)
                if result is not None:
                    return result
            break

    return None


def _collect_ancestors(root: Node, target_id: str,
                       out: dict[str, "SplitNode"]) -> bool:
    """Populate *out* with {node.id: node} for every ancestor of *target_id*."""
    if isinstance(root, LeafNode):
        return root.id == target_id
    if root.id == target_id:
        return True
    if _collect_ancestors(root.first, target_id, out) or \
       _collect_ancestors(root.second, target_id, out):
        out[root.id] = root
        return True
    return False


def _do_merge(root: Node, parent: SplitNode) -> Optional[Node]:
    """Perform the actual merge if *parent* has the right structure.

    Pattern:
      parent (cross_dir)
        first:  SplitNode (border_dir, ratio_a)
        second: SplitNode (border_dir, ratio_b)

    with ratio_a ≈ ratio_b.  Restructure to:
      SplitNode (border_dir, avg_ratio)
        first:  SplitNode (cross_dir, parent.ratio,
                           first.first, second.first)
        second: SplitNode (cross_dir, parent.ratio,
                           first.second, second.second)
    """
    if not isinstance(parent.first, SplitNode) or \
       not isinstance(parent.second, SplitNode):
        return None

    a: SplitNode = parent.first
    b: SplitNode = parent.second

    if a.direction != b.direction:
        return None
    if a.direction == parent.direction:
        return None  # must be perpendicular

    border_dir = a.direction
    cross_dir = parent.direction

    # Check ratio similarity (allow ~1% tolerance)
    if abs(a.ratio - b.ratio) > 0.02:
        return None

    avg_ratio = (a.ratio + b.ratio) / 2.0

    merged = SplitNode(
        direction=border_dir,
        ratio=avg_ratio,
        first=SplitNode(
            direction=cross_dir,
            ratio=parent.ratio,
            first=copy.deepcopy(a.first),
            second=copy.deepcopy(b.first),
        ),
        second=SplitNode(
            direction=cross_dir,
            ratio=parent.ratio,
            first=copy.deepcopy(a.second),
            second=copy.deepcopy(b.second),
        ),
    )

    return _replace_node(root, parent.id, merged)


# ---------------------------------------------------------------------------
# Check whether a border can be split (has a valid crossing)
# ---------------------------------------------------------------------------
def find_valid_crossing(root: Node, split_id: str,
                        rect: Rect) -> Optional[float]:
    """Return the absolute crossing position if the border can be rotated.

    Returns ``None`` if both children of the target SplitNode are not
    perpendicular SplitNodes with matching ratios (i.e. the rotation
    pattern does not apply).
    """
    node = find_node(root, split_id)
    if not isinstance(node, SplitNode):
        return None
    if not isinstance(node.first, SplitNode) or \
       not isinstance(node.second, SplitNode):
        return None

    perp = _perp(node.direction)
    if node.first.direction != perp or node.second.direction != perp:
        return None
    if abs(node.first.ratio - node.second.ratio) > 0.02:
        return None

    avg = (node.first.ratio + node.second.ratio) / 2.0
    return _abs_position(rect, perp, avg)
