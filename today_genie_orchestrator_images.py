"""Today_Geenee orchestrator-path image generation and CID inline resolution."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from admin_store import _get_gcs_client
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
CUSTOMER_IMAGE_PERSISTENCE_FAILED = "today_generated_image_persistence_failed"

TODAY_IMAGE_REGEN_INPUTS_KEY = "today_image_regen_inputs"


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


def today_image_regen_inputs(
    data: Optional[Dict[str, Any]],
    runtime_input: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Snapshot the inputs needed to regenerate today images without text regeneration.

    The top/bottom prompts are authored by the text model, so an image_only reissue
    can only avoid a second text generation if they were persisted with the run.
    Returns {} when the prompts are absent (image_only then stays unavailable).
    """
    payload = data if isinstance(data, dict) else {}
    runtime = runtime_input if isinstance(runtime_input, dict) else {}
    studio = str(payload.get("image_prompt_studio") or "").strip()
    outdoor = str(payload.get("image_prompt_outdoor") or "").strip()
    if not studio or not outdoor:
        return {}
    snapshot: Dict[str, Any] = {
        "image_prompt_studio": studio,
        "image_prompt_outdoor": outdoor,
    }
    for key in ("image_briefing_mood_state", "image_mood_basis"):
        value = str(payload.get(key) or "").strip()
        if value:
            snapshot[key] = value
    target_date = str(runtime.get("target_date") or "").strip()
    if target_date:
        snapshot["target_date"] = target_date
    weather = runtime.get("image_weather_context")
    if isinstance(weather, dict) and weather:
        snapshot["image_weather_context"] = weather
    return snapshot


def today_image_regen_payload_from_snapshot(
    snapshot: Optional[Dict[str, Any]],
) -> Optional[Tuple[Dict[str, Any], Dict[str, Any]]]:
    """Rebuild the (data, runtime_input) pair that image generation consumes."""
    if not isinstance(snapshot, dict):
        return None
    studio = str(snapshot.get("image_prompt_studio") or "").strip()
    outdoor = str(snapshot.get("image_prompt_outdoor") or "").strip()
    if not studio or not outdoor:
        return None
    data: Dict[str, Any] = {
        "image_prompt_studio": studio,
        "image_prompt_outdoor": outdoor,
    }
    for key in ("image_briefing_mood_state", "image_mood_basis"):
        value = str(snapshot.get(key) or "").strip()
        if value:
            data[key] = value
    runtime_input: Dict[str, Any] = {}
    target_date = str(snapshot.get("target_date") or "").strip()
    if target_date:
        runtime_input["target_date"] = target_date
    weather = snapshot.get("image_weather_context")
    if isinstance(weather, dict) and weather:
        runtime_input["image_weather_context"] = weather
    return data, runtime_input


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
        issue_codes: List[str] = []
        if not getattr(bundle, "watermark_applied", False):
            from today_genie_service_full_run import WATERMARK_ISSUE_CODE

            issue_codes.append(WATERMARK_ISSUE_CODE)
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
            issue_codes=issue_codes,
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
    if image_result.bundle is not None and image_result.bundle.ok:
        from today_genie_service_full_run import today_genie_watermark_meta

        fields.update(today_genie_watermark_meta(image_result.bundle))
    return fields


def _upload_customer_image(
    bucket_name: str,
    object_name: str,
    source_path: Path,
) -> None:
    bucket = _get_gcs_client().bucket(bucket_name)
    bucket.blob(object_name).upload_from_filename(
        str(source_path),
        content_type="image/jpeg",
    )


def persist_today_genie_customer_images(
    run_id: str,
    image_result: Optional[TodayGenieOrchestratorImageResult],
    *,
    upload_fn: Optional[Callable[[str, str, Path], None]] = None,
) -> Dict[str, Any]:
    """Persist generated run images beside the artifact for delayed approval sends."""
    if not image_result:
        return {}
    if (
        image_result.image_source != IMAGE_SOURCE_GENERATED
        or image_result.image_generation_status != IMAGE_GEN_GENERATED
        or image_result.fallback_used
    ):
        return {
            "run_specific_images": False,
            "customer_image_source": IMAGE_SOURCE_STATIC_FALLBACK,
        }

    raw_top = str(image_result.generated_image_paths.get("top") or "").strip()
    raw_bottom = str(image_result.generated_image_paths.get("bottom") or "").strip()
    fields: Dict[str, Any] = {
        "run_specific_images": True,
        "customer_image_source": "generated_run_images",
        "customer_top_image_path": raw_top,
        "customer_bottom_image_path": raw_bottom,
    }
    top = (
        (_repo_root() / raw_top).resolve()
        if raw_top and not Path(raw_top).is_absolute()
        else Path(raw_top)
    )
    bottom = (
        (_repo_root() / raw_bottom).resolve()
        if raw_bottom and not Path(raw_bottom).is_absolute()
        else Path(raw_bottom)
    )
    if not raw_top or not raw_bottom or not top.is_file() or not bottom.is_file():
        fields.update(
            customer_image_persistence_status="failed",
            customer_image_persistence_reason=CUSTOMER_IMAGE_PERSISTENCE_FAILED,
        )
        return fields

    from admin_store import admin_artifact_bucket_name, admin_artifact_gcs_prefix

    bucket_name = admin_artifact_bucket_name()
    if not bucket_name:
        fields.update(
            customer_image_persistence_status="local_only",
            customer_image_persistence_reason="artifact_bucket_not_configured",
        )
        return fields

    prefix = admin_artifact_gcs_prefix()
    objects = {
        "top": f"{prefix}/{run_id}.images/top.jpg",
        "bottom": f"{prefix}/{run_id}.images/bottom.jpg",
    }
    uploader = upload_fn or _upload_customer_image
    try:
        uploader(bucket_name, objects["top"], top)
        uploader(bucket_name, objects["bottom"], bottom)
    except Exception as exc:
        fields.update(
            customer_image_persistence_status="failed",
            customer_image_persistence_reason=CUSTOMER_IMAGE_PERSISTENCE_FAILED,
            customer_image_persistence_error=type(exc).__name__,
        )
        return fields

    fields.update(
        customer_image_persistence_status="persisted",
        customer_image_storage_backend="gcs",
        customer_image_gcs_bucket=bucket_name,
        customer_image_gcs_objects=objects,
    )
    return fields
