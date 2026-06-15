"""Internal job endpoints for scheduler/automation dispatch."""
from __future__ import annotations

import hmac
import logging
import os
from typing import Any, Callable, Dict, Optional

from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from admin_store import (
    check_artifact_store_ready,
    derive_artifact_status,
    find_scheduled_owner_review_for_kst_date,
    load_run_artifact,
    normalize_artifact_view,
    process_approval_timeouts,
)
from keysuri_live_source_smoke import (
    PROGRAM_GLOBAL,
    PROGRAM_KOREA,
    LiveSourceSmokeResult,
    run_keysuri_live_source_smoke,
)
from orchestrator import execute_orchestrator_run

router = APIRouter(tags=["internal"])
logger = logging.getLogger(__name__)

KEYSURI_SCHEDULED_PROGRAM_IDS = frozenset({PROGRAM_GLOBAL, PROGRAM_KOREA})
FORBIDDEN_GENIE_PROGRAM_IDS = frozenset(
    {
        "today_genie",
        "tomorrow_genie",
        "today_geenee",
        "tomorrow_geenie",
    }
)
DEFAULT_TRIGGER_SOURCE = "scheduled_owner_review"

_FORBIDDEN_RESPONSE_KEYS = frozenset(
    {
        "email_images",
        "image_prompt_contract",
        "action_log",
        "runtime_input",
        "data",
        "policy",
        "issue_details",
        "content_quality_warnings",
    }
)


class OwnerReviewJobRequest(BaseModel):
    service_full_run: bool = False
    send_owner_email: bool = True
    dry_run: bool = False
    trigger_source: str = DEFAULT_TRIGGER_SOURCE


class KeysuriOwnerReviewJobRequest(BaseModel):
    program_id: Optional[str] = Field(default=None)
    service_full_run: bool = False
    send_owner_email: bool = True
    dry_run: bool = False
    trigger_source: str = DEFAULT_TRIGGER_SOURCE


def _internal_job_token() -> str:
    return os.getenv("GENIE_INTERNAL_JOB_TOKEN", "").strip()


def _verify_internal_job_token(
    request: Request,
    header_token: Optional[str],
) -> Optional[JSONResponse]:
    expected = _internal_job_token()
    if not expected:
        return JSONResponse(
            status_code=503,
            content={"ok": False, "error": "internal_job_token_not_configured"},
        )
    provided = (header_token or "").strip()
    if not provided or not hmac.compare_digest(provided, expected):
        return JSONResponse(
            status_code=403,
            content={"ok": False, "error": "forbidden"},
        )
    return None


def _artifact_store_not_ready_response() -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content={"ok": False, "error": "artifact_store_not_ready"},
    )


def _safe_owner_review_summary(
    run_id: str,
    *,
    skipped_duplicate: bool,
    message: Optional[str] = None,
) -> Dict[str, Any]:
    meta = load_run_artifact(run_id, normalize=False)
    if not meta:
        payload: Dict[str, Any] = {
            "ok": True,
            "skipped_duplicate": skipped_duplicate,
            "run_id": run_id,
            "mode": "today_genie",
        }
        if message:
            payload["message"] = message
        return payload

    view = normalize_artifact_view(meta, run_id)
    artifact_status = str(view.get("artifact_status") or derive_artifact_status(view))
    payload = {
        "ok": True,
        "skipped_duplicate": skipped_duplicate,
        "run_id": run_id,
        "mode": "today_genie",
        "response_status": view.get("response_status"),
        "validation_result": view.get("validation_result"),
        "workflow_status": view.get("workflow_status"),
        "artifact_status": artifact_status,
        "owner_review_status": view.get("owner_review_status"),
        "email_sent": bool(view.get("email_sent")),
        "customer_delivery_status": view.get("customer_delivery_status") or "not_sent",
    }
    for image_key in (
        "called_image_api",
        "image_source",
        "image_generation_status",
        "generated_image_path",
        "generated_image_paths",
        "fallback_used",
        "artifact_storage_backend",
        "artifact_storage_durable",
        "owner_review_url",
    ):
        if image_key in view and view.get(image_key) is not None:
            payload[image_key] = view.get(image_key)
    if message:
        payload["message"] = message
    for key in _FORBIDDEN_RESPONSE_KEYS:
        payload.pop(key, None)
    return payload


