"""Shared Korea Bottom v6 multi-reference image generation."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from keysuri_bottom_shot_prompt_builder import (
    ASSET01_PATH,
    ASSET01_ROLE,
    BOTTOM_ANCHOR_PATH,
    BOTTOM_ANCHOR_ROLE,
    build_bottom_shot_prompt,
)
from keysuri_image_provider_contract import DEFAULT_VERTEX_IMAGE_MODEL, DEFAULT_VERTEX_LOCATION

BOTTOM_ANCHOR_ASSET_ID = "keysuri_korea_bottom_20260605_105936"
SECONDARY_REFERENCE_ASSET_ID = "Asset01"
GENERATED_SOURCE = "generated_v6_multi_ref"

DirectGenerateFn = Callable[..., Path]
WatermarkFn = Callable[[Path, Path], Path]


@dataclass
class BottomShotGenerationResult:
    ok: bool
    image_path: Optional[Path] = None
    raw_image_path: Optional[Path] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    error_code: str = ""
    error_message: str = ""


def _direct_vertex_multi_ref_generate(
    *,
    prompt: str,
    output_path: Path,
    primary_reference_path: Path,
    secondary_reference_path: Path,
    model_name: str,
    project_id: str,
    location: str,
) -> Path:
    """Call Vertex with slot 0 anchor, slot 1 identity reference, then prompt."""
    if not project_id:
        raise RuntimeError("GENIE_VERTEX_PROJECT_ID or GOOGLE_CLOUD_PROJECT is required")

    import vertexai
    from PIL import Image as PILImage
    from vertexai.generative_models import GenerationConfig, GenerativeModel
    from vertexai.generative_models import Image as VertexImage, Part

    vertexai.init(project=project_id, location=location)
    model = GenerativeModel(model_name)
    content_parts = [
        Part.from_image(VertexImage.load_from_file(str(primary_reference_path))),
        Part.from_image(VertexImage.load_from_file(str(secondary_reference_path))),
        prompt,
    ]
    response = model.generate_content(
        content_parts,
        generation_config=GenerationConfig(response_modalities=["IMAGE"]),
    )

    raw: Optional[bytes] = None
    for candidate in getattr(response, "candidates", None) or []:
        content = getattr(candidate, "content", None)
        for part in getattr(content, "parts", None) or []:
            inline = getattr(part, "inline_data", None)
            if inline and getattr(inline, "data", None):
                raw = inline.data
                break
        if raw:
            break
    if not raw:
        raise RuntimeError("No image bytes in Korea Bottom v6 model response")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with PILImage.open(BytesIO(raw)) as image:
        image.convert("RGB").save(output_path, format="JPEG", quality=92, optimize=True)
    return output_path


def generate_keysuri_korea_bottom_v6(
    *,
    repo_root: Path,
    output_path: Path,
    weather_condition: str,
    primary_reference_path: Optional[Path] = None,
    secondary_reference_path: Optional[Path] = None,
    temperature_c: Optional[float] = None,
    season: Optional[str] = None,
    wardrobe_variant: Optional[int] = None,
    pose_variant: Optional[int] = None,
    prompt_result: Optional[Dict[str, Any]] = None,
    model_name: Optional[str] = None,
    project_id: Optional[str] = None,
    location: Optional[str] = None,
    apply_watermark: bool = False,
    watermark_fn: Optional[WatermarkFn] = None,
    generate_fn: Optional[DirectGenerateFn] = None,
) -> BottomShotGenerationResult:
    """Generate one Bottom v6 image while preserving the QA slot contract."""
    repo = Path(repo_root)
    primary = Path(primary_reference_path) if primary_reference_path else repo / BOTTOM_ANCHOR_PATH
    secondary = Path(secondary_reference_path) if secondary_reference_path else repo / ASSET01_PATH
    model = (model_name or os.getenv("VERTEX_IMAGE_MODEL") or DEFAULT_VERTEX_IMAGE_MODEL).strip()
    loc = (location or os.getenv("VERTEX_LOCATION") or DEFAULT_VERTEX_LOCATION).strip()
    project = (
        project_id
        or os.getenv("GENIE_VERTEX_PROJECT_ID")
        or os.getenv("GOOGLE_CLOUD_PROJECT")
        or os.getenv("PROJECT_ID")
        or ""
    ).strip()

    metadata: Dict[str, Any] = {
        "bottom_shot_source": GENERATED_SOURCE,
        "bottom_shot_generated": False,
        "bottom_shot_generation_attempted": True,
        "bottom_shot_image_api_called": False,
        "bottom_anchor_asset_id": BOTTOM_ANCHOR_ASSET_ID,
        "korea_bottom_anchor_asset_id": BOTTOM_ANCHOR_ASSET_ID,
        "bottom_anchor_role": BOTTOM_ANCHOR_ROLE,
        "bottom_anchor_slot": 0,
        "secondary_reference_asset_id": SECONDARY_REFERENCE_ASSET_ID,
        "secondary_reference_role": ASSET01_ROLE,
        "secondary_reference_slot": 1,
        "bottom_shot_model": model,
        "bottom_shot_prompt_contract_version": "v6",
    }

    if not primary.is_file():
        return BottomShotGenerationResult(
            ok=False,
            metadata=metadata,
            error_code="bottom_anchor_missing",
            error_message=str(primary),
        )
    if not secondary.is_file():
        return BottomShotGenerationResult(
            ok=False,
            metadata=metadata,
            error_code="bottom_secondary_reference_missing",
            error_message=str(secondary),
        )

    try:
        built = prompt_result or build_bottom_shot_prompt(
            weather_condition=weather_condition,
            temperature_c=temperature_c,
            season=season,
            wardrobe_variant=wardrobe_variant,
            pose_variant=pose_variant,
        )
        wardrobe = built["weather_outfit_shell"]
        metadata.update(
            {
                "bottom_shot_weather_key": wardrobe["outfit_map_key"],
                "bottom_shot_weather_case": wardrobe["weather_case"],
                "bottom_shot_wardrobe_variant": wardrobe["outfit_variant_index"],
                "bottom_shot_pose_variant": built["pose_variant_text"],
                "bottom_shot_weather_outfit_source": built["weather_input_metadata"]["weather_outfit_source"],
                "bottom_shot_prompt_preview": built["prompt_text"][:200],
            }
        )
        full_prompt = f"{built['prompt_text']}\n\nNEGATIVE:\n{built['negative_prompt']}"
        generator = generate_fn or _direct_vertex_multi_ref_generate
        raw_path = Path(output_path)
        metadata["bottom_shot_image_api_called"] = True
        generated = Path(
            generator(
                prompt=full_prompt,
                output_path=raw_path,
                primary_reference_path=primary,
                secondary_reference_path=secondary,
                model_name=model,
                project_id=project,
                location=loc,
            )
        )
        if not generated.is_file():
            raise RuntimeError(f"Bottom generator did not write output: {generated}")

        final_path = generated
        if apply_watermark:
            if watermark_fn is None:
                from keysuri_image_overlay import apply_keysuri_mirai_on_watermark

                watermark_fn = apply_keysuri_mirai_on_watermark
            final_path = generated.with_name(f"{generated.stem}_mirai_on_watermarked{generated.suffix}")
            final_path = Path(watermark_fn(generated, final_path))
            if not final_path.is_file():
                raise RuntimeError(f"Bottom watermark output missing: {final_path}")

        metadata.update(
            {
                "bottom_shot_generated": True,
                "bottom_shot_generation_status": "generated",
                "bottom_shot_watermark_status": "applied" if apply_watermark else "not_applied",
            }
        )
        return BottomShotGenerationResult(
            ok=True,
            image_path=final_path,
            raw_image_path=generated,
            metadata=metadata,
        )
    except Exception as exc:  # noqa: BLE001
        metadata["bottom_shot_generation_status"] = "failed"
        return BottomShotGenerationResult(
            ok=False,
            metadata=metadata,
            error_code="bottom_v6_generation_failed",
            error_message=f"{type(exc).__name__}: {exc}",
        )
