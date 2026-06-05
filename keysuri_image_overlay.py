"""Kee-Suri MirAI:ON raster watermark overlay (post-process only).

Applies a visible ownership mark after image generation. Does not call image API,
modify prompts, or embed model-generated text in the image.
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal, Tuple, Union

from PIL import Image, ImageDraw, ImageFont

DEFAULT_WATERMARK_TEXT = "MirAI:ON"
DEFAULT_POSITION = "bottom_right"
FORBIDDEN_LEGACY_TEXTS: Tuple[str, ...] = (
    "Heemang",
    "Today_Geenee",
    "Tomorrow_Geenee",
)

Position = Literal["bottom_right", "bottom_left"]

_BAR_FILL = (15, 23, 42, 210)
_TEXT_FILL = (248, 250, 252, 255)
_PAD_X = 14
_PAD_Y = 8
_CORNER_RADIUS = 10
_JPEG_QUALITY = 93


def _resolve_path(path: Union[str, Path]) -> Path:
    return Path(path).expanduser()


def _default_output_path(input_path: Path) -> Path:
    return input_path.with_name(f"{input_path.stem}_mirai_on_watermarked{input_path.suffix}")


def _margin(width: int, height: int) -> int:
    return int(max(10, min(width, height) * 0.018))


def _font_size(width: int, height: int) -> int:
    return int(max(13, min(width, height) * 0.028))


def _load_font(width: int, height: int) -> ImageFont.ImageFont:
    size = _font_size(width, height)
    candidates = (
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/Library/Fonts/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    )
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def _bar_size(text: str, font: ImageFont.ImageFont) -> Tuple[int, int]:
    probe = Image.new("RGBA", (4, 4), (0, 0, 0, 0))
    draw = ImageDraw.Draw(probe)
    bbox = draw.textbbox((0, 0), text, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    return text_w + _PAD_X * 2, text_h + _PAD_Y * 2


def calculate_watermark_box(
    width: int,
    height: int,
    *,
    position: str = DEFAULT_POSITION,
    label: str = DEFAULT_WATERMARK_TEXT,
) -> Tuple[int, int, int, int]:
    """Return (x0, y0, x1, y1) for the watermark bar in image coordinates."""
    if width <= 0 or height <= 0:
        raise ValueError("width and height must be positive")

    text = (label or "").strip() or DEFAULT_WATERMARK_TEXT
    margin = _margin(width, height)
    font = _load_font(width, height)
    bar_w, bar_h = _bar_size(text, font)

    if position == "bottom_left":
        x0 = margin
    elif position == "bottom_right":
        x0 = width - bar_w - margin
    else:
        raise ValueError(f"Unsupported position: {position!r}")

    y0 = height - bar_h - margin
    x1 = x0 + bar_w
    y1 = y0 + bar_h
    return (x0, y0, x1, y1)


def _save_image(image: Image.Image, output_path: Path) -> None:
    suffix = output_path.suffix.lower()
    if suffix in (".jpg", ".jpeg"):
        image.convert("RGB").save(output_path, format="JPEG", quality=_JPEG_QUALITY, optimize=True)
        return
    if suffix == ".png":
        image.save(output_path, format="PNG")
        return
    image.convert("RGB").save(output_path, format="JPEG", quality=_JPEG_QUALITY, optimize=True)


def apply_keysuri_mirai_on_watermark(
    input_path: Union[str, Path],
    output_path: Union[str, Path, None] = None,
    *,
    position: str = DEFAULT_POSITION,
    label: str = DEFAULT_WATERMARK_TEXT,
) -> Path:
    """Apply a visible MirAI:ON watermark strip to a JPEG or PNG raster asset."""
    source = _resolve_path(input_path)
    if not source.is_file():
        raise FileNotFoundError(f"Input image not found: {source}")

    if position not in ("bottom_right", "bottom_left"):
        raise ValueError(f"Unsupported position: {position!r}")

    text = (label or "").strip() or DEFAULT_WATERMARK_TEXT

    target = _resolve_path(output_path) if output_path is not None else _default_output_path(source)
    target.parent.mkdir(parents=True, exist_ok=True)

    with Image.open(source) as base:
        image = base.convert("RGBA")
        width, height = image.size
        font = _load_font(width, height)
        x0, y0, x1, y1 = calculate_watermark_box(width, height, position=position, label=text)

        layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(layer)
        draw.rounded_rectangle((x0, y0, x1, y1), radius=_CORNER_RADIUS, fill=_BAR_FILL)

        probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
        bbox = probe.textbbox((0, 0), text, font=font)
        text_x = x0 + _PAD_X
        text_y = y0 + _PAD_Y - bbox[1]
        draw.text((text_x, text_y), text, font=font, fill=_TEXT_FILL)

        composited = Image.alpha_composite(image, layer)
        _save_image(composited, target)

    return target.resolve()
