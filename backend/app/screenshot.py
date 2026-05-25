from __future__ import annotations

import base64
import io
import os
import tempfile
import time

from PIL import Image, ImageDraw

# Game Boy display dimensions
GB_WIDTH = 160
GB_HEIGHT = 144

# mGBA output sizes
GBA_FRAME_W, GBA_FRAME_H = 240, 160
MGBA_GB_FRAME_W, MGBA_GB_FRAME_H = 256, 224

# Grid cell size for movement overlay
GRID_SIZE = 16

GRID_COLOR = (255, 0, 0, 180)  # semi-transparent red


def _get_crop_box(width: int, height: int) -> tuple[int, int, int, int] | None:
    """Return (left, top, right, bottom) crop for the Game Boy frame."""
    if width == GBA_FRAME_W and height == GBA_FRAME_H:
        return (40, 8, 40 + GB_WIDTH, 8 + GB_HEIGHT)
    if width == MGBA_GB_FRAME_W and height == MGBA_GB_FRAME_H:
        return (48, 40, 48 + GB_WIDTH, 40 + GB_HEIGHT)
    if width == GB_WIDTH and height == GB_HEIGHT:
        return (0, 0, GB_WIDTH, GB_HEIGHT)
    return None


def process_screenshot(path: str, overlay_grid: bool = True) -> str:
    """Read PNG at path, crop to Game Boy frame, optionally draw grid, return base64."""
    with Image.open(path) as img:
        img = img.convert("RGBA")
        crop = _get_crop_box(img.width, img.height)
        if crop:
            img = img.crop(crop)

        if overlay_grid and img.width == GB_WIDTH and img.height == GB_HEIGHT:
            img = _draw_grid(img)

        # Save back as PNG
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        optimized = buf.read()

    with open(path, "wb") as f:
        f.write(optimized)

    return base64.b64encode(optimized).decode("ascii")


def _draw_grid(img: Image.Image) -> Image.Image:
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    for x in range(0, img.width, GRID_SIZE):
        draw.line([(x, 0), (x, img.height - 1)], fill=GRID_COLOR, width=1)
    for y in range(0, img.height, GRID_SIZE):
        draw.line([(0, y), (img.width - 1, y)], fill=GRID_COLOR, width=1)

    return Image.alpha_composite(img, overlay)


def is_black_frame(path: str, threshold: float = 0.95) -> bool:
    """Return True if >95% of pixels are near-black."""
    with Image.open(path) as img:
        img = img.convert("RGB")
        crop = _get_crop_box(img.width, img.height)
        if crop:
            img = img.crop(crop)

        pixels = list(img.getdata())
        black = sum(1 for r, g, b in pixels if r <= 12 and g <= 12 and b <= 12)
        return (black / len(pixels)) >= threshold if pixels else False


def make_screenshot_path() -> str:
    ts = int(time.time() * 1000)
    tmpdir = tempfile.gettempdir()
    return os.path.join(tmpdir, f"pokemon_screenshot_{ts}.png")
