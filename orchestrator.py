"""
Thin downstream orchestration worker: calls the Genie API, applies
publishing_policy.decide_publishing_actions, and returns a structured result.
Email and Naver draft delivery are wired.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from email_sender import send_genie_email
from naver_draft import create_naver_draft
from programs.registry import UnknownProgramError, get_program, resolve_program_id
from publishing_policy import PublishingDecision, decide_publishing_actions

logger = logging.getLogger(__name__)

_APPROVED_CONTROLLED_IMAGE_REVIEW_EMAILS = frozenset(
    {"soulampsito@gmail.com", "ey2133@naver.com"}
)

GENIE_API_URL = os.getenv("GENIE_API_URL", "http://localhost:8080")
GENIE_REQUEST_TIMEOUT = int(os.getenv("GENIE_REQUEST_TIMEOUT", "120"))
GENIE_API_RETRIES = int(os.getenv("GENIE_API_RETRIES", "2"))
GENIE_API_RETRY_DELAY_SEC = float(os.getenv("GENIE_API_RETRY_DELAY_SEC", "2.0"))


@dataclass
class OrchestrationResult:
    """Result of running the Genie job and applying publishing policy."""

    decision: PublishingDecision
    reason_summary: str
    response_status: Optional[int] = None
    mode: Optional[str] = None
    response_data: Optional[Dict[str, Any]] = None

    @property
    def send_email(self) -> bool:
        return self.decision.send_email

    @property
    def create_naver_draft(self) -> bool:
        return self.decision.create_naver_draft

    @property
    def auto_publish(self) -> bool:
        return self.decision.auto_publish

    @property
    def require_review(self) -> bool:
        return self.decision.require_review

    @property
    def suppress_external(self) -> bool:
        return self.decision.suppress_external


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _runtime_check_from_api_payload(
    payload: Dict[str, Any],
    *,
    reason_summary: str,
) -> Dict[str, Any]:
    detail = payload.get("detail") if isinstance(payload.get("detail"), dict) else {}
    root_runtime = payload.get("runtime_validation_check")
    detail_runtime = detail.get("runtime_validation_check")
    runtime = root_runtime if isinstance(root_runtime, dict) else detail_runtime if isinstance(detail_runtime, dict) else {}
    root_issues = payload.get("issues")
    detail_issues = detail.get("issues")
    issue_details = _as_list(root_issues) if isinstance(root_issues, list) else _as_list(detail_issues)
    issue_codes: list[str] = []
    if isinstance(payload.get("issue_codes"), list):
        issue_codes = [str(x) for x in payload.get("issue_codes")]
    elif isinstance(detail.get("issue_codes"), list):
        issue_codes = [str(x) for x in detail.get("issue_codes")]
    else:
        issue_codes = [
            str(item.get("code"))
            for item in issue_details
            if isinstance(item, dict) and item.get("code") is not None
        ]
    cqw = payload.get("content_quality_warnings")
    if not isinstance(cqw, list):
        cqw = detail.get("content_quality_warnings")
    return {
        "controlled_test_mode": os.getenv("GENIE_CONTROLLED_TEST_MODE", "").strip().lower()
        in ("1", "true", "yes"),
        "controlled_test_target_date": os.getenv("GENIE_CONTROLLED_TEST_TARGET_DATE", "").strip() or None,
        "target_date": runtime.get("target_date")
        or (payload.get("runtime_input", {}) if isinstance(payload.get("runtime_input"), dict) else {}).get("target_date")
        or (detail.get("runtime_input", {}) if isinstance(detail.get("runtime_input"), dict) else {}).get("target_date"),
        "validation_result": payload.get("validation_result")
        or detail.get("validation_result")
        or runtime.get("validation_result"),
        "workflow_status": payload.get("workflow_status")
        or detail.get("workflow_status")
        or runtime.get("workflow_status"),
        "reason_summary": reason_summary,
        "issue_codes": issue_codes,
        "issue_details": issue_details,
        "content_quality_warnings": _as_list(cqw),
    }


def run_genie_job(mode: str) -> OrchestrationResult:
    """
    Call the Genie API for the given mode, then apply publishing policy.
    Retries transient failures (timeout, connection error) up to GENIE_API_RETRIES.
    """
    import time
    import urllib.error
    import urllib.request

    url = GENIE_API_URL.rstrip("/") + "/"
    payload: Dict[str, Any] = {"type": mode}
    controlled_flag = os.getenv("GENIE_CONTROLLED_TEST_MODE", "").strip().lower()
    controlled_target = os.getenv("GENIE_CONTROLLED_TEST_TARGET_DATE", "").strip()
    if mode == "today_genie" and controlled_flag in ("1", "true", "yes") and controlled_target:
        payload["controlled_test_mode"] = True
        payload["controlled_test_target_date"] = controlled_target
        logger.info("controlled_test_mode active target_date=%s", controlled_target)
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )

    last_exc = None
    for attempt in range(GENIE_API_RETRIES + 1):
        try:
            with urllib.request.urlopen(req, timeout=GENIE_REQUEST_TIMEOUT) as resp:
                status = resp.getcode()
                raw = resp.read()
            break
        except urllib.error.HTTPError as e:
            status = e.code
            raw = e.read()
            break
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            last_exc = e
            if attempt < GENIE_API_RETRIES:
                time.sleep(GENIE_API_RETRY_DELAY_SEC)
                continue
            logger.warning("Genie API request failed after %d attempts: %s", attempt + 1, type(e).__name__)
            decision = decide_publishing_actions(mode, None, None, [], None)
            return OrchestrationResult(
                decision=decision,
                reason_summary="request_failed",
                response_status=None,
                mode=mode,
            )

    try:
        data = json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        decision = decide_publishing_actions(mode, None, None, [], None)
        return OrchestrationResult(
            decision=decision,
            reason_summary="invalid_response_body",
            response_status=status,
            mode=mode,
        )

    if status == 200:
        validation_result = data.get("validation_result")
        workflow_status = data.get("workflow_status")
        issues = data.get("issues") or []
        # Defensive: if API omits validation_result, infer from workflow_status (v2 contract)
        if validation_result not in ("pass", "draft_only"):
            validation_result = "draft_only" if workflow_status == "review_required" else "pass"
        ri = data.get("runtime_input")
        runtime_input = ri if isinstance(ri, dict) else None
        decision = decide_publishing_actions(
            mode, validation_result, workflow_status, issues, runtime_input
        )
        reason = "ok" if validation_result == "pass" else "review_required"
        runtime_check = _runtime_check_from_api_payload(data, reason_summary=reason)
        logger.info("today_genie runtime_check: %s", json.dumps(runtime_check, ensure_ascii=False))
        return OrchestrationResult(
            decision=decision,
            reason_summary=reason,
            response_status=200,
            mode=mode,
            response_data=data,
        )

    # 4xx/5xx with JSON body (e.g. validation_block)
    inner = data.get("detail", data) if isinstance(data, dict) else {}
    reason = inner.get("reason", "api_error") if isinstance(inner, dict) else "api_error"
    issues = inner.get("issues", []) if isinstance(inner, dict) else []
    decision = decide_publishing_actions(mode, None, None, issues, None)
    runtime_check = _runtime_check_from_api_payload(data if isinstance(data, dict) else {}, reason_summary=reason)
    logger.info("today_genie runtime_check: %s", json.dumps(runtime_check, ensure_ascii=False))
    return OrchestrationResult(
        decision=decision,
        reason_summary=reason,
        response_status=status,
        mode=mode,
        response_data=data if isinstance(data, dict) else None,
    )


def _controlled_test_send_env_active() -> bool:
    flag = os.getenv("GENIE_CONTROLLED_TEST_MODE", "").strip().lower()
    target = os.getenv("GENIE_CONTROLLED_TEST_TARGET_DATE", "").strip()
    return flag in ("1", "true", "yes") and bool(target)


def _controlled_recipients_ok() -> bool:
    raw = os.getenv("EMAIL_TO", "")
    parts = [p.strip().lower() for p in raw.split(",") if p.strip()]
    return bool(parts) and all(p in _APPROVED_CONTROLLED_IMAGE_REVIEW_EMAILS for p in parts)


def _admin_reissue_send_active() -> bool:
    return os.getenv("GENIE_ADMIN_REISSUE", "").strip().lower() in ("1", "true", "yes")


def _program_allows_naver_draft(mode: str) -> bool:
    try:
        spec = get_program(resolve_program_id(mode))
    except UnknownProgramError:
        return mode == "tomorrow_genie"
    return bool(spec.naver_assets_enabled)


def extract_email_html_for_artifact(result: OrchestrationResult) -> str:
    """Best-effort email HTML for admin artifact storage (same render path as send)."""
    if result.response_status != 200 or not isinstance(result.response_data, dict):
        return ""
    data = result.response_data.get("data") or {}
    if not isinstance(data, dict):
        return ""
    mode = str(result.mode or result.response_data.get("type") or "").strip()
    validation_result = str(result.response_data.get("validation_result") or "pass")
    if mode == "today_genie":
        try:
            from main import build_today_genie_email_html_for_cid_mime_send

            return build_today_genie_email_html_for_cid_mime_send(
                data,
                validation_result=validation_result,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("extract_email_html_for_artifact today_genie failed: %s", e)
            return ""
    channels = data.get("rendered_channels") or {}
    if isinstance(channels, dict):
        return str(channels.get("email_body_html") or "")
    return ""


def build_run_artifact_metadata(
    result: OrchestrationResult,
    *,
    run_id: str,
    email_sent: bool,
    parent_run_id: str | None = None,
    reissue_reason: str | None = None,
    trigger_source: str | None = None,
) -> Dict[str, Any]:
    payload = result.response_data if isinstance(result.response_data, dict) else {}
    runtime_check = _runtime_check_from_api_payload(payload, reason_summary=result.reason_summary)
    resolved_trigger = trigger_source
    if not resolved_trigger and parent_run_id:
        resolved_trigger = "reissue"
    meta: Dict[str, Any] = {
        "run_id": run_id,
        "mode": result.mode,
        "created_at": None,
        "response_status": result.response_status,
        "reason_summary": result.reason_summary,
        "validation_result": payload.get("validation_result") or runtime_check.get("validation_result"),
        "workflow_status": payload.get("workflow_status") or runtime_check.get("workflow_status"),
        "email_sent": bool(email_sent),
        "reissue_count": 0,
        "parent_run_id": parent_run_id,
        "reissue_reason": reissue_reason,
        "policy": {
            "send_email": bool(result.decision.send_email),
            "create_naver_draft": bool(result.decision.create_naver_draft),
            "require_review": bool(result.decision.require_review),
            "suppress_external": bool(result.decision.suppress_external),
        },
        "issue_codes": runtime_check.get("issue_codes", []),
        "content_quality_warnings": runtime_check.get("content_quality_warnings", []),
        "target_date": runtime_check.get("target_date"),
        "owner_review_status": "pending_review",
        "customer_delivery_status": "not_sent",
        "admin_reissue": bool(parent_run_id),
    }
    if resolved_trigger:
        meta["trigger_source"] = resolved_trigger
    return meta


def persist_orchestrator_run_artifact(
    result: OrchestrationResult,
    email_sent: bool,
    *,
    parent_run_id: str | None = None,
    reissue_reason: str | None = None,
    trigger_source: str | None = None,
) -> str:
    from admin_store import generate_run_id, save_run_artifact
    from datetime import datetime
    from zoneinfo import ZoneInfo

    mode = str(result.mode or "unknown")
    run_id = generate_run_id(mode)
    meta = build_run_artifact_metadata(
        result,
        run_id=run_id,
        email_sent=email_sent,
        parent_run_id=parent_run_id,
        reissue_reason=reissue_reason,
        trigger_source=trigger_source,
    )
    meta["created_at"] = datetime.now(ZoneInfo("Asia/Seoul")).isoformat()
    email_html = extract_email_html_for_artifact(result)
    return save_run_artifact(meta, email_html=email_html)


def send_email_if_allowed(result: OrchestrationResult) -> bool:
    """
    If policy allows sending email and we have payload, send via email_sender.
    No send on suppress_external or when response_data is missing.
    """
    payload = result.response_data if isinstance(result.response_data, dict) else {}
    runtime_check = _runtime_check_from_api_payload(payload, reason_summary=result.reason_summary)
    send_decision_log = {
        "send_email": bool(result.decision.send_email),
        "create_naver_draft": bool(result.decision.create_naver_draft),
        "suppress_external": bool(result.decision.suppress_external),
        "reason_summary": result.reason_summary,
        "issue_codes": runtime_check.get("issue_codes", []),
        "content_quality_warnings": runtime_check.get("content_quality_warnings", []),
    }
    allow_send = bool(result.decision.send_email)
    if (
        not allow_send
        and _admin_reissue_send_active()
        and result.response_status == 200
        and not result.decision.suppress_external
        and result.response_data
        and _controlled_recipients_ok()
    ):
        allow_send = True
        send_decision_log["admin_reissue_send_override"] = True
    if not allow_send:
        logger.info("today_genie runtime_send_decision: %s", json.dumps(send_decision_log, ensure_ascii=False))
        logger.info("send_email_if_allowed: skipped (policy send_email=False)")
        return False
    if result.decision.suppress_external:
        logger.info("today_genie runtime_send_decision: %s", json.dumps(send_decision_log, ensure_ascii=False))
        logger.info("send_email_if_allowed: skipped (suppress_external=True)")
        return False
    if not result.response_data:
        logger.warning("send_email_if_allowed: skipped (no response_data)")
        return False

    data = result.response_data.get("data") or {}
    channels = data.get("rendered_channels") or {}
    drafts = data.get("channel_drafts") or {}
    subject = drafts.get("email_subject") or "(Genie briefing)"
    mode = (
        str(result.mode or "").strip()
        or str(result.response_data.get("type") or "").strip()
    )
    runtime_input = result.response_data.get("runtime_input")
    if (
        mode == "today_genie"
        and isinstance(runtime_input, dict)
        and runtime_input.get("controlled_test_mode")
    ):
        target_date = str(runtime_input.get("target_date") or "").strip()
        marker = f"[GENIE render test] {target_date} Gmail/Naver 비교"
        subject = marker if not subject else f"{marker} - {subject}"
        if "[GENIE render test]" not in subject:
            logger.warning(
                "send_email_if_allowed: skipped (controlled today_genie subject missing render-test marker)"
            )
            return False
    validation_result = str(result.response_data.get("validation_result") or "pass")
    if _admin_reissue_send_active():
        drafts = data.get("channel_drafts") or {}
        base_subj = drafts.get("email_subject") or "(Genie briefing)"
        subject = f"[GENIE owner reissue] {base_subj}"
    elif mode == "today_genie":
        drafts = data.get("channel_drafts") or {}
        base_subj = drafts.get("email_subject") or "(Genie briefing)"
        subject = f"[운영자 검토] {base_subj}"

    # Canonical today_genie handoff send path: owner-review rich MIME + CID inline only.
    if mode == "today_genie":
        try:
            from main import build_today_genie_email_html_for_cid_mime_send
            from renderers import today_genie_email_inline_cid_pair
        except Exception as e:  # noqa: BLE001
            logger.warning("send_email_if_allowed: today_genie rich imports failed: %s", e)
            return False

        if (
            isinstance(runtime_input, dict)
            and runtime_input.get("controlled_test_mode")
            and _controlled_test_send_env_active()
        ):
            if not _controlled_recipients_ok():
                logger.warning(
                    "send_email_if_allowed: skipped (controlled test EMAIL_TO not exactly approved list)"
                )
                return False

        html_body = build_today_genie_email_html_for_cid_mime_send(
            data,
            validation_result=validation_result,
        )
        if not html_body.strip():
            logger.warning("send_email_if_allowed: skipped (empty today_genie rich html)")
            return False

        repo = Path(__file__).resolve().parent
        top_latest = repo / "static" / "email" / "GENIE_EMAIL_today_genie_top_latest.jpg"
        bottom_latest = repo / "static" / "email" / "GENIE_EMAIL_today_genie_bottom_latest.jpg"
        if not top_latest.is_file() or not bottom_latest.is_file():
            logger.warning(
                "send_email_if_allowed: skipped (today_genie latest image assets missing: top=%s bottom=%s)",
                top_latest.is_file(),
                bottom_latest.is_file(),
            )
            return False

        cid_top, cid_bottom = today_genie_email_inline_cid_pair()
        inline_parts = [
            (str(top_latest), cid_top, "GENIE_EMAIL_today_genie_top.jpg"),
            (str(bottom_latest), cid_bottom, "GENIE_EMAIL_today_genie_bottom.jpg"),
        ]
        os.environ.setdefault("GENIE_EMAIL_RICH_MODE", "1")
        return send_genie_email(
            html_body,
            subject,
            inline_jpeg_parts=inline_parts,
            attachment_jpeg_parts=[],
        )

    html_body = channels.get("email_body_html") or ""

    if not html_body.strip():
        logger.warning("send_email_if_allowed: skipped (empty email_body_html)")
        return False

    return send_genie_email(html_body, subject)


def create_naver_draft_if_allowed(result: OrchestrationResult) -> bool:
    """
    If policy allows creating a Naver draft and we have payload, create via naver_draft.
    Today_Geenee registry disables Naver assets entirely.
    """
    mode = str(result.mode or "").strip()
    if not _program_allows_naver_draft(mode):
        logger.info("create_naver_draft_if_allowed: skipped (naver_assets_enabled=false for %s)", mode)
        return False
    if not result.decision.create_naver_draft:
        logger.info("create_naver_draft_if_allowed: skipped (policy create_naver_draft=False)")
        return False
    if result.decision.suppress_external:
        logger.info("create_naver_draft_if_allowed: skipped (suppress_external=True)")
        return False
    if not result.response_data:
        logger.warning("create_naver_draft_if_allowed: skipped (no response_data)")
        return False

    data = result.response_data.get("data") or {}
    channels = data.get("rendered_channels") or {}
    drafts = data.get("channel_drafts") or {}
    html_body = channels.get("naver_blog_body_html") or ""
    title = drafts.get("naver_blog_title") or "(Genie draft)"

    if not html_body.strip():
        logger.warning("create_naver_draft_if_allowed: skipped (empty naver_blog_body_html)")
        return False

    return create_naver_draft(html_body, title)


def execute_orchestrator_run(
    mode: str,
    *,
    parent_run_id: str | None = None,
    reissue_reason: str | None = None,
    admin_reissue: bool = False,
    trigger_source: str | None = None,
) -> tuple[str, OrchestrationResult, bool]:
    """
    Run Genie job, attempt owner-review email, persist admin artifact.
    Returns (run_id, result, email_sent).
    """
    prev_flag = os.environ.get("GENIE_ADMIN_REISSUE")
    if admin_reissue:
        os.environ["GENIE_ADMIN_REISSUE"] = "1"
    try:
        result = run_genie_job(mode)
        email_sent = send_email_if_allowed(result)
        resolved_trigger = trigger_source
        if not resolved_trigger:
            if parent_run_id:
                resolved_trigger = "reissue"
            elif admin_reissue:
                resolved_trigger = "reissue"
        run_id = persist_orchestrator_run_artifact(
            result,
            email_sent,
            parent_run_id=parent_run_id,
            reissue_reason=reissue_reason,
            trigger_source=resolved_trigger,
        )
        logger.info(
            "execute_orchestrator_run: mode=%s run_id=%s email_sent=%s parent_run_id=%s",
            mode,
            run_id,
            email_sent,
            parent_run_id or "",
        )
        return run_id, result, email_sent
    finally:
        if admin_reissue:
            if prev_flag is None:
                os.environ.pop("GENIE_ADMIN_REISSUE", None)
            else:
                os.environ["GENIE_ADMIN_REISSUE"] = prev_flag
