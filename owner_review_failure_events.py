"""Structured owner-review failure events for Cloud Logging / alert design.

Emits at most one ERROR event per run_id for scheduled service full runs.
Never logs secrets, raw model output, or email addresses.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from typing import Any, Dict, List, Mapping, Optional, Sequence

logger = logging.getLogger("keysuri_service_full_run")

OWNER_REVIEW_RUN_FAILED_EVENT = "owner_review_run_failed"
SCHEDULED_SERVICE_FULL_RUN_TRIGGER = "scheduled_service_full_run"

_EMITTED_LOCK = threading.Lock()
_EMITTED_RUN_IDS: set[str] = set()
_EMITTED_MAX = 4096

_BANNED_PAYLOAD_KEYS = frozenset(
    {
        "raw_response",
        "raw_text",
        "prompt",
        "compact_prompt",
        "response",
        "smtp_password",
        "password",
        "secret",
        "api_key",
        "authorization",
        "email_recipients",
        "recipients",
        "to",
        "owner_email",
        "customer_email",
    }
)


def reset_owner_review_failure_event_dedupe_for_tests() -> None:
    """Test-only helper to clear the in-process dedupe set."""
    with _EMITTED_LOCK:
        _EMITTED_RUN_IDS.clear()


def _sanitize_issue_codes(issue_codes: Optional[Sequence[Any]]) -> List[str]:
    cleaned: List[str] = []
    for code in issue_codes or []:
        text = str(code or "").strip()
        if not text:
            continue
        # Keep issue codes short; drop free-form error strings that may include
        # model excerpts.
        if len(text) > 120:
            continue
        if any(banned in text.lower() for banned in ("secret", "password", "api_key")):
            continue
        if text not in cleaned:
            cleaned.append(text)
    return cleaned[:40]


def _revision_label() -> str:
    return (
        os.getenv("K_REVISION", "").strip()
        or os.getenv("CLOUD_RUN_REVISION", "").strip()
        or os.getenv("GENIE_REVISION", "").strip()
        or ""
    )


def infer_first_failed_stage(
    *,
    error_code: Optional[str],
    validation_result: Optional[str] = None,
) -> str:
    code = str(error_code or "").strip().lower()
    if "image" in code:
        return "image_generation"
    if "smtp" in code or "email" in code:
        return "email_delivery"
    if "artifact" in code or "storage" in code:
        return "artifact_persistence"
    if code in {"validation_blocked", "gemini_or_smoke_failed"} or (
        validation_result and str(validation_result).lower() != "pass"
    ):
        return "generation_validation"
    if code:
        return "service_full_run"
    return "unknown"


def should_emit_owner_review_failure_event(
    *,
    trigger_source: Optional[str],
    dry_run: bool = False,
) -> bool:
    if dry_run:
        return False
    return str(trigger_source or "").strip() == SCHEDULED_SERVICE_FULL_RUN_TRIGGER


def build_owner_review_run_failed_payload(
    *,
    program_id: str,
    run_id: str,
    trigger_source: str,
    first_failed_stage: str,
    error_code: str,
    issue_codes: Optional[Sequence[Any]] = None,
    email_sent: bool = False,
    artifact_url: Optional[str] = None,
    revision: Optional[str] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "event": OWNER_REVIEW_RUN_FAILED_EVENT,
        "severity": "ERROR",
        "program_id": str(program_id or ""),
        "run_id": str(run_id or ""),
        "trigger_source": str(trigger_source or ""),
        "first_failed_stage": str(first_failed_stage or "unknown"),
        "error_code": str(error_code or "unknown"),
        "issue_codes": _sanitize_issue_codes(issue_codes),
        "revision": str(revision if revision is not None else _revision_label()),
        "email_sent": bool(email_sent),
        "artifact_url": str(artifact_url or ""),
    }
    for banned in _BANNED_PAYLOAD_KEYS:
        payload.pop(banned, None)
    return payload


def emit_owner_review_run_failed_once(
    *,
    program_id: str,
    run_id: str,
    trigger_source: str,
    first_failed_stage: Optional[str] = None,
    error_code: Optional[str] = None,
    issue_codes: Optional[Sequence[Any]] = None,
    email_sent: bool = False,
    artifact_url: Optional[str] = None,
    validation_result: Optional[str] = None,
    dry_run: bool = False,
    revision: Optional[str] = None,
) -> bool:
    """Emit one structured ERROR event for a scheduled final failure.

    Returns True when an event was emitted in this process for ``run_id``.
    """
    if not should_emit_owner_review_failure_event(
        trigger_source=trigger_source, dry_run=dry_run
    ):
        return False
    rid = str(run_id or "").strip()
    if not rid:
        return False
    with _EMITTED_LOCK:
        if rid in _EMITTED_RUN_IDS:
            return False
        if len(_EMITTED_RUN_IDS) >= _EMITTED_MAX:
            _EMITTED_RUN_IDS.clear()
        _EMITTED_RUN_IDS.add(rid)

    stage = first_failed_stage or infer_first_failed_stage(
        error_code=error_code, validation_result=validation_result
    )
    payload = build_owner_review_run_failed_payload(
        program_id=program_id,
        run_id=rid,
        trigger_source=trigger_source,
        first_failed_stage=stage,
        error_code=str(error_code or "unknown"),
        issue_codes=issue_codes,
        email_sent=email_sent,
        artifact_url=artifact_url,
        revision=revision,
    )
    # Cloud Run's logging agent promotes single-line JSON messages into
    # jsonPayload when the message parses as an object.
    logger.error("%s", json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return True


def emit_owner_review_failure_from_artifact_meta(
    meta: Mapping[str, Any],
    *,
    dry_run: bool = False,
) -> bool:
    """Convenience wrapper for service-full-run failure finalizers."""
    if not isinstance(meta, Mapping):
        return False
    return emit_owner_review_run_failed_once(
        program_id=str(meta.get("program_id") or meta.get("mode") or ""),
        run_id=str(meta.get("run_id") or ""),
        trigger_source=str(meta.get("trigger_source") or ""),
        error_code=str(meta.get("error_code") or "unknown"),
        issue_codes=list(meta.get("issue_codes") or []),
        email_sent=bool(meta.get("email_sent")),
        artifact_url=str(
            meta.get("artifact_url")
            or meta.get("owner_review_url")
            or meta.get("artifact_gcs_uri")
            or ""
        ),
        validation_result=str(meta.get("validation_result") or ""),
        dry_run=dry_run,
    )
