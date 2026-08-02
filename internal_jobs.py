"""Internal job endpoints for scheduler/automation dispatch."""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Callable, Dict, Optional

from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from admin_store import (
    admin_artifact_bucket_name,
    check_artifact_store_ready,
    derive_artifact_status,
    find_scheduled_owner_review_for_kst_date,
    generate_run_id,
    load_run_artifact,
    normalize_artifact_view,
    process_approval_timeouts,
)
from internal_auth import verify_internal_request
from keysuri_live_source_smoke import (
    PROGRAM_GLOBAL,
    PROGRAM_KOREA,
    LiveSourceSmokeResult,
    run_keysuri_live_source_smoke,
)
from genie_schedule_policy import (
    ScheduledWeekendSkip,
    get_kst_now,
    today_genie_weekend_skip_payload,
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

_KEYSURI_JOB_LOG_SAFE_PAYLOAD_KEYS = (
    "ok",
    "run_id",
    "validation_result",
    "issue_codes",
    "error",
    "error_type",
    "artifact_status",
    "called_gemini",
    "called_image_api",
    "image_source",
    "smtp_attempted",
    "email_sent",
    "customer_delivery_status",
    "approve_customer_final_send",
    "cost_estimate",
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


def _execution_reservations_enabled() -> bool:
    raw = os.getenv("GENIE_EXECUTION_RESERVATIONS", "").strip().lower()
    if raw:
        return raw in {"1", "true", "yes", "on"}
    return bool(
        admin_artifact_bucket_name()
        or os.getenv("GENIE_EXECUTION_STATE_ROOT", "").strip()
    )


def _owner_review_delivery_configured() -> bool:
    """True only when this process could reach the real owner SMTP sender."""
    from email_sender import smtp_configured

    gate = os.getenv("GENIE_OWNER_REVIEW_SEND", "").strip().lower()
    return gate in {"1", "true", "yes", "on"} or smtp_configured()


def _reserve_owner_review_execution(program_id: str, trigger_source: str):
    if not _execution_reservations_enabled():
        return None
    from execution_state import manual_execution_key, reserve_execution, scheduled_execution_key

    run_id = generate_run_id(program_id)
    trigger = str(trigger_source or DEFAULT_TRIGGER_SOURCE).strip() or DEFAULT_TRIGGER_SOURCE
    if trigger.lower().startswith("scheduled"):
        logical_key = scheduled_execution_key(program_id, trigger_source="scheduled")
    else:
        logical_key = manual_execution_key(program_id, run_id, trigger_source=trigger)
    return reserve_execution(logical_key, program_id=program_id, run_id=run_id)


def _reservation_response(reservation):
    if reservation is None:
        return None
    if reservation.execute and reservation.accepted_repair:
        from execution_state import update_execution

        update_execution(
            reservation.logical_execution_key,
            expected_owner_id=reservation.owner_id,
            state="owner_review_emailed",
            last_safe_state="owner_review_emailed",
        )
        return JSONResponse(
            status_code=200,
            content={
                "ok": True,
                "email_sent": True,
                "sender_called": False,
                "checkpoint_repaired": True,
                "logical_execution_key": reservation.logical_execution_key,
                "run_id": reservation.run_id,
            },
        )
    if not reservation.execute:
        return JSONResponse(
            status_code=200,
            content={
                "ok": True,
                "skipped_duplicate": True,
                "logical_execution_key": reservation.logical_execution_key,
                "existing_run_id": reservation.run_id,
                "state": reservation.previous_state,
            },
        )
    return None


def _finish_reservation(reservation, payload: Dict[str, Any]) -> None:
    if reservation is None:
        return
    from execution_state import owner_review_accepted, load_execution, update_execution

    current = load_execution(reservation.logical_execution_key) or {}
    if owner_review_accepted(current):
        state = "owner_review_emailed"
        last_safe = state
    elif payload.get("ok") and not payload.get("email_sent"):
        state = "artifacts_ready"
        last_safe = state
    else:
        terminal_errors = {
            "validation_blocked",
            "global_post_render_qa_blocked",
            "korea_post_render_qa_blocked",
            "keysuri_korean_connector_ellipsis_blocked",
        }
        is_today = str(current.get("program_id") or "") == "today_genie"
        state = "failed_terminal" if is_today or str(payload.get("error") or "") in terminal_errors else "failed_retryable"
        last_safe = "artifacts_ready" if payload.get("html_path") else "running"
    update_execution(
        reservation.logical_execution_key,
        expected_owner_id=reservation.owner_id,
        state=state,
        last_safe_state=last_safe,
        error_code=str(payload.get("error") or "")[:120],
    )


def _verify_internal_job_token(
    request: Request,
    header_token: Optional[str],
) -> Optional[JSONResponse]:
    result = verify_internal_request(
        authorization=request.headers.get("Authorization", ""),
        header_token=header_token,
    )
    if not result.ok:
        return JSONResponse(
            status_code=result.status_code,
            content={"ok": False, "error": result.error},
        )
    return None


def _artifact_store_not_ready_response() -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content={"ok": False, "error": "artifact_store_not_ready"},
    )


def _bool_from_payload(payload: Dict[str, Any], *keys: str) -> bool:
    for key in keys:
        if key in payload:
            return bool(payload.get(key))
    return False


def _list_from_payload(payload: Dict[str, Any], *keys: str) -> list[Any]:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, list):
            return value
        if value:
            return [value]
    return []


