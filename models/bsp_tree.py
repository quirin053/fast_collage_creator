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
