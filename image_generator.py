from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Optional

from PIL import Image as PILImage
import vertexai
from vertexai.generative_models import GenerationConfig, GenerativeModel, Image, Part


def _extract_first_image_bytes(response: object) -> bytes:
    candidates = getattr(response, "candidates", None) or []
    for cand in candidates:
        content = getattr(cand, "content", None)
        if not content:
            continue
        parts = getattr(content, "parts", None) or []
        for p in parts:
            inline = getattr(p, "inline_data", None)
            if inline is None:
                continue
            data = getattr(inline, "data", None)
            if data:
                return data
    raise RuntimeError("No image bytes in model response.")


def generate_image_file(
    *,
    prompt: str,
    output_path: Path,
    model_name: str,
    reference_image_path: Optional[Path] = None,
    project_id: Optional[str] = None,
    location: str = "global",
) -> Path:
    """
    Generate an image with a Gemini image model and write as JPEG.
    """
    if not prompt.strip():
        raise ValueError("prompt must not be empty")

    if project_id:
        vertexai.init(project=project_id, location=location)

    model = GenerativeModel(model_name)
    content_parts: list[object] = []
    if reference_image_path and reference_image_path.is_file():
        ref_img = Image.load_from_file(str(reference_image_path))
        content_parts.append(Part.from_image(ref_img))
    content_parts.append(prompt)

    response = model.generate_content(
        content_parts,
        generation_config=GenerationConfig(
            response_modalities=["IMAGE"],
        ),
    )
    raw = _extract_first_image_bytes(response)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with PILImage.open(BytesIO(raw)) as im:
        im.convert("RGB").save(output_path, format="JPEG", quality=92, optimize=True)
    return output_path

