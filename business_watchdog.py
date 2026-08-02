"""Read-only, metadata-only evaluator for scheduled business success."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional
from zoneinfo import ZoneInfo

from execution_state import SCHEDULED_SLOTS, build_logical_execution_key
from run_metadata_index import claim_watchdog_event, list_recent_metadata
from structured_events import emit_business_event

KST = ZoneInfo("Asia/Seoul")
# Business deadlines are explicit monitoring-policy thresholds. Each individual
# Scheduler and Cloud Run request remains bounded independently.
PROGRAM_DEADLINE_MINUTES = {
    "today_genie": 20,
    "keysuri_global_tech": 30,
    "keysuri_korea_tech": 35,
}
RETRY_GRACE_MINUTES = 10


def owner_review_business_success(row: Dict[str, Any]) -> bool:
    program_id = str(row.get("program_id") or "")
    required = 3 if program_id == "today_genie" else 5
    selected = int(row.get("selected_count") or 0)
    shortfall = int(row.get("shortfall_count") or 0)
    validation_ok = str(row.get("validation_result") or "") == "pass"
    artifacts_ok = str(row.get("artifact_manifest_state") or "") == "complete"
    owner_ok = bool(row.get("owner_review_accepted"))
    images_ok = True if program_id == "today_genie" else bool(row.get("required_images_complete"))
    return all((selected == required, shortfall == 0, validation_ok, artifacts_ok, owner_ok, images_ok))


def _expected_slot(program_id: str, observed: datetime) -> tuple[str, datetime]:
    slot = SCHEDULED_SLOTS[program_id]
    hour, minute = (int(part) for part in slot.split(":"))
    scheduled = observed.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if observed < scheduled:
        scheduled -= timedelta(days=1)
    logical_key = build_logical_execution_key(
        program_id=program_id,
        scheduled_date_kst=scheduled.date().isoformat(),
        scheduled_slot_kst=slot,
        trigger_source="scheduled",
    )
    return logical_key, scheduled


def evaluate_business_success_deadlines(
    *,
    now: Optional[datetime] = None,
    metadata_rows: Optional[Iterable[Dict[str, Any]]] = None,
    claim_fn=claim_watchdog_event,
) -> Dict[str, Any]:
    observed = (now or datetime.now(KST)).astimezone(KST)
    rows = list(metadata_rows) if metadata_rows is not None else list_recent_metadata(limit=100)
    by_key = {str(row.get("logical_execution_key") or ""): row for row in rows}
    failures: List[Dict[str, Any]] = []
    checked = 0
    for program_id in PROGRAM_DEADLINE_MINUTES:
        logical_key, scheduled = _expected_slot(program_id, observed)
        if scheduled.weekday() >= 5:
            continue
        deadline = scheduled + timedelta(minutes=PROGRAM_DEADLINE_MINUTES[program_id])
        if observed <= deadline:
            continue
        checked += 1
        row = by_key.get(logical_key)
        if row and owner_review_business_success(row):
            continue
        state = (
            str(row.get("terminal_status") or row.get("current_stage") or "")
            if row is not None
            else "missing"
        )
        if state in {"failed_terminal", "failed"}:
            continue
        if state in {"running", "failed_retryable"} and observed <= deadline + timedelta(minutes=RETRY_GRACE_MINUTES):
            continue
        if not claim_fn(logical_key):
            continue
        payload = emit_business_event(
            "business_success_deadline_missed",
            program_id=program_id,
            run_id=str((row or {}).get("run_id") or ""),
            logical_execution_key=logical_key,
            stage=str((row or {}).get("current_stage") or "scheduled_slot"),
            status=state,
            retryable=state in {"running", "failed_retryable", "missing"},
            attempt=int((row or {}).get("retry_count") or 0) + 1,
            scheduled_at_kst=scheduled.isoformat(),
            deadline_at_kst=deadline.isoformat(),
            observed_at_kst=observed.isoformat(),
            error_code="business_success_deadline_missed",
            summary="Required owner-review business milestone was not recorded before its deadline.",
        )
        failures.append(payload)
    return {
        "ok": not failures,
        "metadata_only": True,
        "artifact_html_reads": "UNMEASURED",
        "checked_slots": checked,
        "failure_event_count": len(failures),
        "events": failures,
        "observed_at_kst": observed.isoformat(),
    }
