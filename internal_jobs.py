"""Internal job endpoints for scheduler/automation dispatch."""
from __future__ import annotations

import hmac
import json
import logging
import os
from typing import Any, Callable, Dict, Optional

from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from admin_store import (
    check_artifact_store_ready,
    derive_artifact_status,
    list_run_artifacts,
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
from genie_schedule_policy import (
    ScheduledWeekendSkip,
    get_kst_now,
    today_genie_weekend_skip_payload,
)
from orchestrator import execute_orchestrator_run
from today_genie_execution_identity import (
    EXECUTION_CLASS_NATURAL_SCHEDULED,
    FIRST_FAILED_STAGE_EXECUTION_CLASSIFICATION,
    FIRST_FAILED_STAGE_NATURAL_SLOT_GATE,
    GATE_ACTION_ADMIT,
    GATE_ACTION_FAIL_CLOSED,
    GATE_ACTION_REJECT_INVALID_MATCH,
    GATE_ACTION_SKIP_LEGITIMATE_DUPLICATE,
    TODAY_NATURAL_SCHEDULED_SLOT,
    evaluate_today_natural_slot_gate,
    identity_fields_for_artifact,
    resolve_today_execution_identity,
)

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
    # No silent defaults for identity: missing values fail closed at the gate.
    trigger_source: Optional[str] = None
    execution_class: Optional[str] = None
    scheduled_slot: Optional[str] = None


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
    gate_diagnostics: Optional[Dict[str, Any]] = None,
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
        if gate_diagnostics:
            payload.update(gate_diagnostics)
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
        "execution_class": view.get("execution_class"),
        "scheduled_slot": view.get("scheduled_slot"),
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
    if gate_diagnostics:
        for key, value in gate_diagnostics.items():
            if key not in payload and value is not None:
                payload[key] = value
    for key in _FORBIDDEN_RESPONSE_KEYS:
        payload.pop(key, None)
    return payload


def _emit_today_natural_gate_failure(
    *,
    decision_diagnostics: Dict[str, Any],
    trigger_source: str,
    error_code: str,
    issue_codes: list,
    first_failed_stage: str,
    dry_run: bool = False,
) -> bool:
    from owner_review_failure_events import emit_owner_review_run_failed_once

    kst = str(decision_diagnostics.get("kst_schedule_date") or get_kst_now().date().isoformat())
    slot = str(decision_diagnostics.get("scheduled_slot") or decision_diagnostics.get("current_requested_slot") or "unknown")
    synthetic_run_id = (
        f"gate_{kst.replace('-', '')}_{slot.replace(':', '')}_"
        f"{str(error_code or 'gate')[:48]}"
    )
    return emit_owner_review_run_failed_once(
        program_id="today_genie",
        run_id=synthetic_run_id,
        trigger_source=trigger_source or "unknown",
        first_failed_stage=first_failed_stage,
        error_code=error_code,
        issue_codes=issue_codes,
        email_sent=False,
        artifact_saved=False,
        dry_run=dry_run,
        force_emit=True,
        extra_fields={
            k: decision_diagnostics.get(k)
            for k in (
                "execution_class",
                "scheduled_slot",
                "matched_run_id",
                "matched_execution_class",
                "matched_terminal_status",
                "matched_slot",
                "duplicate_reason",
                "gate_action",
                "kst_schedule_date",
            )
            if decision_diagnostics.get(k) is not None
        },
    )


def _today_natural_gate_response(
    decision,
    *,
    dry_run: bool = False,
) -> Optional[JSONResponse]:
    """Return an HTTP response when the gate blocks admission; else None."""
    diagnostics = decision.diagnostic_payload()
    trigger = ""
    if decision.identity is not None:
        trigger = decision.identity.trigger_source

    if decision.action == GATE_ACTION_FAIL_CLOSED:
        _emit_today_natural_gate_failure(
            decision_diagnostics=diagnostics,
            trigger_source=trigger,
            error_code=decision.error_code or "execution_identity_invalid",
            issue_codes=list(decision.issue_codes),
            first_failed_stage=FIRST_FAILED_STAGE_EXECUTION_CLASSIFICATION,
            dry_run=dry_run,
        )
        logger.error(
            "create_owner_review: natural gate fail-closed diagnostics=%s",
            json.dumps(diagnostics, ensure_ascii=False, sort_keys=True),
        )
        return JSONResponse(
            status_code=422,
            content={
                "ok": False,
                "error": decision.error_code or "execution_identity_invalid",
                "message": decision.message,
                "issue_codes": list(decision.issue_codes),
                **{k: v for k, v in diagnostics.items() if k not in {"error_code", "issue_codes", "message"}},
            },
        )

    if decision.action == GATE_ACTION_REJECT_INVALID_MATCH:
        emitted = _emit_today_natural_gate_failure(
            decision_diagnostics=diagnostics,
            trigger_source=trigger or DEFAULT_TRIGGER_SOURCE,
            error_code=decision.error_code or "invalid_natural_slot_duplicate_match",
            issue_codes=list(decision.issue_codes),
            first_failed_stage=FIRST_FAILED_STAGE_NATURAL_SLOT_GATE,
            dry_run=dry_run,
        )
        logger.error(
            "create_owner_review: invalid natural-slot match diagnostics=%s emitted=%s",
            json.dumps(diagnostics, ensure_ascii=False, sort_keys=True),
            emitted,
        )
        return JSONResponse(
            status_code=409,
            content={
                "ok": False,
                "error": decision.error_code or "invalid_natural_slot_duplicate_match",
                "message": decision.message,
                "skipped_duplicate": False,
                "duplicate": True,
                "failure_event_emitted": emitted,
                **diagnostics,
            },
        )

    if decision.action == GATE_ACTION_SKIP_LEGITIMATE_DUPLICATE:
        matched_run_id = decision.match.run_id if decision.match else ""
        logger.info(
            "create_owner_review: legitimate natural-slot duplicate diagnostics=%s",
            json.dumps(diagnostics, ensure_ascii=False, sort_keys=True),
        )
        summary = _safe_owner_review_summary(
            matched_run_id,
            skipped_duplicate=True,
            message=decision.message or "natural_slot_already_completed",
            gate_diagnostics=diagnostics,
        )
        # Legitimate duplicate is operator-visible success for Scheduler retries.
        summary["ok"] = True
        summary["duplicate"] = True
        return JSONResponse(status_code=200, content=summary)

    return None


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

    identity, identity_error, identity_issues = resolve_today_execution_identity(
        execution_class=body.execution_class,
        scheduled_slot=body.scheduled_slot,
        trigger_source=body.trigger_source,
        now=get_kst_now(),
    )
    artifacts = list_run_artifacts(limit=100)
    decision = evaluate_today_natural_slot_gate(
        identity=identity,
        identity_error=identity_error,
        identity_issues=identity_issues,
        artifacts=artifacts,
    )
    gate_block = _today_natural_gate_response(decision, dry_run=body.dry_run)
    if gate_block is not None:
        return gate_block

    assert identity is not None  # admit path always has identity
    trigger = identity.trigger_source

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

    if body.service_full_run:
        from today_genie_service_full_run import run_today_genie_service_full_run

        try:
            payload = run_today_genie_service_full_run(
                trigger_source=trigger,
                send_owner_email=body.send_owner_email,
                dry_run=body.dry_run,
            )
            if isinstance(payload, dict):
                payload.update(
                    {
                        k: v
                        for k, v in identity_fields_for_artifact(identity).items()
                        if v is not None
                    }
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

    try:
        run_id, result, email_sent = execute_orchestrator_run(
            "today_genie",
            trigger_source=trigger,
            send_owner_email=body.send_owner_email,
            execution_class=identity.execution_class,
            scheduled_slot=identity.scheduled_slot,
        )
    except ScheduledWeekendSkip as exc:
        logger.info("create_owner_review: orchestrator weekend guard payload=%s", exc.payload)
        return JSONResponse(status_code=200, content=exc.payload)
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
    summary.update(
        {k: v for k, v in identity_fields_for_artifact(identity).items() if v is not None}
    )
    logger.info(
        "create_owner_review: run_id=%s email_sent=%s response_status=%s execution_class=%s scheduled_slot=%s",
        run_id,
        summary.get("email_sent"),
        summary.get("response_status"),
        identity.execution_class,
        identity.scheduled_slot,
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


@router.post("/internal/jobs/natural-run-watchdog")
def natural_run_watchdog_endpoint(
    request: Request,
    x_genie_internal_job_token: Optional[str] = Header(None, alias="X-Genie-Internal-Job-Token"),
):
    """SLA poll: diagnose missed natural runs and email Korean reports.

    Never auto-retries, never customer-sends, never Scheduler-reruns.
    """
    auth_fail = _verify_internal_job_token(request, x_genie_internal_job_token)
    if auth_fail is not None:
        return auth_fail

    from admin_store import list_run_artifacts
    from natural_run_watchdog import run_watchdog_poll

    try:
        artifacts = list_run_artifacts(limit=100)
        summary = run_watchdog_poll(
            artifacts=artifacts,
            now=get_kst_now(),
            paused_programs=["tomorrow_genie"],
        )
    except Exception as exc:
        logger.exception(
            "natural_run_watchdog failed error_type=%s",
            type(exc).__name__,
        )
        return JSONResponse(
            status_code=500,
            content={
                "ok": False,
                "error": "watchdog_failed",
                "error_type": type(exc).__name__,
                "auto_retry": 0,
                "customer_send": 0,
            },
        )
    summary["auto_retry"] = 0
    summary["customer_send"] = 0
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

    try:
        payload = create_keysuri_owner_review_job(
            normalized,
            trigger_source=body.trigger_source,
            dry_run=body.dry_run,
            service_full_run=body.service_full_run,
            send_owner_email=body.send_owner_email,
        )
    except Exception as exc:
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
