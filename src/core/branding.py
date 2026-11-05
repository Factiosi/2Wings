"""2Wings icon paths and raster tray/window assets."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageOps

from src.core.paths import program_root


def icons_dir() -> Path:
    return program_root() / "assets" / "icons"


def app_window_icon_path() -> Path | None:
    """Always-online icon for the app window and shortcuts."""
    ico = icons_dir() / "app.ico"
    return ico if ico.exists() else None


def load_tray_menu_icon(name: str, *, dark: bool, size: int) -> Image.Image | None:
    """Lucide icon rendered by tools/generate_icons.mjs for the dark or light menu."""
    path = icons_dir() / "menu" / f"{name}-{'dark' if dark else 'light'}.png"
    if not path.exists():
        return None
    return Image.open(path).convert("RGBA").resize((size, size), Image.Resampling.LANCZOS)


def load_tray_icon(*, running: bool, size: int = 64) -> Image.Image:
    """The logo while the bypass runs, the same logo without colour while it is stopped."""
    path = icons_dir() / "tray.png"
    if not path.exists():
        return _fallback_tray_icon(size)
    image = Image.open(path).convert("RGBA")
    if image.size != (size, size):
        image = image.resize((size, size), Image.Resampling.LANCZOS)
    if running:
        return image
    grey = ImageOps.grayscale(image).convert("RGBA")
    grey.putalpha(image.getchannel("A"))
    return grey


def _fallback_tray_icon(size: int) -> Image.Image:
    from PIL import ImageDraw

    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse((4, 4, size - 4, size - 4), fill=(66, 133, 244, 255))
    return image


__all__ = [
    "app_window_icon_path",
    "icons_dir",
    "load_tray_icon",
    "load_tray_menu_icon",
]
