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

# Flat candidate-funnel diagnostic keys mirrored onto the run artifact so a
# pre-Gemini hold (or a successful controlled backfill) can be diagnosed straight
# from the JSON without re-running the pipeline. Sourced from the selection
# funnel summary; missing keys are recorded as null with an unavailable_reason.
_FUNNEL_ARTIFACT_KEYS = (
    "normalized_candidate_count",
    "korea_scope_candidate_count",
    "relevance_candidate_count",
    "candidate_count_before_dedup",
    "sent_log_read_count",
    "exposure_log_read_count",
    "recent_combined_log_count",
    "dedup_removed_count",
    "dedup_removed_by_sent_log_count",
    "dedup_removed_by_exposure_log_count",
    "candidate_count_after_dedup",
    "final_selected_count",
    "hold_reason",
)


def _candidate_funnel_artifact_fields(
    *,
    candidate_funnel_summary: Optional[Dict[str, Any]],
    fetched_item_count: Optional[int],
    hold_reason: Optional[str],
    exposure_dedup_backfill_used: bool,
) -> Dict[str, Any]:
    """Flatten the candidate funnel onto artifact fields for cold diagnosis."""
    funnel = candidate_funnel_summary if isinstance(candidate_funnel_summary, dict) else {}
    out: Dict[str, Any] = {
        "candidate_funnel_summary": funnel or None,
        "fetched_item_count": fetched_item_count,
        "raw_fetched_count": fetched_item_count,
        "exposure_dedup_backfill_used": bool(exposure_dedup_backfill_used),
    }
    for key in _FUNNEL_ARTIFACT_KEYS:
        out[key] = funnel.get(key)
    if hold_reason and not out.get("hold_reason"):
        out["hold_reason"] = hold_reason
    if not funnel:
        out["candidate_funnel_unavailable_reason"] = (
            "selection_funnel_summary_not_produced_by_smoke_result"
        )
    return out


@dataclass
class ServiceImageOutcome:
    called_image_api: bool = False
    image_generation_status: str = IMAGE_GEN_NOT_ATTEMPTED
    image_source: str = ""
    generated_image_path: Optional[str] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    image_api_provider: str = "google_cloud_vertex_ai"
    image_model_raw: Optional[str] = None
    image_model_normalized: Optional[str] = None
    image_pricing_mode: str = "standard_paygo"
    image_request_count: int = 0
    image_successful_output_count: int = 0
    image_failed_request_count: int = 0
    image_retry_count: int = 0
    image_discarded_output_count: int = 0
    image_locally_derived_asset_count: int = 0
    image_cache_reuse_count: int = 0
    image_static_fallback_count: int = 0
    image_output_tokens: Optional[int] = None
    image_evidence_confidence: Optional[str] = None
    image_evidence_source: Optional[str] = None

    @property
    def ok(self) -> bool:
        return service_image_passes(self)

    def cost_usage(self) -> Dict[str, Any]:
        successful = self.image_successful_output_count
        requests = self.image_request_count
        # Compatibility for injected/older outcome producers that already
        # satisfy the explicit API-success contract but predate counters.
        if self.ok and successful == 0 and requests == 0:
            successful = 1
            requests = 1
        return {
            "image_api_provider": self.image_api_provider,
            "image_model_raw": self.image_model_raw,
            "image_model_normalized": self.image_model_normalized,
            "image_pricing_mode": self.image_pricing_mode,
            "image_request_count": requests,
            "image_successful_output_count": successful,
            "image_failed_request_count": self.image_failed_request_count,
            "image_retry_count": self.image_retry_count,
            "image_discarded_output_count": self.image_discarded_output_count,
            "image_locally_derived_asset_count": self.image_locally_derived_asset_count,
            "image_cache_reuse_count": self.image_cache_reuse_count,
            "image_static_fallback_count": self.image_static_fallback_count,
            "image_output_tokens": self.image_output_tokens,
            "image_evidence_confidence": self.image_evidence_confidence
            or ("medium" if self.ok else None),
            "image_evidence_source": self.image_evidence_source
            or ("service_image_success_contract" if self.ok else None),
            "generated_image_count_semantics": "paid_successful_api_outputs",
        }


@dataclass
class TodayGenieServiceImageBundle:
    top: ServiceImageOutcome = field(default_factory=ServiceImageOutcome)
    bottom: ServiceImageOutcome = field(default_factory=ServiceImageOutcome)
    primary_generated_image_path: Optional[str] = None
    # Today_Geenee post-process brand footer/watermark state (MirAI:ON).
    watermark_applied: bool = False
    watermark_label: str = ""
    watermark_method: str = ""
    watermark_paths: List[str] = field(default_factory=list)
    watermark_error: Optional[str] = None

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
    candidate_funnel_summary: Optional[Dict[str, Any]] = None,
    fetched_item_count: Optional[int] = None,
    hold_reason: Optional[str] = None,
    exposure_dedup_backfill_used: bool = False,
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
    outcomes = []
    if image_bundle is not None:
        outcomes = [image_bundle.top, image_bundle.bottom]
    elif image_outcome is not None:
        outcomes = [image_outcome]
    if outcomes:
        outcome_usage = [item.cost_usage() for item in outcomes]
        meta.update(
            {
                "image_api_provider": next(
                    (item.image_api_provider for item in outcomes if item.image_api_provider), None
                ),
                "image_model_raw": next(
                    (item.image_model_raw for item in outcomes if item.image_model_raw), None
                ),
                "image_model_normalized": next(
                    (item.image_model_normalized for item in outcomes if item.image_model_normalized), None
                ),
                "image_pricing_mode": next(
                    (item.image_pricing_mode for item in outcomes if item.image_pricing_mode), None
                ),
                "image_request_count": sum(item["image_request_count"] for item in outcome_usage),
                "image_successful_output_count": sum(
                    item["image_successful_output_count"] for item in outcome_usage
                ),
                "image_failed_request_count": sum(item.image_failed_request_count for item in outcomes),
                "image_retry_count": sum(item.image_retry_count for item in outcomes),
                "image_discarded_output_count": sum(
                    item.image_discarded_output_count for item in outcomes
                ),
                "image_locally_derived_asset_count": sum(
                    item.image_locally_derived_asset_count for item in outcomes
                ),
                "image_cache_reuse_count": sum(item.image_cache_reuse_count for item in outcomes),
                "image_static_fallback_count": sum(
                    item.image_static_fallback_count for item in outcomes
                ),
                "image_output_tokens": sum(item.image_output_tokens or 0 for item in outcomes)
                or None,
                "generated_image_count_semantics": "paid_successful_api_outputs",
                "image_evidence_confidence": next(
                    (item.image_evidence_confidence for item in outcomes if item.image_evidence_confidence),
                    None,
                ),
                "image_evidence_source": next(
                    (item.image_evidence_source for item in outcomes if item.image_evidence_source),
                    None,
                ),
            }
        )
    if error_code:
        meta["error_code"] = error_code
    if owner_review_url:
        meta["owner_review_url"] = owner_review_url
    meta["artifact_storage_durable"] = bool(artifact_storage_durable)
    meta.update(
        _candidate_funnel_artifact_fields(
            candidate_funnel_summary=candidate_funnel_summary,
            fetched_item_count=fetched_item_count,
            hold_reason=hold_reason,
            exposure_dedup_backfill_used=exposure_dedup_backfill_used,
        )
    )
    return meta