def validate_keysuri_owner_review_program_id(
    program_id: Optional[str],
) -> tuple[Optional[str], Optional[Dict[str, Any]]]:
    """Return (normalized_program_id, error_payload) for HTTP 400 responses."""
    key = (program_id or "").strip()
    if not key:
        return None, {"ok": False, "error": "program_id_required"}
    if key in FORBIDDEN_GENIE_PROGRAM_IDS:
        return None, {
            "ok": False,
            "error": "forbidden_genie_program",
            "program_id": key,
        }
    if key not in KEYSURI_SCHEDULED_PROGRAM_IDS:
        return None, {"ok": False, "error": "unknown_program_id", "program_id": key}
    return key, None


def _smoke_result_to_job_payload(
    result: LiveSourceSmokeResult,
    *,
    program_id: str,
    trigger_source: str,
) -> Dict[str, Any]:
    return {
        "ok": result.ok,
        "program_id": program_id,
        "dry_run": False,
        "trigger_source": trigger_source,
        "html_path": result.html_path,
        "source_pack_path": result.source_pack_path,
        "called_gemini": result.called_gemini,
        "parse_status": result.parse_status,
        "preview_overall_status": result.preview_overall_status,
        "ready_for_owner_visual_review": result.ready_for_owner_visual_review,
        "send_attempted": result.send_attempted,
        "error": result.error,
        "side_effects": result.side_effects,
    }


def create_keysuri_owner_review_job(
    program_id: str,
    *,
    trigger_source: str = DEFAULT_TRIGGER_SOURCE,
    dry_run: bool = False,
    service_full_run: bool = False,
    send_owner_email: bool = True,
    smoke_runner: Optional[Callable[..., LiveSourceSmokeResult]] = None,
) -> Dict[str, Any]:
    """
    Dispatch Kee-Suri scheduled owner-review generation.

    dry_run=True performs validation only — no Gemini, HTML, or email.
    service_full_run=True uses keysuri_service_full_run (generated images, admin_runs, SMTP).
    """
    normalized, err = validate_keysuri_owner_review_program_id(program_id)
    if err:
        raise ValueError(str(err.get("error")))

    trigger = (trigger_source or DEFAULT_TRIGGER_SOURCE).strip() or DEFAULT_TRIGGER_SOURCE

    if service_full_run:
        from keysuri_service_full_run import run_keysuri_service_full_run

        return run_keysuri_service_full_run(
            normalized,
            trigger_source=trigger,
            send_owner_email=send_owner_email,
            dry_run=dry_run,
            smoke_runner=smoke_runner,
        )

    if dry_run:
        return {
            "ok": True,
            "program_id": normalized,
            "dry_run": True,
            "trigger_source": trigger,
            "would_run": True,
            "service_full_run": False,
        }

    runner = smoke_runner or run_keysuri_live_source_smoke
    result = runner(
        program_id=normalized,
        use_gemini=True,
        contract_preview=True,
        send=False,
    )
    payload = _smoke_result_to_job_payload(
        result,
        program_id=normalized,
        trigger_source=trigger,
    )
    payload["service_full_run"] = False
    return payload


