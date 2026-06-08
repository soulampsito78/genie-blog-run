"""Legacy Today_Geenee local TPO proof image footer helper.

Local PIL post-processing only. Does not call image APIs, schedulers, or email
systems. Not part of the Kee-Suri image manifest pipeline (see
``keysuri_image_overlay`` and ``scripts/apply_keysuri_image_watermark.py``).

Tracked Today_Geenee proof scripts import ``apply_today_genie_brand_footer``:
``scripts/run_tpo_proof_once.py``, ``scripts/run_owner_review_full_tpo_v2.py``.

Future convergence should replace this module with
``keysuri_image_overlay.apply_keysuri_mirai_on_watermark(..., position="bottom_left")``.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def apply_today_genie_brand_footer(path: Path, label: str = "MirAI:ON") -> None:
    """
    Apply a visible MirAI:ON footer strip to the raster at ``path``.

    Overwrites the given image path in place (JPEG). If the path is missing or
    not a file, returns without raising. Default label is ``MirAI:ON``.

    For Today_Geenee TPO proof flows only. Callers must not use this for
    production asset manifest tracking; use the Kee-Suri watermark CLI/manifest
    path for tracked preview assets instead.
    """
    p = Path(path)
    if not p.is_file():
        return
    text = (label or "").strip() or "MirAI:ON"
    with Image.open(p) as base:
        im = base.convert("RGBA")
        w, h = im.size
        margin = int(max(10, min(w, h) * 0.018))
        pad_x, pad_y = 14, 8
        layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(layer)
        try:
            font = ImageFont.truetype(
                "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
                size=int(max(13, min(w, h) * 0.028)),
            )
        except OSError:
            try:
                font = ImageFont.truetype(
                    "/System/Library/Fonts/Supplemental/Arial.ttf",
                    size=int(max(13, min(w, h) * 0.028)),
                )
            except OSError:
                font = ImageFont.load_default()
        bbox = draw.textbbox((0, 0), text, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        bar_w = tw + pad_x * 2
        bar_h = th + pad_y * 2
        x0 = margin
        y0 = h - bar_h - margin
        x1 = x0 + bar_w
        y1 = y0 + bar_h
        draw.rounded_rectangle((x0, y0, x1, y1), radius=10, fill=(15, 23, 42, 210))
        draw.text((x0 + pad_x, y0 + pad_y - bbox[1]), text, font=font, fill=(248, 250, 252, 255))
        out = Image.alpha_composite(im, layer).convert("RGB")
        out.save(p, format="JPEG", quality=93, optimize=True)
