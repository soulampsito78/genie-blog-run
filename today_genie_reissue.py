"""Today_Geenee scoped admin reissue runners (body_only / image_only).

Scope semantics mirror the Kee-Suri runners as closely as the Today architecture
allows, but this module never calls a Kee-Suri runner:

body_only
    Regenerate the briefing text through the normal Today pipeline and reuse the
    parent run's images verbatim (no image API call).

image_only
    Regenerate the images exactly once and reuse the parent's stored owner-review
    body verbatim (no Gemini text call, no news/source fetch).

Both scopes send the owner-review email at most once and never authorize
customer delivery (customer_delivery_status stays not_sent).
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from admin_store import (
    generate_run_id,
    load_run_artifact,
    load_run_email_html,
    now_kst_iso,
    save_run_artifact,
    update_run_artifact,
)
from service_full_run_contract import (
    IMAGE_GEN_FAILED,
    IMAGE_GEN_GENERATED,
    IMAGE_SOURCE_GENERATED,
)
from today_genie_orchestrator_images import (
    IMAGE_SOURCE_STATIC_FALLBACK,
    STATIC_FALLBACK_ISSUE_CODE,
    TODAY_IMAGE_REGEN_INPUTS_KEY,
    TodayGenieOrchestratorImageResult,
    generate_today_genie_orchestrator_images,
    persist_today_genie_customer_images,
    today_image_regen_payload_from_snapshot,
)

logger = logging.getLogger(__name__)

TODAY_MODE = "today_genie"

BODY_ONLY_SUBJECT_PREFIX = "[본문 재발행]"
IMAGE_ONLY_SUBJECT_PREFIX = "[이미지 재발행]"

BODY_ONLY_TRIGGER_SOURCE = "admin_today_body_only_reissue"
IMAGE_ONLY_TRIGGER_SOURCE = "admin_today_image_only_reissue"

ERROR_BODY_ONLY_UNSUPPORTED_MODE = "today_body_only_reissue_unsupported_mode"
ERROR_BODY_ONLY_PARENT_IMAGES_UNAVAILABLE = "today_body_only_reissue_parent_images_unavailable"
ERROR_BODY_ONLY_TEXT_FAILED = "today_body_only_reissue_text_generation_failed"
ERROR_IMAGE_ONLY_UNSUPPORTED_MODE = "today_image_only_reissue_unsupported_mode"
ERROR_IMAGE_ONLY_MISSING_PARENT_HTML = "today_image_only_reissue_missing_parent_email_html"
ERROR_IMAGE_ONLY_MISSING_PROMPT_SNAPSHOT = "today_image_only_reissue_missing_image_prompt_snapshot"
ERROR_IMAGE_ONLY_IMAGE_FAILED = "today_image_only_reissue_image_generation_failed"

OWNER_REVIEW_SEND_GATE_OFF = "owner_review_send_gate_off"


def _parent_mode(parent: Dict[str, Any]) -> str:
    return str(parent.get("mode") or parent.get("program_id") or "").strip()


def _load_parent(
    parent_run_id: str,
    parent_meta: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    return dict(parent_meta or load_run_artifact(parent_run_id, normalize=False) or {})


def _scope_common_meta(
    *,
    scope: str,
    parent_run_id: str,
    reissue_reason_code: str,
    reissue_reason_note: str,
) -> Dict[str, Any]:
    """Scope/lineage metadata shared by both Today scoped reissue paths."""
    ts = now_kst_iso()
    return {
        "reissue_scope": scope,
        "reissue_scope_supported": True,
        "reissue_scope_status": "executed",
        "reissue_reason_code": reissue_reason_code or None,
        "reissue_reason_note": reissue_reason_note or None,
        "reissue_requested_at": ts,
        "reissue_requested_by": "owner_admin",
        "regen_type": scope,
        "regen_parent_run_id": parent_run_id,
        "regen_requested_at_kst": ts,
        "regen_requested_by": "admin",
        "admin_reissue": True,
        "customer_delivery_status": "not_sent",
        "customer_approve_called": False,
        "customer_final_email_called": False,
    }


# ---------------------------------------------------------------------------
# body_only: fresh text, parent images reused
# ---------------------------------------------------------------------------

def build_reused_today_image_result(
    parent: Dict[str, Any],
    *,
    download_fn: Optional[Callable[[str, str, Path], None]] = None,
) -> Tuple[Optional[TodayGenieOrchestratorImageResult], Dict[str, Any]]:
    """Resolve the parent run's images as an image result with zero generation.

    Returns (image_result, provenance_fields); image_result is None when the
    parent's images cannot be resolved, in which case a body_only reissue must
    not proceed (it would silently swap in unrelated imagery).
    """
    from today_geenee_customer_delivery import resolve_today_genie_reusable_images

    resolution = resolve_today_genie_reusable_images(parent, download_fn=download_fn)
    parent_run_id = str(parent.get("run_id") or "").strip()
    if not resolution.inline_parts:
        return None, {
            "today_image_reuse_status": "unavailable",
            "today_image_reuse_reason": resolution.reason_code,
        }

    reused_generated = resolution.source == "generated_run_images"
    paths = parent.get("generated_image_paths")
    generated_paths: Dict[str, Optional[str]] = {"top": None, "bottom": None}
    if reused_generated and isinstance(paths, dict):
        generated_paths = {
            "top": str(paths.get("top") or "") or None,
            "bottom": str(paths.get("bottom") or "") or None,
        }
    fields: Dict[str, Any] = {
        "today_image_reuse_status": "reused",
        "today_image_reuse_reason": resolution.reason_code,
        "today_image_reuse_source": resolution.source,
        "reused_images_from_run_id": parent_run_id or None,
        "image_generation_called": False,
        "image_generation_count": 0,
        "called_image_api": False,
    }
    image_result = TodayGenieOrchestratorImageResult(
        bundle=None,
        inline_parts=list(resolution.inline_parts),
        called_image_api=False,
        image_source=IMAGE_SOURCE_GENERATED if reused_generated else IMAGE_SOURCE_STATIC_FALLBACK,
        image_generation_status=IMAGE_GEN_GENERATED if reused_generated else IMAGE_GEN_FAILED,
        generated_image_paths=generated_paths,
        fallback_used=not reused_generated,
        issue_codes=[] if reused_generated else [STATIC_FALLBACK_ISSUE_CODE],
    )
    return image_result, fields


def run_today_body_only_reissue(
    parent_run_id: str,
    *,
    parent_meta: Optional[Dict[str, Any]] = None,
    trigger_source: str = BODY_ONLY_TRIGGER_SOURCE,
    reissue_reason_code: str = "",
    reissue_reason_note: str = "",
    send_owner_email: bool = True,
    orchestrator_runner: Optional[Callable[..., Any]] = None,
    download_fn: Optional[Callable[[str, str, Path], None]] = None,
) -> Dict[str, Any]:
    """Regenerate Today body text through the normal pipeline, reusing parent images."""
    parent = _load_parent(parent_run_id, parent_meta)
    mode = _parent_mode(parent)
    if mode != TODAY_MODE:
        return {"ok": False, "error": ERROR_BODY_ONLY_UNSUPPORTED_MODE, "mode": mode}

    image_result, reuse_fields = build_reused_today_image_result(
        parent, download_fn=download_fn
    )
    if image_result is None:
        return {
            "ok": False,
            "error": ERROR_BODY_ONLY_PARENT_IMAGES_UNAVAILABLE,
            "mode": mode,
            **reuse_fields,
        }

    reason = reissue_reason_code
    if reissue_reason_note:
        reason = f"{reason} — {reissue_reason_note}" if reason else reissue_reason_note

    runner = orchestrator_runner
    if runner is None:
        from orchestrator import execute_orchestrator_run

        runner = execute_orchestrator_run

    try:
        child_run_id, result, email_sent = runner(
            TODAY_MODE,
            parent_run_id=parent_run_id,
            reissue_reason=reason or None,
            admin_reissue=True,
            trigger_source=trigger_source,
            send_owner_email=send_owner_email,
            reissue_scope="body_only",
            today_image_result_override=image_result,
        )
    except Exception:  # noqa: BLE001 - caller renders a safe failure page
        logger.exception("today body_only reissue pipeline failed parent_run_id=%s", parent_run_id)
        return {"ok": False, "error": ERROR_BODY_ONLY_TEXT_FAILED, "mode": mode}

    if not child_run_id:
        return {"ok": False, "error": ERROR_BODY_ONLY_TEXT_FAILED, "mode": mode}

    extra = _scope_common_meta(
        scope="body_only",
        parent_run_id=parent_run_id,
        reissue_reason_code=reissue_reason_code,
        reissue_reason_note=reissue_reason_note,
    )
    extra.update(reuse_fields)
    extra.update(
        {
            "text_generation_called": True,
            "regen_preserved_text": False,
            "regen_regenerated_images": False,
            "owner_email_subject_prefix": BODY_ONLY_SUBJECT_PREFIX,
        }
    )
    if update_run_artifact(child_run_id, lambda child: child.update(extra)) is None:
        logger.warning(
            "today body_only reissue: scope metadata not stamped (child artifact unreadable) run_id=%s",
            child_run_id,
        )

    response_status = getattr(result, "response_status", None)
    validation_result = ""
    payload = getattr(result, "response_data", None)
    if isinstance(payload, dict):
        validation_result = str(payload.get("validation_result") or "")
    return {
        "ok": bool(child_run_id) and (not send_owner_email or bool(email_sent)),
        "run_id": child_run_id,
        "mode": mode,
        "regen_type": "body_only",
        "reissue_scope": "body_only",
        "regen_parent_run_id": parent_run_id,
        "response_status": response_status,
        "validation_result": validation_result,
        "text_generation_called": True,
        "image_generation_called": False,
        "image_generation_count": 0,
        "email_sent": bool(email_sent),
        "customer_delivery_status": "not_sent",
        **reuse_fields,
    }


# ---------------------------------------------------------------------------
# image_only: parent text preserved, images regenerated once
# ---------------------------------------------------------------------------

def _rewrite_owner_review_run_id(html: str, parent_run_id: str, child_run_id: str) -> str:
    """Point the preserved owner-review email at the child run (admin link, run_id line)."""
    if not html or not parent_run_id or parent_run_id == child_run_id:
        return html
    return html.replace(parent_run_id, child_run_id)


def _ensure_child_admin_link(html: str, child_run_id: str) -> Tuple[str, bool]:
    """Guarantee the reissued owner-review email links to the child run's admin page."""
    from admin_urls import build_owner_review_admin_url

    admin_url = build_owner_review_admin_url(child_run_id) or ""
    if not admin_url:
        return html, False
    if admin_url in html:
        return html, True

    from renderers import render_owner_review_admin_link_block

    block = render_owner_review_admin_link_block(admin_url, child_run_id)
    if not block:
        return html, False
    lowered = html.lower()
    idx = lowered.rfind("</body>")
    if idx == -1:
        return f"{html}\n{block}", True
    return f"{html[:idx]}{block}\n{html[idx:]}", True


