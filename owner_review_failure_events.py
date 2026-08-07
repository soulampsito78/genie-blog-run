"""Structured owner-review failure events for Cloud Logging / alert design.

Emits at most one ERROR event per (program_id, run_id) for scheduled service
full runs. Never logs secrets, raw model output, or email addresses.

The event is written through a dedicated logger whose formatter is exactly
``%(message)s`` so the emitted line is a bare single-line JSON object. The
application-wide formatter (``main.configure_application_logging``) prefixes
records with an asctime/level/name header, which would stop Cloud Logging from
parsing the line into ``jsonPayload``; this logger deliberately does not
propagate into it.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from typing import Any, Dict, List, Mapping, Optional, Sequence  # Mapping used by extra_fields

from genie_schedule_policy import is_scheduled_trigger_source

# Diagnostic logger for emitter problems — never used for the event itself.
logger = logging.getLogger("keysuri_service_full_run")

OWNER_REVIEW_RUN_FAILED_EVENT = "owner_review_run_failed"
SCHEDULED_SERVICE_FULL_RUN_TRIGGER = "scheduled_service_full_run"
OWNER_REVIEW_FAILURE_EVENT_LOGGER = "genie.owner_review_failure_event"

_STRUCTURED_HANDLER_MARKER = "_genie_owner_review_failure_event_handler"

_EMITTED_LOCK = threading.Lock()
_EMITTED_EVENT_KEYS: set[str] = set()
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


def configure_owner_review_failure_event_logger() -> logging.Logger:
    """Return the event logger, wired to emit one bare JSON line per record.

    Idempotent: the handler is tagged so repeated calls (or a module reload)
    never stack duplicate handlers. ``propagate`` stays False so the prefixed
    application formatter can never wrap the JSON line.
    """
    event_logger = logging.getLogger(OWNER_REVIEW_FAILURE_EVENT_LOGGER)
    if not any(
        getattr(handler, _STRUCTURED_HANDLER_MARKER, False)
        for handler in event_logger.handlers
    ):
        handler = logging.StreamHandler()
        handler.setLevel(logging.ERROR)
        handler.setFormatter(logging.Formatter("%(message)s"))
        setattr(handler, _STRUCTURED_HANDLER_MARKER, True)
        event_logger.addHandler(handler)
    event_logger.setLevel(logging.ERROR)
    event_logger.propagate = False
    return event_logger


event_logger = configure_owner_review_failure_event_logger()


def reset_owner_review_failure_event_dedupe_for_tests() -> None:
    """Test-only helper to clear the in-process dedupe set."""
    with _EMITTED_LOCK:
        _EMITTED_EVENT_KEYS.clear()


def _dedupe_key(program_id: Any, run_id: Any) -> str:
    """One event per program+run: run ids are program-scoped by convention."""
    return f"{str(program_id or '').strip()}|{str(run_id or '').strip()}"


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
    hold_reason: Optional[str] = None,
) -> str:
    code = str(error_code or "").strip().lower()
    # Order matters: render/watermark codes also contain "email"/"image" tokens.
    if "render" in code:
        return "email_rendering"
    if "image" in code or "watermark" in code:
        return "image_generation"
    if "smtp" in code or "email" in code:
        return "email_delivery"
    if "artifact" in code or "storage" in code:
        return "artifact_persistence"
    if "exception" in code:
        return "service_exception"
    # A source-shortage hold reaches the finalizer as validation_result="block",
    # so hold_reason is the only signal that separates it from a model-contract
    # failure. Operators triage the two differently.
    if str(hold_reason or "").strip() or str(validation_result or "").strip().lower() == "hold":
        return "validation_hold"
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
    """Gate on the repo's canonical scheduled-trigger policy.

    ``genie_schedule_policy.is_scheduled_trigger_source`` is the single source of
    truth for what counts as a scheduled run; this module must not keep its own
    parallel allow-list.
    """
    if dry_run:
        return False
    return is_scheduled_trigger_source(trigger_source)


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
    artifact_saved: bool = True,
    extra_fields: Optional[Mapping[str, Any]] = None,
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
        # A failed artifact save is a secondary fault: keep the primary stage
        # and surface the storage problem as its own flag with no stale URL.
        "artifact_saved": bool(artifact_saved),
        "artifact_url": str(artifact_url or "") if artifact_saved else "",
    }
    if extra_fields:
        for key, value in extra_fields.items():
            key_text = str(key or "").strip()
            if not key_text or key_text in _BANNED_PAYLOAD_KEYS or key_text in payload:
                continue
            if key_text.lower() in _BANNED_PAYLOAD_KEYS:
                continue
            if value is None:
                continue
            if isinstance(value, (str, int, float, bool)):
                payload[key_text] = value
            elif isinstance(value, list):
                payload[key_text] = _sanitize_issue_codes(value)
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
    hold_reason: Optional[str] = None,
    dry_run: bool = False,
    revision: Optional[str] = None,
    artifact_saved: bool = True,
    extra_fields: Optional[Mapping[str, Any]] = None,
    force_emit: bool = False,
) -> bool:
    """Emit one structured ERROR event for a scheduled final failure.

    Returns True when an event was emitted in this process for this
    ``(program_id, run_id)`` pair.

    ``force_emit=True`` bypasses the scheduled-trigger allow-list for gate
    failures that must remain observable even when identity fields are missing.
    """
    if dry_run:
        return False
    if not force_emit and not should_emit_owner_review_failure_event(
        trigger_source=trigger_source, dry_run=False
    ):
        return False
    rid = str(run_id or "").strip()
    if not rid:
        return False
    key = _dedupe_key(program_id, rid)
    with _EMITTED_LOCK:
        if key in _EMITTED_EVENT_KEYS:
            return False
        if len(_EMITTED_EVENT_KEYS) >= _EMITTED_MAX:
            _EMITTED_EVENT_KEYS.clear()
        _EMITTED_EVENT_KEYS.add(key)

    stage = first_failed_stage or infer_first_failed_stage(
        error_code=error_code,
        validation_result=validation_result,
        hold_reason=hold_reason,
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
        artifact_saved=artifact_saved,
        extra_fields=extra_fields,
    )
    # One bare JSON object per line, on a logger whose formatter adds nothing,
    # so Cloud Logging can parse the entry into jsonPayload.
    event_logger.error(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    # Korean operator report (diagnose → report → wait). Never auto-retries.
    try:
        from natural_run_watchdog import notify_natural_run_incident_from_failure

        notify_natural_run_incident_from_failure(
            program_id=str(program_id or ""),
            run_id=rid,
            trigger_source=str(trigger_source or ""),
            first_failed_stage=stage,
            error_code=str(error_code or "unknown"),
            issue_codes=list(issue_codes or []),
            email_sent=bool(email_sent),
            artifact_saved=bool(artifact_saved),
            extra_fields=extra_fields,
            dry_run=False,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "owner_review_failure_report_hook_failed error_type=%s",
            type(exc).__name__,
        )
    return True


def emit_owner_review_failure_from_artifact_meta(
    meta: Mapping[str, Any],
    *,
    dry_run: bool = False,
    first_failed_stage: Optional[str] = None,
    error_code: Optional[str] = None,
    artifact_saved: bool = True,
) -> bool:
    """Convenience wrapper for service-full-run failure finalizers."""
    if not isinstance(meta, Mapping):
        return False
    return emit_owner_review_run_failed_once(
        program_id=str(meta.get("program_id") or meta.get("mode") or ""),
        run_id=str(meta.get("run_id") or ""),
        trigger_source=str(meta.get("trigger_source") or ""),
        first_failed_stage=first_failed_stage or meta.get("first_failed_stage") or None,
        error_code=str(error_code or meta.get("error_code") or "unknown"),
        issue_codes=list(meta.get("issue_codes") or []),
        email_sent=bool(meta.get("email_sent")),
        artifact_url=str(
            meta.get("artifact_url")
            or meta.get("owner_review_url")
            or meta.get("artifact_gcs_uri")
            or ""
        ),
        validation_result=str(meta.get("validation_result") or ""),
        hold_reason=str(meta.get("hold_reason") or ""),
        dry_run=dry_run,
        artifact_saved=artifact_saved,
    )
