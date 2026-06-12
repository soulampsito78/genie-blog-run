"""Shared service-level full-run image and artifact contract."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

IMAGE_SOURCE_GENERATED = "generated"
IMAGE_SOURCE_FALLBACK = "fallback"
IMAGE_SOURCE_REUSED = "reused"
IMAGE_SOURCE_REGISTRY = "registry"
IMAGE_SOURCE_STATIC = "static"

IMAGE_GEN_GENERATED = "generated"
IMAGE_GEN_FAILED = "failed"
IMAGE_GEN_NOT_IMPLEMENTED = "not_implemented"
IMAGE_GEN_NOT_ATTEMPTED = "not_attempted"

ERROR_IMAGE_GENERATION_FAILED = "IMAGE_GENERATION_FAILED"
ERROR_IMAGE_GENERATION_NOT_IMPLEMENTED = "IMAGE_GENERATION_NOT_IMPLEMENTED"

SERVICE_FULL_RUN_TRIGGER = "manual_service_full_run"
SMOKE_ONLY_IMAGE_SOURCES = frozenset(
    {IMAGE_SOURCE_FALLBACK, IMAGE_SOURCE_REUSED, IMAGE_SOURCE_REGISTRY, IMAGE_SOURCE_STATIC}
)


@dataclass
class ServiceImageOutcome:
    called_image_api: bool = False
    image_generation_status: str = IMAGE_GEN_NOT_ATTEMPTED
    image_source: str = ""
    generated_image_path: Optional[str] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None

    @property
    def ok(self) -> bool:
        return service_image_passes(self)


@dataclass
class TodayGenieServiceImageBundle:
    top: ServiceImageOutcome = field(default_factory=ServiceImageOutcome)
    bottom: ServiceImageOutcome = field(default_factory=ServiceImageOutcome)
    primary_generated_image_path: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.top.ok and self.bottom.ok

    @property
    def called_image_api(self) -> bool:
        return bool(self.top.called_image_api or self.bottom.called_image_api)


def service_image_passes(outcome: ServiceImageOutcome) -> bool:
    return (
        bool(outcome.called_image_api)
        and outcome.image_generation_status == IMAGE_GEN_GENERATED
        and outcome.image_source == IMAGE_SOURCE_GENERATED
        and bool(str(outcome.generated_image_path or "").strip())
    )


def is_smoke_only_image_source(image_source: str) -> bool:
    return str(image_source or "").strip() in SMOKE_ONLY_IMAGE_SOURCES


def build_service_artifact_fields(
    *,
    run_id: str,
    mode: str,
    program_id: Optional[str] = None,
    trigger_source: str,
    validation_result: Optional[str],
    issue_codes: Optional[List[str]] = None,
    called_gemini: bool = False,
    image_outcome: Optional[ServiceImageOutcome] = None,
    image_bundle: Optional[TodayGenieServiceImageBundle] = None,
    html_path: Optional[str] = None,
    owner_review_html_path: Optional[str] = None,
    smtp_attempted: bool = False,
    email_sent: bool = False,
    customer_delivery_status: str = "not_sent",
    response_status: Optional[int] = None,
    workflow_status: Optional[str] = None,
    error_code: Optional[str] = None,
    owner_review_url: Optional[str] = None,
    artifact_storage_durable: bool = False,
) -> Dict[str, Any]:
    """Standard admin_runs metadata for service-level full runs."""
    called_image_api = False
    image_generation_status = IMAGE_GEN_NOT_ATTEMPTED
    image_source = ""
    generated_image_path: Optional[str] = None

    if image_bundle is not None:
        called_image_api = image_bundle.called_image_api
        if image_bundle.ok:
            image_generation_status = IMAGE_GEN_GENERATED
            image_source = IMAGE_SOURCE_GENERATED
            generated_image_path = image_bundle.primary_generated_image_path or image_bundle.top.generated_image_path
        elif image_bundle.called_image_api:
            image_generation_status = IMAGE_GEN_FAILED
            image_source = image_bundle.top.image_source or image_bundle.bottom.image_source or IMAGE_SOURCE_FALLBACK
            generated_image_path = image_bundle.top.generated_image_path or image_bundle.bottom.generated_image_path
    elif image_outcome is not None:
        called_image_api = bool(image_outcome.called_image_api)
        image_generation_status = image_outcome.image_generation_status
        image_source = image_outcome.image_source
        generated_image_path = image_outcome.generated_image_path

    meta: Dict[str, Any] = {
        "run_id": run_id,
        "mode": mode,
        "program_id": program_id or mode,
        "service_full_run": True,
        "trigger_source": trigger_source,
        "validation_result": validation_result,
        "issue_codes": list(issue_codes or []),
        "called_gemini": bool(called_gemini),
        "called_image_api": called_image_api,
        "image_generation_status": image_generation_status,
        "generated_image_path": generated_image_path,
        "image_source": image_source,
        "html_path": html_path,
        "owner_review_html_path": owner_review_html_path,
        "smtp_attempted": bool(smtp_attempted),
        "email_sent": bool(email_sent),
        "customer_delivery_status": customer_delivery_status,
        "owner_review_status": "pending_review",
        "response_status": response_status,
        "workflow_status": workflow_status,
    }
    if error_code:
        meta["error_code"] = error_code
    if owner_review_url:
        meta["owner_review_url"] = owner_review_url
    meta["artifact_storage_durable"] = bool(artifact_storage_durable)
    return meta
