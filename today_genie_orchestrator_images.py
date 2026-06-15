"""Today_Geenee orchestrator-path image generation and CID inline resolution."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from renderers import today_genie_email_inline_cid_pair
from service_full_run_contract import (
    ERROR_IMAGE_GENERATION_FAILED,
    IMAGE_GEN_FAILED,
    IMAGE_GEN_GENERATED,
    IMAGE_SOURCE_GENERATED,
    TodayGenieServiceImageBundle,
)
from today_genie_service_full_run import (
    generate_today_genie_service_images,
    inline_parts_from_today_genie_bundle,
)

IMAGE_SOURCE_STATIC_FALLBACK = "static_fallback"
STATIC_FALLBACK_ISSUE_CODE = "TODAY_GENIE_STATIC_IMAGE_FALLBACK"


@dataclass
class TodayGenieOrchestratorImageResult:
    bundle: Optional[TodayGenieServiceImageBundle] = None
    inline_parts: List[Tuple[str, str, str]] = field(default_factory=list)
    called_image_api: bool = False
    image_source: str = ""
    image_generation_status: str = ""
    generated_image_paths: Dict[str, Optional[str]] = field(default_factory=dict)
    fallback_used: bool = False
    issue_codes: List[str] = field(default_factory=list)


def _repo_root() -> Path:
    return Path(__file__).resolve().parent


def _static_latest_inline_parts() -> Optional[List[Tuple[str, str, str]]]:
    repo = _repo_root()
    top_latest = repo / "static" / "email" / "GENIE_EMAIL_today_genie_top_latest.jpg"
    bottom_latest = repo / "static" / "email" / "GENIE_EMAIL_today_genie_bottom_latest.jpg"
    if not top_latest.is_file() or not bottom_latest.is_file():
        return None
    cid_top, cid_bottom = today_genie_email_inline_cid_pair()
    return [
        (str(top_latest.resolve()), cid_top, "GENIE_EMAIL_today_genie_top.jpg"),
        (str(bottom_latest.resolve()), cid_bottom, "GENIE_EMAIL_today_genie_bottom.jpg"),
    ]


def generate_today_genie_orchestrator_images(
    run_id: str,
    data: Dict[str, Any],
    runtime_input: Dict[str, Any],
    *,
    generate_fn: Any = None,
    allow_static_fallback: bool = True,
) -> TodayGenieOrchestratorImageResult:
    """Generate run-specific top/bottom images; optional static latest fallback on failure."""
    bundle = generate_today_genie_service_images(
        data,
        runtime_input,
        run_id=run_id,
        generate_fn=generate_fn,
    )
    if bundle.ok:
        return TodayGenieOrchestratorImageResult(
            bundle=bundle,
            inline_parts=inline_parts_from_today_genie_bundle(bundle),
            called_image_api=bundle.called_image_api,
            image_source=IMAGE_SOURCE_GENERATED,
            image_generation_status=IMAGE_GEN_GENERATED,
            generated_image_paths={
                "top": bundle.top.generated_image_path,
                "bottom": bundle.bottom.generated_image_path,
            },
            fallback_used=False,
            issue_codes=[],
        )

    err = (
        bundle.top.error_code
        or bundle.bottom.error_code
        or ERROR_IMAGE_GENERATION_FAILED
    )
    issue_codes = [str(err)]
    if allow_static_fallback:
        static_parts = _static_latest_inline_parts()
        if static_parts:
            issue_codes.append(STATIC_FALLBACK_ISSUE_CODE)
            return TodayGenieOrchestratorImageResult(
                bundle=bundle,
                inline_parts=static_parts,
                called_image_api=bundle.called_image_api,
                image_source=IMAGE_SOURCE_STATIC_FALLBACK,
                image_generation_status=IMAGE_GEN_FAILED,
                generated_image_paths={"top": None, "bottom": None},
                fallback_used=True,
                issue_codes=issue_codes,
            )

    return TodayGenieOrchestratorImageResult(
        bundle=bundle,
        inline_parts=[],
        called_image_api=bundle.called_image_api,
        image_source=IMAGE_SOURCE_STATIC_FALLBACK if bundle.called_image_api else "",
        image_generation_status=IMAGE_GEN_FAILED,
        generated_image_paths={"top": None, "bottom": None},
        fallback_used=False,
        issue_codes=issue_codes,
    )


def orchestrator_image_fields_for_artifact(
    image_result: Optional[TodayGenieOrchestratorImageResult],
) -> Dict[str, Any]:
    if not image_result:
        return {}
    fields: Dict[str, Any] = {
        "called_image_api": bool(image_result.called_image_api),
        "image_source": image_result.image_source,
        "image_generation_status": image_result.image_generation_status,
        "fallback_used": bool(image_result.fallback_used),
    }
    top = image_result.generated_image_paths.get("top")
    bottom = image_result.generated_image_paths.get("bottom")
    if top and bottom:
        fields["generated_image_paths"] = {"top": top, "bottom": bottom}
        fields["generated_image_path"] = top
    return fields