def _keysuri_owner_review_failure_stage(payload: Dict[str, Any]) -> str:
    validation_result = str(payload.get("validation_result") or "").strip().lower()
    issue_codes = _list_from_payload(payload, "issue_codes", "issues")
    error_text = str(payload.get("error") or "").strip().lower()
    if validation_result == "block" or issue_codes:
        return "validation"
    if _bool_from_payload(payload, "smtp_attempted", "owner_email_smtp_attempted") and not _bool_from_payload(
        payload, "email_sent", "owner_review_email_sent"
    ):
        return "smtp"
    if not _bool_from_payload(payload, "called_gemini") and any(
        marker in error_text for marker in ("source", "fetch", "pre_generation", "pre-generation")
    ):
        return "source_or_pre_generation"
    if _bool_from_payload(payload, "called_gemini") and not _bool_from_payload(payload, "called_image_api"):
        return "generation_or_validation_before_image"
    if _bool_from_payload(payload, "called_image_api") and not _bool_from_payload(
        payload, "email_sent", "owner_review_email_sent"
    ):
        return "artifact_or_email"
    return "unknown_safe_fail"


def _keysuri_owner_review_log_fields(
    *,
    event: str,
    program_id: str,
    trigger_source: str,
    service_full_run: bool,
    send_owner_email: bool,
    dry_run: bool,
    http_status: int,
    payload: Optional[Dict[str, Any]] = None,
    stage: Optional[str] = None,
    error_type: Optional[str] = None,
    error_message: Optional[str] = None,
) -> Dict[str, Any]:
    safe_payload = payload if isinstance(payload, dict) else {}
    fields: Dict[str, Any] = {
        "event": event,
        "program_id": program_id,
        "trigger_source": trigger_source,
        "service_full_run": bool(service_full_run),
        "send_owner_email": bool(send_owner_email),
        "dry_run": bool(dry_run),
        "http_status": int(http_status),
        "stage": stage,
    }
    for key in _KEYSURI_JOB_LOG_SAFE_PAYLOAD_KEYS:
        if key in safe_payload:
            fields[key] = safe_payload.get(key)
    if "smtp_attempted" not in fields and "owner_email_smtp_attempted" in safe_payload:
        fields["smtp_attempted"] = bool(safe_payload.get("owner_email_smtp_attempted"))
    if "approve_customer_final_send" not in fields:
        fields["approve_customer_final_send"] = bool(
            safe_payload.get("approve_customer_final_send") or safe_payload.get("customer_approve_called")
        )
    if error_type:
        fields["error_type"] = error_type
    if error_message:
        fields["error_message"] = str(error_message)[:300]
    return {k: v for k, v in fields.items() if v is not None}


