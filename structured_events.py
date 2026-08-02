"""Credential-safe business event emitter shared by jobs and watchdogs."""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo

BUSINESS_EVENT_LOGGER = "genie.business_events"
_HANDLER_MARKER = "_genie_business_event_handler"


def configure_business_event_logger() -> logging.Logger:
    """Emit bare JSON lines so Cloud Logging creates ``jsonPayload`` fields."""
    event_logger = logging.getLogger(BUSINESS_EVENT_LOGGER)
    if not any(getattr(handler, _HANDLER_MARKER, False) for handler in event_logger.handlers):
        handler = logging.StreamHandler()
        handler.setLevel(logging.INFO)
        handler.setFormatter(logging.Formatter("%(message)s"))
        setattr(handler, _HANDLER_MARKER, True)
        event_logger.addHandler(handler)
    event_logger.setLevel(logging.INFO)
    event_logger.propagate = False
    return event_logger


LOGGER = configure_business_event_logger()
ALLOWED_EVENTS = frozenset(
    {
        "scheduled_run_started",
        "scheduled_run_duplicate_skipped",
        "scheduled_run_retry_started",
        "scheduled_run_stage_failed",
        "owner_review_run_failed",
        "business_success_deadline_missed",
        "owner_review_business_success",
        "customer_delivery_business_success",
        "exposure_log_update_failed",
        "idempotency_conflict",
        "stale_feed_fallback_blocked",
        "internal_auth_token_fallback",
    }
)


def now_kst_iso() -> str:
    return datetime.now(ZoneInfo("Asia/Seoul")).isoformat()


def emit_business_event(
    event: str,
    *,
    program_id: str,
    run_id: str = "",
    logical_execution_key: str = "",
    stage: str = "",
    status: str = "",
    retryable: bool = False,
    attempt: int = 1,
    scheduled_at_kst: str = "",
    deadline_at_kst: str = "",
    observed_at_kst: Optional[str] = None,
    error_code: str = "",
    summary: str = "",
) -> Dict[str, Any]:
    if event not in ALLOWED_EVENTS:
        raise ValueError("unsupported_business_event")
    safe_summary = " ".join(str(summary or "").split())[:240]
    payload = {
        "event": event,
        "program_id": str(program_id or ""),
        "run_id": str(run_id or ""),
        "logical_execution_key": str(logical_execution_key or ""),
        "stage": str(stage or ""),
        "status": str(status or ""),
        "retryable": bool(retryable),
        "attempt": max(1, int(attempt or 1)),
        "scheduled_at_kst": str(scheduled_at_kst or ""),
        "deadline_at_kst": str(deadline_at_kst or ""),
        "observed_at_kst": observed_at_kst or now_kst_iso(),
        "error_code": str(error_code or ""),
        "summary": safe_summary,
    }
    LOGGER.info(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return payload
