"""Fenced logical-execution state for owner-review delivery.

The application records SMTP acceptance immediately after the sender returns
successfully.  A later retry may repair the normal checkpoint, but it may not
invoke the sender again once that durable marker exists.  This is not a
transactional outbox: SMTP acceptance can still occur before the marker write.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, Optional
from zoneinfo import ZoneInfo

from artifact_atomic import atomic_update_json

PIPELINE_CONTRACT_VERSION = "v1"
MIN_EXECUTION_LEASE_SECONDS = 120
MAX_EXECUTION_LEASE_SECONDS = 900
PROGRAM_MAX_ATTEMPTS = {
    "today_genie": 1,
    "keysuri_global_tech": 3,
    "keysuri_korea_tech": 3,
}
SCHEDULED_SLOTS = {
    "today_genie": "06:30",
    "keysuri_global_tech": "12:30",
    "keysuri_korea_tech": "18:30",
}
TERMINAL_STATES = frozenset(
    {"owner_review_emailed", "customer_accepted", "complete", "failed_terminal"}
)
LEASED_ACTIVE_STATES = frozenset(
    {"reserved", "running", "content_ready", "validated", "artifacts_ready", "failed_retryable"}
)
VALID_STATES = frozenset(LEASED_ACTIVE_STATES | TERMINAL_STATES)
_LOCAL_CREATE_LOCK = threading.Lock()


def _now() -> datetime:
    return datetime.now(ZoneInfo("Asia/Seoul"))


def execution_lease_seconds() -> int:
    raw = os.getenv("GENIE_EXECUTION_LEASE_SECONDS", "330").strip()
    try:
        configured = int(raw)
    except ValueError as exc:
        raise RuntimeError("execution_lease_seconds_invalid") from exc
    if not MIN_EXECUTION_LEASE_SECONDS <= configured <= MAX_EXECUTION_LEASE_SECONDS:
        raise RuntimeError("execution_lease_seconds_unsafe")
    return configured


def _new_owner_id() -> str:
    revision = str(os.getenv("K_REVISION", "local") or "local").strip()
    return f"{revision}:{os.getpid()}:{threading.get_ident()}:{uuid.uuid4().hex}"


def _parse_timestamp(value: Any) -> Optional[datetime]:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo("Asia/Seoul"))
    return parsed.astimezone(ZoneInfo("Asia/Seoul"))


def _lease_is_valid(record: Dict[str, Any], observed: datetime) -> bool:
    expires = _parse_timestamp(record.get("lease_expires_at"))
    return bool(expires and expires > observed)


def _renewed_lease(owner_id: str, observed: datetime, *, acquired: bool) -> Dict[str, str]:
    fields = {
        "lease_expires_at": (observed + timedelta(seconds=execution_lease_seconds())).isoformat(),
        "heartbeat_at": observed.isoformat(),
        "owner_id": owner_id,
    }
    if acquired:
        fields["lease_acquired_at"] = observed.isoformat()
    return fields


def build_logical_execution_key(
    *,
    program_id: str,
    scheduled_date_kst: str,
    scheduled_slot_kst: str,
    trigger_source: str,
    pipeline_contract_version: str = PIPELINE_CONTRACT_VERSION,
) -> str:
    values = (
        str(program_id or "").strip(),
        str(scheduled_date_kst or "").strip(),
        str(scheduled_slot_kst or "").strip(),
        str(trigger_source or "").strip(),
        str(pipeline_contract_version or "").strip(),
    )
    if not all(values):
        raise ValueError("logical_execution_key_fields_required")
    return ":".join(values)


def scheduled_execution_key(
    program_id: str,
    *,
    now: Optional[datetime] = None,
    trigger_source: str = "scheduled",
) -> str:
    current = (now or _now()).astimezone(ZoneInfo("Asia/Seoul"))
    slot = SCHEDULED_SLOTS.get(program_id)
    if not slot:
        raise ValueError("program_schedule_slot_unknown")
    return build_logical_execution_key(
        program_id=program_id,
        scheduled_date_kst=current.date().isoformat(),
        scheduled_slot_kst=slot,
        trigger_source=trigger_source,
    )


def manual_execution_key(program_id: str, run_id: str, *, trigger_source: str) -> str:
    """Give one explicit manual run a distinct execution identity."""
    current = _now()
    return build_logical_execution_key(
        program_id=program_id,
        scheduled_date_kst=current.date().isoformat(),
        scheduled_slot_kst=f"manual-{run_id}",
        trigger_source=trigger_source or "manual",
    )


def scheduled_at_for_key(logical_key: str) -> str:
    parts = logical_key.split(":")
    if len(parts) != 5:
        return ""
    try:
        dt = datetime.combine(date.fromisoformat(parts[1]), time.fromisoformat(parts[2]))
    except ValueError:
        return ""
    return dt.replace(tzinfo=ZoneInfo("Asia/Seoul")).isoformat()


def _key_token(logical_key: str) -> str:
    return hashlib.sha256(logical_key.encode("utf-8")).hexdigest()


def _local_root() -> Path:
    raw = os.getenv("GENIE_EXECUTION_STATE_ROOT", "").strip()
    if raw:
        root = Path(raw)
    else:
        from admin_store import admin_runs_dir

        root = admin_runs_dir() / "execution_reservations"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _local_path(logical_key: str) -> Path:
    return _local_root() / f"{_key_token(logical_key)}.json"


def _gcs_key(logical_key: str) -> str:
    from admin_store import admin_artifact_gcs_prefix

    return f"{admin_artifact_gcs_prefix()}/execution_reservations/{_key_token(logical_key)}.json"


def _uses_gcs() -> bool:
    from admin_store import admin_artifact_bucket_name

    return bool(admin_artifact_bucket_name()) and not os.getenv("GENIE_EXECUTION_STATE_ROOT", "").strip()


def load_execution(logical_key: str) -> Optional[Dict[str, Any]]:
    if _uses_gcs():
        from admin_store import _gcs_download_text

        raw = _gcs_download_text(_gcs_key(logical_key))
        if not raw:
            return None
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    path = _local_path(logical_key)
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else None


def _create_if_absent(logical_key: str, payload: Dict[str, Any]) -> bool:
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if _uses_gcs():
        from admin_store import _gcs_upload_text

        try:
            _gcs_upload_text(
                _gcs_key(logical_key),
                text,
                content_type="application/json",
                if_generation_match=0,
            )
            return True
        except Exception as exc:
            if type(exc).__name__ in {"PreconditionFailed", "Conflict"}:
                return False
            raise
    path = _local_path(logical_key)
    with _LOCAL_CREATE_LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            return False
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        return True


def _update(logical_key: str, mutator: Callable[[Dict[str, Any]], Any]) -> tuple[Dict[str, Any], Any]:
    if _uses_gcs():
        from admin_store import _gcs_atomic_update_json

        result_box: list[Any] = []

        def _wrapped(current: Dict[str, Any]) -> None:
            result_box[:] = [mutator(current)]

        current = _gcs_atomic_update_json(_gcs_key(logical_key), mutator=_wrapped)
        return current, result_box[0] if result_box else None
    return atomic_update_json(_local_path(logical_key), default={}, mutator=mutator)


def _require_owner(expected_owner_id: str) -> str:
    owner = str(expected_owner_id or "").strip()
    if not owner:
        raise RuntimeError("expected_owner_id_required")
    return owner


def update_execution(
    logical_key: str,
    *,
    expected_owner_id: str,
    release_lease: Optional[bool] = None,
    **fields: Any,
) -> Dict[str, Any]:
    owner = _require_owner(expected_owner_id)
    requested_state = fields.get("state")
    if requested_state is not None and requested_state not in VALID_STATES:
        raise ValueError("invalid_execution_state")
    observed_dt = _now()
    observed = observed_dt.isoformat()

    def _mut(current: Dict[str, Any]) -> None:
        if not current:
            raise RuntimeError("execution_reservation_missing")
        if str(current.get("owner_id") or "") != owner:
            raise RuntimeError("execution_lease_owner_mismatch")
        current.update(fields)
        state = str(current.get("state") or "")
        should_release = (
            release_lease is True
            or state in TERMINAL_STATES
            or (state == "failed_retryable" and release_lease is not False)
        )
        if should_release:
            current["heartbeat_at"] = observed
            current["lease_expires_at"] = observed
        else:
            # Meaningful stage transitions are the heartbeat policy.  There is
            # deliberately no standalone public heartbeat API.
            current.update(_renewed_lease(owner, observed_dt, acquired=False))
        current["updated_at"] = observed
        current["schema_version"] = "execution_reservation_v1"

    current, _ = _update(logical_key, _mut)
    return current


def owner_review_accepted(record: Optional[Dict[str, Any]]) -> bool:
    return bool(record and record.get("owner_review_accepted_at"))


@dataclass(frozen=True)
class OwnerReviewDeliveryResult:
    accepted: bool
    sender_called: bool
    duplicate_suppressed: bool


def deliver_owner_review_once(
    logical_key: str,
    *,
    expected_owner_id: str,
    send: Callable[[], bool],
) -> OwnerReviewDeliveryResult:
    """Fence a sender call and durably mark acceptance before returning.

    A crash after provider acceptance but before the marker is the documented
    residual gap; no application-only primitive can close that gap.
    """
    owner = _require_owner(expected_owner_id)
    observed_dt = _now()

    def _begin(current: Dict[str, Any]) -> str:
        if not current:
            raise RuntimeError("execution_reservation_missing")
        if str(current.get("owner_id") or "") != owner:
            raise RuntimeError("execution_lease_owner_mismatch")
        if owner_review_accepted(current):
            return "accepted"
        if str(current.get("state") or "") in TERMINAL_STATES:
            return "terminal"
        current["owner_review_send_started_at"] = observed_dt.isoformat()
        current.update(_renewed_lease(owner, observed_dt, acquired=False))
        current["updated_at"] = observed_dt.isoformat()
        return "send"

    _current, decision = _update(logical_key, _begin)
    if decision == "accepted":
        return OwnerReviewDeliveryResult(True, False, True)
    if decision == "terminal":
        return OwnerReviewDeliveryResult(False, False, True)
    accepted = bool(send())
    if not accepted:
        return OwnerReviewDeliveryResult(False, True, False)

    accepted_at = _now().isoformat()

    def _accept(current: Dict[str, Any]) -> None:
        if not current:
            raise RuntimeError("execution_reservation_missing")
        if str(current.get("owner_id") or "") != owner:
            raise RuntimeError("execution_lease_owner_mismatch")
        current["owner_review_delivery_status"] = "smtp_accepted"
        current["owner_review_accepted_at"] = accepted_at
        current["owner_review_accepted_by"] = owner
        current["updated_at"] = accepted_at
        current.update(_renewed_lease(owner, _now(), acquired=False))

    _update(logical_key, _accept)
    return OwnerReviewDeliveryResult(True, True, False)


class _RetryClaimUnavailable(RuntimeError):
    pass


def _max_attempts(program_id: str) -> int:
    return PROGRAM_MAX_ATTEMPTS.get(program_id, 1)


def _claim_retry_or_stale_lease(logical_key: str, *, owner_id: str) -> Dict[str, Any]:
    observed_dt = _now()
    observed = observed_dt.isoformat()

    def _mut(current: Dict[str, Any]) -> None:
        state = str(current.get("state") or "")
        attempt = max(1, int(current.get("attempt") or 1))
        accepted_repair = owner_review_accepted(current) and state not in TERMINAL_STATES
        if state not in LEASED_ACTIVE_STATES or _lease_is_valid(current, observed_dt):
            raise _RetryClaimUnavailable("retry_claim_unavailable")
        program_id = str(current.get("program_id") or "")
        if not accepted_repair and attempt >= _max_attempts(program_id):
            current.update(
                {
                    "state": "failed_terminal",
                    "terminal_status": "failed_terminal",
                    "error_code": "execution_attempt_limit_exceeded",
                    "heartbeat_at": observed,
                    "lease_expires_at": observed,
                    "updated_at": observed,
                }
            )
            return
        previous_state = state
        last_safe_state = str(current.get("last_safe_state") or "")
        if previous_state in {"content_ready", "validated", "artifacts_ready"}:
            last_safe_state = previous_state
        current.update(
            {
                "state": "running",
                "attempt": attempt if accepted_repair else attempt + 1,
                "retry_count": max(0, attempt - 1) if accepted_repair else attempt,
                "last_retry_started_at": observed,
                "reclaimed_from_state": previous_state,
                "last_safe_state": last_safe_state or "running",
                "updated_at": observed,
            }
        )
        current.update(_renewed_lease(owner_id, observed_dt, acquired=True))

    current, _ = _update(logical_key, _mut)
    return current


@dataclass(frozen=True)
class ReservationDecision:
    execute: bool
    resume: bool
    skipped_duplicate: bool
    logical_execution_key: str
    run_id: str
    attempt: int
    previous_state: str
    owner_id: str
    accepted_repair: bool = False


def reserve_execution(
    logical_key: str,
    *,
    program_id: str,
    run_id: str,
    owner_id: Optional[str] = None,
) -> ReservationDecision:
    observed = _now()
    now_iso = observed.isoformat()
    claimant = str(owner_id or _new_owner_id())
    initial = {
        "schema_version": "execution_reservation_v1",
        "logical_execution_key": logical_key,
        "program_id": program_id,
        "run_id": run_id,
        "state": "running",
        "attempt": 1,
        "retry_count": 0,
        "scheduled_at_kst": scheduled_at_for_key(logical_key),
        "created_at": now_iso,
        "updated_at": now_iso,
    }
    initial.update(_renewed_lease(claimant, observed, acquired=True))
    if _create_if_absent(logical_key, initial):
        return ReservationDecision(True, False, False, logical_key, run_id, 1, "reserved", claimant)

    existing = load_execution(logical_key) or {}
    state = str(existing.get("state") or "")
    existing_run_id = str(existing.get("run_id") or run_id)
    attempt = max(1, int(existing.get("attempt") or 1))
    if state in LEASED_ACTIVE_STATES and not _lease_is_valid(existing, observed):
        try:
            updated = _claim_retry_or_stale_lease(logical_key, owner_id=claimant)
        except _RetryClaimUnavailable:
            latest = load_execution(logical_key) or existing
            return ReservationDecision(
                False, False, True, logical_key,
                str(latest.get("run_id") or existing_run_id),
                max(1, int(latest.get("attempt") or attempt)),
                str(latest.get("state") or state),
                str(latest.get("owner_id") or ""),
            )
        if str(updated.get("state") or "") == "failed_terminal":
            return ReservationDecision(
                False, False, True, logical_key,
                str(updated.get("run_id") or existing_run_id),
                max(1, int(updated.get("attempt") or attempt)),
                state,
                str(updated.get("owner_id") or ""),
            )
        accepted_repair = owner_review_accepted(updated)
        return ReservationDecision(
            True, True, False, logical_key,
            str(updated.get("run_id") or existing_run_id),
            max(1, int(updated.get("attempt") or attempt)),
            str(updated.get("reclaimed_from_state") or state),
            claimant,
            accepted_repair,
        )
    return ReservationDecision(
        False, False, True, logical_key, existing_run_id, attempt, state,
        str(existing.get("owner_id") or ""),
    )


def reserve_manual_execution(
    *,
    program_id: str,
    run_id: str,
    trigger_source: str,
) -> ReservationDecision:
    return reserve_execution(
        manual_execution_key(program_id, run_id, trigger_source=trigger_source),
        program_id=program_id,
        run_id=run_id,
    )