def _log_keysuri_owner_review_job_event(**kwargs: Any) -> None:
    logger.info(json.dumps(_keysuri_owner_review_log_fields(**kwargs), ensure_ascii=False, sort_keys=True))


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
    run_id_override: Optional[str] = None,
    logical_execution_key: str = "",
    expected_owner_id: str = "",
    attempt: int = 1,
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

        kwargs: Dict[str, Any] = {
            "trigger_source": trigger,
            "send_owner_email": send_owner_email,
            "dry_run": dry_run,
            "smoke_runner": smoke_runner,
        }
        if run_id_override:
            kwargs.update(
                run_id_override=run_id_override,
                logical_execution_key=logical_execution_key,
                expected_owner_id=expected_owner_id,
                attempt=attempt,
            )
        return run_keysuri_service_full_run(normalized, **kwargs)

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

    trigger = (body.trigger_source or DEFAULT_TRIGGER_SOURCE).strip() or DEFAULT_TRIGGER_SOURCE
    skip_payload = today_genie_weekend_skip_payload(
        trigger_source=trigger,
        now=get_kst_now(),
    )
    if skip_payload is not None:
        logger.info("create_owner_review: scheduled run skipped payload=%s", skip_payload)
        return JSONResponse(status_code=200, content=skip_payload)

    store_err, _desc = check_artifact_store_ready()
    if store_err:
        return _artifact_store_not_ready_response()

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

    reservation = None
    if body.send_owner_email and not body.dry_run:
        if not _execution_reservations_enabled():
            return JSONResponse(status_code=503, content={"ok": False, "error": "execution_reservations_disabled"})
        reservation = _reserve_owner_review_execution("today_genie", trigger)
        reservation_response = _reservation_response(reservation)
        if reservation_response is not None:
            return reservation_response

    if body.service_full_run:
        from today_genie_service_full_run import run_today_genie_service_full_run

        try:
            kwargs: Dict[str, Any] = {
                "trigger_source": trigger,
                "send_owner_email": body.send_owner_email,
                "dry_run": body.dry_run,
            }
            if reservation is not None:
                kwargs.update(
                    run_id_override=reservation.run_id,
                    logical_execution_key=reservation.logical_execution_key,
                    expected_owner_id=reservation.owner_id,
                    attempt=reservation.attempt,
                )
            payload = run_today_genie_service_full_run(**kwargs)
        except Exception as exc:
            if reservation is not None:
                _finish_reservation(reservation, {"ok": False, "error": "orchestration_failed"})
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
        _finish_reservation(reservation, payload)
        if reservation is not None:
            payload["logical_execution_key"] = reservation.logical_execution_key
            payload["attempt"] = reservation.attempt
        status_code = 200 if payload.get("ok") else 500
        return JSONResponse(status_code=status_code, content=payload)

    try:
        kwargs = {
            "trigger_source": trigger,
            "send_owner_email": body.send_owner_email,
        }
        if reservation is not None:
            kwargs.update(
                run_id_override=reservation.run_id,
                logical_execution_key=reservation.logical_execution_key,
                expected_owner_id=reservation.owner_id,
            )
        run_id, result, email_sent = execute_orchestrator_run("today_genie", **kwargs)
    except ScheduledWeekendSkip as exc:
        logger.info("create_owner_review: orchestrator weekend guard payload=%s", exc.payload)
        return JSONResponse(status_code=200, content=exc.payload)
    except Exception as exc:
        if reservation is not None:
            _finish_reservation(reservation, {"ok": False, "error": "orchestration_failed"})
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

    _finish_reservation(
        reservation,
        {
            "ok": bool(run_id),
            "email_sent": email_sent,
            "error": "" if run_id else "orchestration_failed",
            "html_path": run_id or "",
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


@router.post("/internal/jobs/watch-business-success")
def watch_business_success_endpoint(
    request: Request,
    x_genie_internal_job_token: Optional[str] = Header(None, alias="X-Genie-Internal-Job-Token"),
):
    """Evaluate business deadlines from the bounded metadata index only."""
    auth_fail = _verify_internal_job_token(request, x_genie_internal_job_token)
    if auth_fail is not None:
        return auth_fail
    from business_watchdog import evaluate_business_success_deadlines

    try:
        summary = evaluate_business_success_deadlines()
    except Exception as exc:
        logger.error("business watchdog failed error_type=%s", type(exc).__name__)
        return JSONResponse(
            status_code=500,
            content={
                "ok": False,
                "error": "business_watchdog_failed",
                "error_type": type(exc).__name__,
            },
        )
    # Deadline misses are business signals, not transport failures that should
    # retry the watchdog request itself.
    return JSONResponse(status_code=200, content=summary)


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

    reservation = None
    if body.service_full_run and body.send_owner_email and not body.dry_run:
        if not _execution_reservations_enabled():
            return JSONResponse(status_code=503, content={"ok": False, "error": "execution_reservations_disabled"})
        reservation = _reserve_owner_review_execution(normalized, body.trigger_source)
        reservation_response = _reservation_response(reservation)
        if reservation_response is not None:
            return reservation_response

    try:
        resume_email_only = False
        if reservation is not None and reservation.resume:
            from execution_state import load_execution

            current = load_execution(reservation.logical_execution_key) or {}
            resume_email_only = current.get("last_safe_state") == "artifacts_ready"
        if resume_email_only:
            from keysuri_service_full_run import resume_keysuri_owner_review_email

            payload = resume_keysuri_owner_review_email(
                reservation.run_id,
                logical_execution_key=reservation.logical_execution_key,
                expected_owner_id=reservation.owner_id,
            )
        else:
            payload = create_keysuri_owner_review_job(
                normalized,
                trigger_source=body.trigger_source,
                dry_run=body.dry_run,
                service_full_run=body.service_full_run,
                send_owner_email=body.send_owner_email,
                run_id_override=reservation.run_id if reservation else None,
                logical_execution_key=reservation.logical_execution_key if reservation else "",
                expected_owner_id=reservation.owner_id if reservation else "",
                attempt=reservation.attempt if reservation else 1,
            )
    except Exception as exc:
        if reservation is not None:
            _finish_reservation(reservation, {"ok": False, "error": "orchestration_failed"})
        _log_keysuri_owner_review_job_event(
            event="keysuri_owner_review_endpoint_exception",
            program_id=normalized,
            trigger_source=body.trigger_source,
            service_full_run=body.service_full_run,
            send_owner_email=body.send_owner_email,
            dry_run=body.dry_run,
            http_status=500,
            stage="endpoint_exception",
            error_type=type(exc).__name__,
            error_message=str(exc),
        )
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

    _finish_reservation(reservation, payload)
    if reservation is not None:
        payload["logical_execution_key"] = reservation.logical_execution_key
        payload["attempt"] = reservation.attempt

    status_code = 200 if payload.get("ok", True) else 500
    if status_code == 200:
        _log_keysuri_owner_review_job_event(
            event="keysuri_owner_review_success",
            program_id=normalized,
            trigger_source=body.trigger_source,
            service_full_run=body.service_full_run,
            send_owner_email=body.send_owner_email,
            dry_run=body.dry_run,
            http_status=status_code,
            payload=payload,
            stage="success",
        )
    else:
        _log_keysuri_owner_review_job_event(
            event="keysuri_owner_review_safe_fail_http_500",
            program_id=normalized,
            trigger_source=body.trigger_source,
            service_full_run=body.service_full_run,
            send_owner_email=body.send_owner_email,
            dry_run=body.dry_run,
            http_status=status_code,
            payload=payload,
            stage=_keysuri_owner_review_failure_stage(payload),
        )
    return JSONResponse(status_code=status_code, content=payload)