@router.post("/internal/jobs/create-owner-review")
def create_owner_review_endpoint(
    request: Request,
    body: OwnerReviewJobRequest = OwnerReviewJobRequest(),
    x_genie_internal_job_token: Optional[str] = Header(None, alias="X-Genie-Internal-Job-Token"),
):
    """Scheduler entry: today_genie owner-review via execute_orchestrator_run (no admin session)."""
    auth_fail = _verify_internal_job_token(request, x_genie_internal_job_token)
    if auth_fail is not None:
        return auth_fail

    store_err, _desc = check_artifact_store_ready()
    if store_err:
        return _artifact_store_not_ready_response()

    trigger = (body.trigger_source or DEFAULT_TRIGGER_SOURCE).strip() or DEFAULT_TRIGGER_SOURCE

    if body.service_full_run:
        from today_genie_service_full_run import run_today_genie_service_full_run

        try:
            payload = run_today_genie_service_full_run(
                trigger_source=trigger,
                send_owner_email=body.send_owner_email,
                dry_run=body.dry_run,
            )
        except Exception as exc:
            logger.exception(
                "create_owner_review service_full_run failed error_type=%s",
                type(exc).__name__,
            )
            return JSONResponse(
                status_code=500,
                content={
                    "ok": False,
                    "error": "orchestration_failed",
                    "error_type": type(exc).__name__,
                    "service_full_run": True,
                },
            )
        status_code = 200 if payload.get("ok") else 500
        return JSONResponse(status_code=status_code, content=payload)

    existing = find_scheduled_owner_review_for_kst_date("today_genie")
    if existing:
        return JSONResponse(
            status_code=200,
            content=_safe_owner_review_summary(
                existing,
                skipped_duplicate=True,
                message="owner_review_already_exists_for_kst_date",
            ),
        )

    try:
        run_id, result, email_sent = execute_orchestrator_run(
            "today_genie",
            trigger_source=trigger,
        )
    except Exception as exc:
        logger.exception(
            "create_owner_review: orchestration_failed error_type=%s",
            type(exc).__name__,
        )
        return JSONResponse(
            status_code=500,
            content={
                "ok": False,
                "error": "orchestration_failed",
                "error_type": type(exc).__name__,
            },
        )

    if not run_id:
        logger.error(
            "create_owner_review: orchestration_failed error_type=MissingRunId response_status=%s",
            getattr(result, "response_status", None),
        )
        return JSONResponse(
            status_code=500,
            content={
                "ok": False,
                "error": "orchestration_failed",
                "error_type": "MissingRunId",
            },
        )

    summary = _safe_owner_review_summary(run_id, skipped_duplicate=False)
    if not summary.get("email_sent") and email_sent:
        summary["email_sent"] = True
    logger.info(
        "create_owner_review: run_id=%s email_sent=%s response_status=%s",
        run_id,
        summary.get("email_sent"),
        summary.get("response_status"),
    )
    return JSONResponse(status_code=200, content=summary)


@router.post("/internal/jobs/process-approval-timeouts")
def process_approval_timeouts_endpoint(
    request: Request,
    x_genie_internal_job_token: Optional[str] = Header(None, alias="X-Genie-Internal-Job-Token"),
):
    """Scheduler entry: scan pending owner-review runs for approval timeout processing."""
    auth_fail = _verify_internal_job_token(request, x_genie_internal_job_token)
    if auth_fail is not None:
        return auth_fail

    store_err, _desc = check_artifact_store_ready()
    if store_err:
        return _artifact_store_not_ready_response()

    try:
        summary = process_approval_timeouts()
    except Exception as exc:
        logger.exception(
            "process_approval_timeouts failed error_type=%s",
            type(exc).__name__,
        )
        return JSONResponse(
            status_code=500,
            content={
                "ok": False,
                "error": "timeout_processor_failed",
                "error_type": type(exc).__name__,
            },
        )

    status_code = 200 if summary.get("ok") else 503
    return JSONResponse(status_code=status_code, content=summary)


@router.post("/internal/jobs/create-keysuri-owner-review")
def create_keysuri_owner_review_endpoint(
    request: Request,
    body: KeysuriOwnerReviewJobRequest,
    x_genie_internal_job_token: Optional[str] = Header(None, alias="X-Genie-Internal-Job-Token"),
):
    """Scheduler entry: Kee-Suri owner-review contract-preview dispatch."""
    auth_fail = _verify_internal_job_token(request, x_genie_internal_job_token)
    if auth_fail is not None:
        return auth_fail

    normalized, err = validate_keysuri_owner_review_program_id(body.program_id)
    if err:
        return JSONResponse(status_code=400, content=err)

    try:
        payload = create_keysuri_owner_review_job(
            normalized,
            trigger_source=body.trigger_source,
            dry_run=body.dry_run,
            service_full_run=body.service_full_run,
            send_owner_email=body.send_owner_email,
        )
    except Exception as exc:
        logger.exception(
            "create_keysuri_owner_review failed program_id=%s error_type=%s",
            normalized,
            type(exc).__name__,
        )
        return JSONResponse(
            status_code=500,
            content={
                "ok": False,
                "error": "orchestration_failed",
                "error_type": type(exc).__name__,
                "program_id": normalized,
            },
        )

    status_code = 200 if payload.get("ok", True) else 500
    return JSONResponse(status_code=status_code, content=payload)
