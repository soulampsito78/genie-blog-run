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
from publishing_policy import PublishingDecision, decide_publishing_actions

logger = logging.getLogger(__name__)

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
    return OrchestrationResult(
        decision=decision,
        reason_summary=reason,
        response_status=status,
        mode=mode,
    )


def send_email_if_allowed(result: OrchestrationResult) -> bool:
    """
    If policy allows sending email and we have payload, send via email_sender.
    No send on suppress_external or when response_data is missing.
    """
    if not result.decision.send_email:
        logger.info("send_email_if_allowed: skipped (policy send_email=False)")
        return False
    if result.decision.suppress_external:
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
    validation_result = str(result.response_data.get("validation_result") or "pass")

    # Canonical today_genie handoff send path: rich MIME + CID inline + attachments.
    if mode == "today_genie":
        try:
            from main import build_today_genie_email_html_for_cid_mime_send
            from renderers import today_genie_email_inline_cid_pair
        except Exception as e:  # noqa: BLE001
            logger.warning("send_email_if_allowed: today_genie rich imports failed: %s", e)
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
        attach_parts = [
            (str(top_latest), "GENIE_EMAIL_today_genie_top.jpg"),
            (str(bottom_latest), "GENIE_EMAIL_today_genie_bottom.jpg"),
        ]
        os.environ.setdefault("GENIE_EMAIL_RICH_MODE", "1")
        return send_genie_email(
            html_body,
            subject,
            inline_jpeg_parts=inline_parts,
            attachment_jpeg_parts=attach_parts,
        )

    html_body = channels.get("email_body_html") or ""

    if not html_body.strip():
        logger.warning("send_email_if_allowed: skipped (empty email_body_html)")
        return False

    return send_genie_email(html_body, subject)


def create_naver_draft_if_allowed(result: OrchestrationResult) -> bool:
    """
    If policy allows creating a Naver draft and we have payload, create via naver_draft.
    No action on suppress_external or when response_data is missing.
    """
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
