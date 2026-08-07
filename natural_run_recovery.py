"""Human-approved natural-run recovery (exactly once). Never customer-sends."""
from __future__ import annotations

import logging
from typing import Any, Callable, Dict, Optional

from natural_run_incident_report import send_recovery_report
from natural_run_incident_store import (
    STATUS_RECOVERY_FAILED,
    STATUS_RECOVERY_SUCCEEDED,
    acquire_recovery_lease,
    complete_recovery,
    load_incident,
    mark_recovery_report_sent,
    save_incident,
)
from today_genie_execution_identity import EXECUTION_CLASS_RECOVERY

logger = logging.getLogger(__name__)

RECOVERY_TRIGGER = "admin_recovery_approved"


def execute_approved_recovery(
    incident_id: str,
    *,
    today_runner: Optional[Callable[..., Any]] = None,
    keysuri_runner: Optional[Callable[..., Any]] = None,
    send_fn: Optional[Callable[..., bool]] = None,
) -> Dict[str, Any]:
    """Acquire lease and run exactly one recovery. No auto second attempt."""
    from natural_run_incident_store import is_verification_incident_id

    incident = load_incident(incident_id)
    if not incident:
        return {"ok": False, "error": "incident_not_found", "auto_retry": 0, "customer_send": 0}

    if incident.get("verification_only") or is_verification_incident_id(incident_id):
        return {
            "ok": False,
            "error": "verification_only_recovery_blocked",
            "incident_id": incident_id,
            "auto_retry": 0,
            "customer_send": 0,
            "recovery_count": 0,
        }

    lease = acquire_recovery_lease(incident_id)
    if not lease:
        return {
            "ok": False,
            "error": "recovery_lease_unavailable",
            "incident_id": incident_id,
            "status": incident.get("status"),
            "auto_retry": 0,
            "customer_send": 0,
        }

    program_id = str(incident.get("program_id") or "")
    slot = str(incident.get("scheduled_slot") or "")
    recovery_run_id: Optional[str] = None
    success = False
    email_sent = False
    validation_result = ""
    artifact_status = ""
    error = ""

    try:
        if program_id == "today_genie":
            runner = today_runner
            if runner is None:
                from orchestrator import execute_orchestrator_run

                def runner(**kwargs):  # type: ignore
                    return execute_orchestrator_run(**kwargs)

            run_id, result, email_sent = runner(
                "today_genie",
                trigger_source=RECOVERY_TRIGGER,
                send_owner_email=True,
                execution_class=EXECUTION_CLASS_RECOVERY,
                scheduled_slot=slot,
            )
            recovery_run_id = run_id
            success = bool(run_id) and bool(email_sent)
            if result is not None:
                payload = getattr(result, "response_data", None) or {}
                if isinstance(payload, dict):
                    validation_result = str(payload.get("validation_result") or "")
            artifact_status = "emailed" if email_sent else "stored"
        elif program_id in {"keysuri_global_tech", "keysuri_korea_tech"}:
            runner = keysuri_runner
            if runner is None:
                from keysuri_service_full_run import run_keysuri_service_full_run

                runner = run_keysuri_service_full_run
            payload = runner(
                program_id,
                trigger_source=RECOVERY_TRIGGER,
                send_owner_email=True,
                dry_run=False,
            )
            if not isinstance(payload, dict):
                payload = {}
            recovery_run_id = str(payload.get("run_id") or "") or None
            email_sent = bool(payload.get("email_sent"))
            validation_result = str(payload.get("validation_result") or "")
            artifact_status = str(payload.get("artifact_status") or "")
            success = bool(payload.get("ok")) and email_sent
            # Stamp recovery identity on child if present
            if recovery_run_id:
                try:
                    from admin_store import update_run_artifact

                    def _stamp(meta: Dict[str, Any]) -> None:
                        meta["execution_class"] = EXECUTION_CLASS_RECOVERY
                        meta["original_incident_id"] = incident_id
                        meta["scheduled_slot"] = slot
                        meta["customer_delivery_status"] = "not_sent"
                        meta["approve_customer_final_send"] = False

                    update_run_artifact(recovery_run_id, _stamp)
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "recovery_meta_stamp_failed error_type=%s", type(exc).__name__
                    )
        else:
            error = "unsupported_program"
            success = False
    except Exception as exc:  # noqa: BLE001
        logger.exception("approved_recovery_failed error_type=%s", type(exc).__name__)
        error = type(exc).__name__
        success = False

    complete_recovery(
        incident_id,
        lease_token=lease,
        success=success,
        recovery_run_id=recovery_run_id,
    )
    updated = load_incident(incident_id) or {}
    updated["recovery_outcomes"] = {
        "생성 결과": "성공" if success else f"실패({error or 'unknown'})",
        "validation": validation_result or "확인불가",
        "artifact": artifact_status or ("생성됨" if recovery_run_id else "없음"),
        "owner_review_smtp": "smtp_accepted" if email_sent else "미발송 또는 실패",
        "고객 발송": "수행하지 않음",
    }
    save_incident(updated)

    send_ok, subject = send_recovery_report(updated, success=success, send_fn=send_fn)
    if send_ok:
        mark_recovery_report_sent(incident_id)

    return {
        "ok": success,
        "incident_id": incident_id,
        "recovery_run_id": recovery_run_id,
        "email_sent": email_sent,
        "customer_send": 0,
        "auto_retry": 0,
        "recovery_report_sent": send_ok,
        "recovery_report_subject": subject,
        "status": STATUS_RECOVERY_SUCCEEDED if success else STATUS_RECOVERY_FAILED,
        "error": error or None,
    }
