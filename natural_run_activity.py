"""Bounded, process-local awareness of natural executions in progress.

This module is deliberately *advisory*.  It neither admits nor rejects a run,
does not persist completion state, and is not an execution lease.  The existing
natural-slot identity/gate remains the only authority.  The marker only lets
secondary work on the same Cloud Run instance (watchdog/Admin projections)
defer while an admitted natural execution is using the process.
"""
from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Any, Dict, Iterator

from today_genie_execution_identity import (
    EXECUTION_CLASS_NATURAL_SCHEDULED,
    natural_slot_key,
)


MAX_ACTIVE_NATURAL_IDENTITIES = 8

_LOCK = threading.RLock()
_ACTIVE_BY_SLOT_KEY: Dict[str, Dict[str, Any]] = {}


def _bounded_text(value: Any, *, max_len: int = 80) -> str:
    return str(value or "").strip()[:max_len]


def _activity_key(
    *,
    program_id: str,
    kst_date: str,
    scheduled_slot: str,
    execution_class: str,
) -> str:
    # These fields have already passed the endpoint's execution-identity gate.
    # Feed the exact values to the canonical key builder; do not create a
    # truncated or alternate identity namespace here.
    return natural_slot_key(
        program_id=str(program_id or "").strip(),
        kst_date=str(kst_date or "").strip(),
        scheduled_slot=str(scheduled_slot or "").strip(),
        execution_class=str(execution_class or "").strip(),
    )


def begin_natural_run_activity(
    *,
    program_id: str,
    kst_date: str,
    scheduled_slot: str,
    execution_class: str,
) -> str:
    """Register one admitted natural execution and return its advisory key.

    Non-natural execution classes are intentionally ignored.  Capacity is
    bounded; if an unexpected number of distinct identities is already active,
    the new marker is omitted rather than changing execution behavior.
    """
    if _bounded_text(execution_class) != EXECUTION_CLASS_NATURAL_SCHEDULED:
        return ""
    key = _activity_key(
        program_id=program_id,
        kst_date=kst_date,
        scheduled_slot=scheduled_slot,
        execution_class=execution_class,
    )
    with _LOCK:
        current = _ACTIVE_BY_SLOT_KEY.get(key)
        if current is not None:
            current["count"] = min(int(current.get("count") or 0) + 1, 1_000_000)
            return key
        if len(_ACTIVE_BY_SLOT_KEY) >= MAX_ACTIVE_NATURAL_IDENTITIES:
            return ""
        _ACTIVE_BY_SLOT_KEY[key] = {
            "program_id": _bounded_text(program_id),
            "kst_date": _bounded_text(kst_date),
            "scheduled_slot": _bounded_text(scheduled_slot),
            "execution_class": EXECUTION_CLASS_NATURAL_SCHEDULED,
            "count": 1,
        }
    return key


def end_natural_run_activity(activity_key: str) -> None:
    """Release one advisory marker.  Unknown/empty keys are harmless."""
    key = str(activity_key or "").strip()
    if not key:
        return
    with _LOCK:
        current = _ACTIVE_BY_SLOT_KEY.get(key)
        if current is None:
            return
        remaining = int(current.get("count") or 1) - 1
        if remaining <= 0:
            _ACTIVE_BY_SLOT_KEY.pop(key, None)
        else:
            current["count"] = remaining


@contextmanager
def track_natural_run_activity(
    *,
    program_id: str,
    kst_date: str,
    scheduled_slot: str,
    execution_class: str,
) -> Iterator[str]:
    """Context-manage the advisory marker without affecting run outcome."""
    key = begin_natural_run_activity(
        program_id=program_id,
        kst_date=kst_date,
        scheduled_slot=scheduled_slot,
        execution_class=execution_class,
    )
    try:
        yield key
    finally:
        end_natural_run_activity(key)


def active_natural_run_snapshot() -> Dict[str, Any]:
    """Return bounded metadata only; never payloads, HTML, images, or secrets."""
    with _LOCK:
        rows = [dict(row) for _, row in sorted(_ACTIVE_BY_SLOT_KEY.items())]
    return {
        "active": bool(rows),
        "active_identity_count": len(rows),
        "active_request_count": sum(int(row.get("count") or 0) for row in rows),
        "program_ids": [str(row.get("program_id") or "") for row in rows],
        "scheduled_slots": [str(row.get("scheduled_slot") or "") for row in rows],
    }


def natural_run_is_active() -> bool:
    with _LOCK:
        return bool(_ACTIVE_BY_SLOT_KEY)
