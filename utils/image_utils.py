"""
Image loading utilities and thumbnail cache.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PIL import Image, ImageOps
from PySide6.QtGui import QImage, QPixmap

# ------------------------------------------------------------------
# Supported extensions
# ------------------------------------------------------------------
SUPPORTED_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".webp", ".tiff", ".tif",
    ".bmp", ".gif", ".jxl",
}


def is_supported(path: str | Path) -> bool:
    return Path(path).suffix.lower() in SUPPORTED_EXTENSIONS


# ------------------------------------------------------------------
# Thumbnail cache
# ------------------------------------------------------------------
class ThumbnailCache:
    """LRU-like in-memory cache mapping path -> QPixmap at a given size."""

    def __init__(self, max_size: int = 256):
        self._cache: dict[tuple[str, int], QPixmap] = {}
        self._order: list[tuple[str, int]] = []
        self._max = max_size

    def get(self, path: str, thumb_size: int = 256) -> Optional[QPixmap]:
        key = (path, thumb_size)
        if key in self._cache:
            # Move to end (most recently used)
            self._order.remove(key)
            self._order.append(key)
            return self._cache[key]
        return None

    def put(self, path: str, thumb_size: int, pixmap: QPixmap) -> None:
        key = (path, thumb_size)
        if key in self._cache:
            self._order.remove(key)
        elif len(self._cache) >= self._max:
            oldest = self._order.pop(0)
            del self._cache[oldest]
        self._cache[key] = pixmap
        self._order.append(key)

    def load(self, path: str, thumb_size: int = 256) -> Optional[QPixmap]:
        cached = self.get(path, thumb_size)
        if cached is not None:
            return cached
        pixmap = load_pixmap(path, max_dim=thumb_size)
        if pixmap is not None:
            self.put(path, thumb_size, pixmap)
        return pixmap

    def invalidate(self, path: str) -> None:
        keys = [k for k in self._cache if k[0] == path]
        for k in keys:
            del self._cache[k]
            if k in self._order:
                self._order.remove(k)


# Global cache instance
thumbnail_cache = ThumbnailCache(max_size=512)


# ------------------------------------------------------------------
# Pillow → QPixmap
# ------------------------------------------------------------------

def pil_to_qimage(pil_img: Image.Image) -> QImage:
    """Convert a PIL Image (RGBA or RGB) to QImage."""
    pil_img = pil_img.convert("RGBA")
    data = pil_img.tobytes("raw", "RGBA")
    qimg = QImage(data, pil_img.width, pil_img.height, QImage.Format.Format_RGBA8888)
    return qimg.copy()  # detach from the data buffer


def load_pixmap(path: str, max_dim: int = 0) -> Optional[QPixmap]:
    """Load an image from *path* and return a QPixmap.
    If *max_dim* > 0 the image is downscaled so that neither
    dimension exceeds *max_dim* (preserving aspect ratio).
    Returns None on failure.
    """
    try:
        img: Image.Image = Image.open(path)
        img = ImageOps.exif_transpose(img)          # fix EXIF rotation
        img = img.convert("RGBA")

        if max_dim > 0:
            img.thumbnail((max_dim, max_dim), Image.LANCZOS)

        qimg = pil_to_qimage(img)
        return QPixmap.fromImage(qimg)
    except Exception as exc:  # noqa: BLE001
        print(f"[image_utils] Could not load {path}: {exc}")
        return None


def load_full_pixmap(path: str) -> Optional[QPixmap]:
    """Load at full resolution (for export or high-quality zoom)."""
    return load_pixmap(path, max_dim=0)
