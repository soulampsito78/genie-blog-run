"""Service-level image API wrapper — called_image_api only when wrapper is invoked."""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from service_full_run_contract import (
    ERROR_IMAGE_GENERATION_FAILED,
    ERROR_IMAGE_GENERATION_NOT_IMPLEMENTED,
    IMAGE_GEN_FAILED,
    IMAGE_GEN_GENERATED,
    IMAGE_SOURCE_GENERATED,
    ServiceImageOutcome,
)

logger = logging.getLogger(__name__)

DEFAULT_VERTEX_IMAGE_MODEL = os.getenv("VERTEX_IMAGE_MODEL", "gemini-2.5-flash-image")
DEFAULT_VERTEX_LOCATION = os.getenv("VERTEX_LOCATION", "global")
GEMINI_2_5_FLASH_IMAGE_OUTPUT_TOKENS = 1290


def _repo_rel(path: Path) -> str:
    root = Path(__file__).resolve().parent
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError:
        return str(path.resolve())


def invoke_vertex_image_generation(
    *,
    prompt: str,
    output_path: Path,
    reference_image_path: Optional[Path] = None,
    project_id: Optional[str] = None,
    model_name: Optional[str] = None,
    location: Optional[str] = None,
    generate_fn: Optional[Callable[..., Path]] = None,
) -> ServiceImageOutcome:
    """
    Invoke Vertex image generation. Sets called_image_api=True only on actual API call attempt.
    """
    prompt_text = str(prompt or "").strip()
    if not prompt_text:
        return ServiceImageOutcome(
            image_generation_status=IMAGE_GEN_FAILED,
            error_code=ERROR_IMAGE_GENERATION_FAILED,
            error_message="empty prompt",
        )

    fn = generate_fn
    uses_default_generator = fn is None
    if fn is None:
        try:
            from image_generator import generate_image_file as fn  # noqa: PLC0415
        except ImportError as exc:
            logger.warning("image_generator import failed: %s", exc)
            return ServiceImageOutcome(
                image_generation_status=IMAGE_GEN_FAILED,
                error_code=ERROR_IMAGE_GENERATION_NOT_IMPLEMENTED,
                error_message=f"image_generator_import_failed: {exc}",
            )

    project = (
        str(project_id or "").strip()
        or os.getenv("GENIE_VERTEX_PROJECT_ID", "").strip()
        or os.getenv("GOOGLE_CLOUD_PROJECT", "").strip()
        or os.getenv("PROJECT_ID", "").strip()
    )
    if not project:
        return ServiceImageOutcome(
            image_generation_status=IMAGE_GEN_FAILED,
            error_code=ERROR_IMAGE_GENERATION_NOT_IMPLEMENTED,
            error_message="missing vertex project id",
        )

    model = str(model_name or DEFAULT_VERTEX_IMAGE_MODEL).strip()
    loc = str(location or DEFAULT_VERTEX_LOCATION).strip()
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    ref = Path(reference_image_path) if reference_image_path else None

    try:
        telemetry: Dict[str, Any] = {}
        kwargs = dict(
            prompt=prompt_text,
            output_path=out,
            model_name=model,
            reference_image_path=ref if ref and ref.is_file() else None,
            project_id=project,
            location=loc,
        )
        if uses_default_generator:
            kwargs["telemetry"] = telemetry
        fn(**kwargs)
        if not out.is_file():
            raise RuntimeError(f"image file not written: {out}")
        output_count = int(telemetry.get("response_image_output_count") or 1)
        normalized_model = model.lower()
        return ServiceImageOutcome(
            called_image_api=True,
            image_generation_status=IMAGE_GEN_GENERATED,
            image_source=IMAGE_SOURCE_GENERATED,
            generated_image_path=_repo_rel(out),
            image_model_raw=model,
            image_model_normalized=normalized_model,
            image_request_count=1,
            image_successful_output_count=output_count,
            image_discarded_output_count=int(
                telemetry.get("discarded_image_output_count") or max(0, output_count - 1)
            ),
            image_output_tokens=(
                output_count * GEMINI_2_5_FLASH_IMAGE_OUTPUT_TOKENS
                if normalized_model == "gemini-2.5-flash-image"
                else None
            ),
            image_evidence_confidence="high",
            image_evidence_source="runtime_vertex_response_image_parts",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("invoke_vertex_image_generation failed: %s", exc)
        return ServiceImageOutcome(
            called_image_api=True,
            image_generation_status=IMAGE_GEN_FAILED,
            image_source="",
            error_code=ERROR_IMAGE_GENERATION_FAILED,
            error_message=f"{type(exc).__name__}: {exc}",
            image_model_raw=model,
            image_model_normalized=model.lower(),
            image_request_count=1,
            image_successful_output_count=0,
            image_failed_request_count=1,
            image_evidence_confidence="high",
            image_evidence_source="runtime_vertex_request_failure",
        )
