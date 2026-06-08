"""Internal job endpoints for scheduler/automation dispatch."""
from __future__ import annotations

import hmac
import logging
import os
from typing import Any, Callable, Dict, Optional

from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from keysuri_live_source_smoke import (
    PROGRAM_GLOBAL,
    PROGRAM_KOREA,
    LiveSourceSmokeResult,
    run_keysuri_live_source_smoke,
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


class KeysuriOwnerReviewJobRequest(BaseModel):
    program_id: Optional[str] = Field(default=None)
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
    smoke_runner: Optional[Callable[..., LiveSourceSmokeResult]] = None,
) -> Dict[str, Any]:
    """
    Dispatch Kee-Suri scheduled owner-review generation.

    dry_run=True performs validation only — no Gemini, HTML, or email.
    """
    normalized, err = validate_keysuri_owner_review_program_id(program_id)
    if err:
        raise ValueError(str(err.get("error")))

    trigger = (trigger_source or DEFAULT_TRIGGER_SOURCE).strip() or DEFAULT_TRIGGER_SOURCE

    if dry_run:
        return {
            "ok": True,
            "program_id": normalized,
            "dry_run": True,
            "trigger_source": trigger,
            "would_run": True,
        }

    runner = smoke_runner or run_keysuri_live_source_smoke
    result = runner(
        program_id=normalized,
        use_gemini=True,
        contract_preview=True,
        send=False,
    )
    return _smoke_result_to_job_payload(
        result,
        program_id=normalized,
        trigger_source=trigger,
    )


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

    return JSONResponse(status_code=200, content=payload)


def process_approval_timeouts(*, now: Any = None, limit: int = 500) -> Dict[str, Any]:
    """
    Compatibility no-op: timeout-based customer auto-send was removed from active policy.
    Historical artifacts with sent_after_timeout remain display-only.
    """
    _ = now
    _ = limit
    return {
        "ok": True,
        "retired": True,
        "sent": 0,
        "eligible": 0,
        "skipped": 0,
        "errors": 0,
        "run_ids_sent": [],
        "skip_reasons": {},
        "error_run_ids": [],
        "note": "timeout customer send retired",
    }