def _image_only_subject(parent: Dict[str, Any], preserved_email_html: str) -> Tuple[str, str]:
    """Return (customer_safe_base_subject, owner_review_subject)."""
    from today_geenee_customer_delivery import build_customer_final_subject

    base = build_customer_final_subject(parent, preserved_email_html).strip()
    if base.startswith(IMAGE_ONLY_SUBJECT_PREFIX):
        return base, base
    return base, f"{IMAGE_ONLY_SUBJECT_PREFIX}[운영자 검토] {base}".strip()


def run_today_image_only_reissue(
    parent_run_id: str,
    *,
    parent_meta: Optional[Dict[str, Any]] = None,
    parent_email_html: Optional[str] = None,
    trigger_source: str = IMAGE_ONLY_TRIGGER_SOURCE,
    reissue_reason_code: str = "",
    reissue_reason_note: str = "",
    send_owner_email: bool = True,
    image_generate_fn: Optional[Callable[..., Path]] = None,
    send_fn: Optional[Callable[..., bool]] = None,
    upload_fn: Optional[Callable[[str, str, Path], None]] = None,
) -> Dict[str, Any]:
    """Regenerate Today images once and reassemble the owner-review email.

    Deliberately does not call the Genie text API, news/source fetch, customer
    approval, or the customer-final send: the parent's briefing body is reused
    verbatim and only the inline images change.
    """
    parent = _load_parent(parent_run_id, parent_meta)
    mode = _parent_mode(parent)
    if mode != TODAY_MODE:
        return {"ok": False, "error": ERROR_IMAGE_ONLY_UNSUPPORTED_MODE, "mode": mode}

    preserved_email_html = str(
        parent_email_html
        if parent_email_html is not None
        else load_run_email_html(parent_run_id) or ""
    )
    if not preserved_email_html.strip():
        return {"ok": False, "error": ERROR_IMAGE_ONLY_MISSING_PARENT_HTML, "mode": mode}

    regen_payload = today_image_regen_payload_from_snapshot(
        parent.get(TODAY_IMAGE_REGEN_INPUTS_KEY)
    )
    if regen_payload is None:
        return {
            "ok": False,
            "error": ERROR_IMAGE_ONLY_MISSING_PROMPT_SNAPSHOT,
            "mode": mode,
        }
    data, runtime_input = regen_payload

    child_run_id = generate_run_id(TODAY_MODE)
    # Exactly one image generation pass, and no static-latest fallback: an
    # image_only reissue that quietly reused the static asset would not be a new image.
    image_result = generate_today_genie_orchestrator_images(
        child_run_id,
        data,
        runtime_input,
        generate_fn=image_generate_fn,
        allow_static_fallback=False,
    )
    if not image_result.inline_parts or image_result.fallback_used:
        return {
            "ok": False,
            "error": ERROR_IMAGE_ONLY_IMAGE_FAILED,
            "mode": mode,
            "run_id": child_run_id,
            "text_generation_called": False,
            "image_generation_called": True,
            "called_image_api": bool(image_result.called_image_api),
            "issue_codes": list(image_result.issue_codes or []),
        }

    email_html = _rewrite_owner_review_run_id(
        preserved_email_html, parent_run_id, child_run_id
    )
    email_html, admin_link_present = _ensure_child_admin_link(email_html, child_run_id)
    base_subject, subject = _image_only_subject(parent, preserved_email_html)

    issue_codes: List[str] = list(image_result.issue_codes or [])
    smtp_attempted = False
    email_sent = False
    if send_owner_email:
        from publishing_policy import today_owner_review_reissue_send_allowed

        if not today_owner_review_reissue_send_allowed():
            issue_codes.append(OWNER_REVIEW_SEND_GATE_OFF)
        else:
            from email_sender import send_genie_email

            smtp_attempted = True
            os.environ.setdefault("GENIE_EMAIL_RICH_MODE", "1")
            sender = send_fn or send_genie_email
            email_sent = bool(
                sender(
                    email_html,
                    subject,
                    inline_jpeg_parts=list(image_result.inline_parts),
                    attachment_jpeg_parts=[],
                )
            )

    from admin_urls import build_owner_review_admin_url
    from today_genie_orchestrator_images import orchestrator_image_fields_for_artifact

    meta: Dict[str, Any] = {
        "run_id": child_run_id,
        "mode": TODAY_MODE,
        "program_id": TODAY_MODE,
        "parent_run_id": parent_run_id,
        "trigger_source": trigger_source,
        "reissue_reason": _combined_reason(reissue_reason_code, reissue_reason_note),
        "response_status": int(parent.get("response_status") or 200),
        "reason_summary": str(parent.get("reason_summary") or "ok"),
        "validation_result": str(parent.get("validation_result") or "pass"),
        "workflow_status": str(parent.get("workflow_status") or "review_required"),
        "owner_review_status": "pending_review",
        "smtp_attempted": smtp_attempted,
        "email_sent": email_sent,
        "reissue_count": 0,
        "target_date": parent.get("target_date"),
        # email_subject stays customer-safe (no owner/reissue markers); the
        # prefixed owner-review subject is recorded separately.
        "email_subject": base_subject,
        "owner_email_subject": subject,
        "owner_review_url": build_owner_review_admin_url(child_run_id) or None,
        "owner_review_admin_link_present": admin_link_present,
        "email_rebuilt_after_image_reissue": True,
        "reused_body_from_run_id": parent_run_id,
        "regen_preserved_text": True,
        "regen_regenerated_images": True,
        "text_generation_called": False,
        "called_gemini": False,
        "image_generation_called": True,
        "image_generation_count": 1,
        "source_fetch_called": False,
        "news_fetch_called": False,
        "owner_email_subject_prefix": IMAGE_ONLY_SUBJECT_PREFIX,
    }
    # Carry the prompt snapshot forward so the child itself stays image_only-capable.
    if isinstance(parent.get(TODAY_IMAGE_REGEN_INPUTS_KEY), dict):
        meta[TODAY_IMAGE_REGEN_INPUTS_KEY] = parent[TODAY_IMAGE_REGEN_INPUTS_KEY]
    meta.update(
        _scope_common_meta(
            scope="image_only",
            parent_run_id=parent_run_id,
            reissue_reason_code=reissue_reason_code,
            reissue_reason_note=reissue_reason_note,
        )
    )
    meta.update(orchestrator_image_fields_for_artifact(image_result))
    meta.update(persist_today_genie_customer_images(child_run_id, image_result, upload_fn=upload_fn))
    if not send_owner_email:
        meta["verification_mode"] = "no_send_verification"
        meta["send_owner_email"] = False
    if issue_codes:
        meta["issue_codes"] = issue_codes
    for key in ("selected_items", "used_dedup_gate", "dedup_summary"):
        if key in parent:
            meta[key] = parent.get(key)

    saved_run_id = save_run_artifact(meta, email_html=email_html)
    return {
        "ok": not send_owner_email or email_sent,
        "run_id": saved_run_id,
        "mode": mode,
        "regen_type": "image_only",
        "reissue_scope": "image_only",
        "regen_parent_run_id": parent_run_id,
        "text_generation_called": False,
        "called_gemini": False,
        "image_generation_called": True,
        "image_generation_count": 1,
        "called_image_api": bool(image_result.called_image_api),
        "email_sent": email_sent,
        "owner_email_subject": subject,
        "customer_delivery_status": "not_sent",
        "issue_codes": issue_codes,
    }


def _combined_reason(reason_code: str, reason_note: str) -> Optional[str]:
    code = str(reason_code or "").strip()
    note = str(reason_note or "").strip()
    if code and note:
        return f"{code} — {note}"
    return code or note or None
