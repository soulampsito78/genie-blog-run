"""Today_Geenee customer-final email: HTML body + inline CID only (no Naver package)."""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from admin_store import _get_gcs_client, resolve_customer_recipients
from customer_review_confirmation import (
    DELEGATED_WORK_REVIEW,
    HUMAN_OWNER,
    PRE_SEND_REVIEWED,
    PRE_SEND_OWNER_WITH_WARNINGS,
    customer_review_confirmation,
    today_delegated_warning_eligible,
    today_quality_warning_present,
)
from email_sender import parse_customer_to_addrs, send_genie_email
from renderers import today_genie_email_inline_cid_pair

logger = logging.getLogger(__name__)

REVIEW_CONFIRMATION_STATE_REVIEW_PASSED = "review_passed"
REVIEW_CONFIRMATION_STATE_OWNER_WARNING = "owner_send_with_warnings"

_GENIE_CUSTOMER_OUTBOUND_REVIEW_STATES = frozenset({
    REVIEW_CONFIRMATION_STATE_REVIEW_PASSED, REVIEW_CONFIRMATION_STATE_OWNER_WARNING,
})

_OPERATIONAL_HANDOFF_RE = re.compile(
    r'<section[^>]*\bid=["\']genie-operational-handoff["\'][^>]*>.*?</section>',
    re.IGNORECASE | re.DOTALL,
)

_NAVER_MARKER_FRAGMENTS = (
    "[네이버 블로그 복사용 본문 시작]",
    "[네이버 블로그 복사용 본문 끝]",
    "[본문 크기 안내]",
    "[사용 안내]",
    "naver_ready_article.html",
    "genie-customer-naver-paste-body",
)

TODAY_IMAGE_REASON_GENERATED = "today_generated_images_resolved"
TODAY_IMAGE_REASON_STATIC_FALLBACK = "today_static_fallback"
TODAY_IMAGE_REASON_GENERATED_PATHS_MISSING = "today_generated_paths_missing"
TODAY_IMAGE_REASON_GENERATED_TOP_MISSING = "today_generated_top_path_missing"
TODAY_IMAGE_REASON_GENERATED_BOTTOM_MISSING = "today_generated_bottom_path_missing"
TODAY_IMAGE_REASON_GENERATED_STATUS_INVALID = "today_generated_status_invalid"
TODAY_IMAGE_REASON_GENERATED_FALLBACK_CONFLICT = "today_generated_fallback_conflict"
TODAY_IMAGE_REASON_GENERATED_FILES_UNAVAILABLE = "today_generated_files_unavailable"
_LAST_CUSTOMER_IMAGE_RESOLUTION_REASON = ""


@dataclass(frozen=True)
class TodayGenieCustomerImageResolution:
    inline_parts: Optional[List[Tuple[str, str, str]]]
    source: str
    reason_code: str


def last_customer_image_resolution_reason() -> str:
    return _LAST_CUSTOMER_IMAGE_RESOLUTION_REASON


def strip_owner_operational_handoff(html_body: str) -> str:
    """Remove owner-review operational handoff block from customer-facing HTML."""
    if not html_body:
        return ""
    return _OPERATIONAL_HANDOFF_RE.sub("", html_body).strip()


def customer_html_contains_naver_markers(html_body: str) -> bool:
    blob = html_body or ""
    lower = blob.lower()
    return any(frag.lower() in lower for frag in _NAVER_MARKER_FRAGMENTS)


def customer_delivery_config_ready() -> tuple[bool, str]:
    if not resolve_customer_recipients()["final_recipients"]:
        return False, "missing_customer_to"
    host = os.getenv("SMTP_HOST", "").strip()
    user = os.getenv("SMTP_USER", "").strip()
    if not (host and user):
        return False, "missing_smtp"
    return True, "ok"


def _resolve_path_under_repo(path_value: str) -> Path:
    repo = Path(__file__).resolve().parent
    raw = Path(str(path_value or "").strip())
    if raw.is_absolute():
        return raw
    return (repo / raw).resolve()


def _download_gcs_customer_image(bucket_name: str, object_name: str, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    _get_gcs_client().bucket(bucket_name).blob(object_name).download_to_filename(str(target))


def _generated_provenance_present(meta: Dict[str, Any]) -> bool:
    return any(
        (
            meta.get("image_source") == "generated",
            meta.get("image_generation_status") == "generated",
            bool(meta.get("generated_image_paths")),
            meta.get("customer_image_source") == "generated_run_images",
            meta.get("run_specific_images") is True,
        )
    )


def _inline_parts_for_paths(top_path: Path, bottom_path: Path) -> List[Tuple[str, str, str]]:
    cid_top, cid_bottom = today_genie_email_inline_cid_pair()
    return [
        (str(top_path), cid_top, top_path.name or "GENIE_EMAIL_today_genie_top.jpg"),
        (str(bottom_path), cid_bottom, bottom_path.name or "GENIE_EMAIL_today_genie_bottom.jpg"),
    ]


def _resolve_today_genie_customer_image_result(
    meta: Dict[str, Any],
    *,
    download_fn: Optional[Callable[[str, str, Path], None]] = None,
) -> TodayGenieCustomerImageResolution:
    generated_intent = _generated_provenance_present(meta)
    if generated_intent:
        if meta.get("fallback_used") is True:
            return TodayGenieCustomerImageResolution(
                None, "blocked", TODAY_IMAGE_REASON_GENERATED_FALLBACK_CONFLICT
            )
        if (
            meta.get("image_source") != "generated"
            or meta.get("image_generation_status") != "generated"
        ):
            return TodayGenieCustomerImageResolution(
                None, "blocked", TODAY_IMAGE_REASON_GENERATED_STATUS_INVALID
            )
        paths = meta.get("generated_image_paths")
        if not isinstance(paths, dict):
            return TodayGenieCustomerImageResolution(
                None, "blocked", TODAY_IMAGE_REASON_GENERATED_PATHS_MISSING
            )
        raw_top = str(paths.get("top") or "").strip()
        raw_bottom = str(paths.get("bottom") or "").strip()
        if not raw_top:
            return TodayGenieCustomerImageResolution(
                None, "blocked", TODAY_IMAGE_REASON_GENERATED_TOP_MISSING
            )
        if not raw_bottom:
            return TodayGenieCustomerImageResolution(
                None, "blocked", TODAY_IMAGE_REASON_GENERATED_BOTTOM_MISSING
            )
        top_path = _resolve_path_under_repo(raw_top)
        bottom_path = _resolve_path_under_repo(raw_bottom)
        if top_path.is_file() and bottom_path.is_file():
            return TodayGenieCustomerImageResolution(
                _inline_parts_for_paths(top_path, bottom_path),
                "generated_run_images",
                TODAY_IMAGE_REASON_GENERATED,
            )

        bucket = str(meta.get("customer_image_gcs_bucket") or "").strip()
        objects = meta.get("customer_image_gcs_objects")
        if bucket and isinstance(objects, dict):
            top_object = str(objects.get("top") or "").strip()
            bottom_object = str(objects.get("bottom") or "").strip()
            if top_object and bottom_object:
                downloader = download_fn or _download_gcs_customer_image
                try:
                    downloader(bucket, top_object, top_path)
                    downloader(bucket, bottom_object, bottom_path)
                except Exception:
                    logger.exception("today_genie customer image GCS restore failed")
                if top_path.is_file() and bottom_path.is_file():
                    return TodayGenieCustomerImageResolution(
                        _inline_parts_for_paths(top_path, bottom_path),
                        "generated_run_images",
                        TODAY_IMAGE_REASON_GENERATED,
                    )
        return TodayGenieCustomerImageResolution(
            None, "blocked", TODAY_IMAGE_REASON_GENERATED_FILES_UNAVAILABLE
        )

    repo = Path(__file__).resolve().parent
    top_latest = repo / "static" / "email" / "GENIE_EMAIL_today_genie_top_latest.jpg"
    bottom_latest = repo / "static" / "email" / "GENIE_EMAIL_today_genie_bottom_latest.jpg"
    if not top_latest.is_file() or not bottom_latest.is_file():
        return TodayGenieCustomerImageResolution(
            None, "blocked", TODAY_IMAGE_REASON_GENERATED_FILES_UNAVAILABLE
        )
    return TodayGenieCustomerImageResolution(
        _inline_parts_for_paths(top_latest, bottom_latest),
        "static_latest_fallback",
        TODAY_IMAGE_REASON_STATIC_FALLBACK,
    )


def resolve_today_genie_reusable_images(
    meta: Dict[str, Any],
    *,
    download_fn: Optional[Callable[[str, str, Path], None]] = None,
) -> TodayGenieCustomerImageResolution:
    """Resolve a stored run's images for reuse (body_only reissue keeps parent images).

    Same resolution contract as the approved customer send: generated run images
    first (restoring from GCS when the local file is gone), static latest only
    when the run never had run-specific images.
    """
    return _resolve_today_genie_customer_image_result(meta, download_fn=download_fn)


def _resolve_today_genie_inline_jpeg_parts_from_meta(
    meta: Dict[str, Any],
) -> Optional[List[Tuple[str, str, str]]]:
    return _resolve_today_genie_customer_image_result(meta).inline_parts


def _resolve_today_genie_inline_jpeg_parts(
    meta: Optional[Dict[str, Any]] = None,
) -> Optional[List[Tuple[str, str, str]]]:
    global _LAST_CUSTOMER_IMAGE_RESOLUTION_REASON

    resolution = _resolve_today_genie_customer_image_result(meta or {})
    _LAST_CUSTOMER_IMAGE_RESOLUTION_REASON = resolution.reason_code
    return resolution.inline_parts


def build_customer_final_subject(meta: Dict[str, Any], saved_html: str) -> str:
    drafts_subj = ""
    if isinstance(meta.get("email_subject"), str):
        drafts_subj = meta["email_subject"].strip()
    if not drafts_subj:
        m = re.search(r"<h1[^>]*>([^<]+)</h1>", saved_html or "", re.IGNORECASE)
        if m:
            drafts_subj = m.group(1).strip()
    if not drafts_subj:
        drafts_subj = "오늘의 지니 장전 브리핑"
    # Reissue markers are stripped before the owner-review marker so a scoped
    # reissue subject ("[이미지 재발행][운영자 검토] …") never reaches a customer.
    for prefix in (
        "[본문 재발행]",
        "[이미지 재발행]",
        "[GENIE owner reissue]",
        "[GENIE render test]",
        "[운영자 검토]",
    ):
        if drafts_subj.startswith(prefix):
            drafts_subj = drafts_subj.split("]", 1)[-1].strip(" -")
    return drafts_subj


def render_genie_review_confirmation_box(
    review_state: str,
    *,
    approval_source: str = HUMAN_OWNER,
) -> str:
    """Customer-safe review confirmation box for approved outbound email only."""
    if review_state not in _GENIE_CUSTOMER_OUTBOUND_REVIEW_STATES:
        raise ValueError(
            "unsupported review_confirmation_state for Genie customer outbound email: "
            f"{review_state!r}"
        )
    selected_state, confirmation_text = customer_review_confirmation(
        approval_source=approval_source,
        display_state=(
            PRE_SEND_OWNER_WITH_WARNINGS
            if review_state == REVIEW_CONFIRMATION_STATE_OWNER_WARNING
            else PRE_SEND_REVIEWED
        ),
    )
    if selected_state != review_state:
        raise ValueError("customer review display state does not match review_confirmation_state")
    return (
        f'<section id="review-confirmation-box" '
        f'data-review-state="{review_state}" '
        f'data-review-source="{approval_source}" '
        'style="margin-top:24px;padding:16px 18px;border:1px solid #d9d9d9;'
        'border-radius:8px;background:#fafafa;">'
        f'<p class="review-confirmation-text" style="margin:0;font-size:14px;'
        f'line-height:1.65;color:#1a1a1a;">{confirmation_text}</p>'
        "</section>"
    )


def prepare_customer_final_html(
    saved_html: str,
    *,
    review_confirmation_state: str | None = None,
    approval_source: str = HUMAN_OWNER,
) -> str:
    from auto_remediation import strip_auto_remediation_notice

    # Owner-only 자동 교정본 header: never part of a customer surface.
    html_body = strip_auto_remediation_notice(strip_owner_operational_handoff(saved_html))
    if customer_html_contains_naver_markers(html_body):
        raise ValueError("customer final HTML contains forbidden Naver markers")
    if not html_body.strip():
        raise ValueError("customer final HTML is empty after stripping operational handoff")
    if review_confirmation_state is None:
        return html_body
    if review_confirmation_state not in _GENIE_CUSTOMER_OUTBOUND_REVIEW_STATES:
        raise ValueError(
            "unsupported review_confirmation_state for Genie customer outbound email: "
            f"{review_confirmation_state!r}"
        )
    review_box = render_genie_review_confirmation_box(
        review_confirmation_state,
        approval_source=approval_source,
    )
    return f"{html_body}\n{review_box}"


def send_today_geenee_customer_final_email(
    saved_html: str,
    meta: Dict[str, Any],
    *,
    prepared_delivery: Optional[Dict[str, Any]] = None,
) -> bool:
    """
    Send approved customer email: text/html body with inline CID JPEG parts only.
    No HTML attachment, no image attachments, no Naver paste body.
    """
    prepared = dict(prepared_delivery or prepare_today_geenee_customer_delivery(saved_html, meta))
    if not prepared.get("ok"):
        logger.warning(
            "send_today_geenee_customer_final_email: blocked (%s)",
            prepared.get("error") or "today_delivery_preparation_failed",
        )
        return False
    return send_genie_email(
        str(prepared["html_body"]),
        str(prepared["subject"]),
        inline_jpeg_parts=list(prepared["inline_jpeg_parts"]),
        attachment_jpeg_parts=[],
        to_addrs_override=list(prepared["recipients"]),
        allow_rich_delivery=True,
    )


def prepare_today_geenee_customer_delivery(
    saved_html: str,
    meta: Dict[str, Any],
    *,
    recipients_override: Optional[List[str]] = None,
    approval_source: str = HUMAN_OWNER,
) -> Dict[str, Any]:
    """Prepare the exact customer payload without submitting it to SMTP.

    ``approval_source`` controls only the displayed attestation.  It cannot
    grant delivery authority and is explicitly supplied by the delegated gate.
    """
    if recipients_override is None:
        ready, err = customer_delivery_config_ready()
        if not ready:
            return {"ok": False, "error": err}
    warning_present = today_quality_warning_present(meta)
    delegated_warning_ok = today_delegated_warning_eligible(meta)
    if warning_present:
        if approval_source == HUMAN_OWNER:
            review_confirmation_state = REVIEW_CONFIRMATION_STATE_OWNER_WARNING
        elif approval_source == DELEGATED_WORK_REVIEW and delegated_warning_ok:
            review_confirmation_state = REVIEW_CONFIRMATION_STATE_REVIEW_PASSED
        else:
            return {"ok": False, "error": "manual_warning_requires_human_owner"}
    else:
        review_confirmation_state = REVIEW_CONFIRMATION_STATE_REVIEW_PASSED
    try:
        html_body = prepare_customer_final_html(
            saved_html,
            review_confirmation_state=review_confirmation_state,
            approval_source=approval_source,
        )
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    global _LAST_CUSTOMER_IMAGE_RESOLUTION_REASON
    _LAST_CUSTOMER_IMAGE_RESOLUTION_REASON = ""
    inline_parts = _resolve_today_genie_inline_jpeg_parts(meta)
    if inline_parts is None:
        return {
            "ok": False,
            "error": _LAST_CUSTOMER_IMAGE_RESOLUTION_REASON or "today_image_resolution_failed",
        }
    recipients = (
        list(recipients_override)
        if recipients_override is not None
        else list(resolve_customer_recipients()["final_recipients"])
    )
    if not recipients:
        return {"ok": False, "error": "missing_customer_to"}
    return {
        "ok": True,
        "html_body": html_body,
        "subject": build_customer_final_subject(meta, saved_html),
        "inline_jpeg_parts": list(inline_parts),
        "recipients": recipients,
    }


def render_today_geenee_postsend_frozen_preview(
    saved_html: str,
    meta: Dict[str, Any],
    *,
    recipients_override: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Reconstruct already signed-and-accepted frozen customer body for read-only preview.

    Does not grant delivery authority, backdate clocks, or relax send eligibility.
    Validates exact immutable event/result/attempt/outcome proof and candidate binding.
    Fails closed if proof is missing, tampered, or mismatched.
    """
    import hashlib
    import admin_safety_store as s_store
    from delegated_delivery_safety import PRODUCTS, _digest

    run_id = str(meta.get("run_id") or "").strip()
    mode = str(meta.get("mode") or "").strip()
    if mode != "today_genie" or not run_id:
        return {"ok": False, "error": "unsupported_frozen_preview_target"}

    approval_source = str(meta.get("approval_source") or "").strip()
    if approval_source != DELEGATED_WORK_REVIEW:
        return {"ok": False, "error": "frozen_preview_requires_delegated_review"}

    delivery_status = str(meta.get("customer_delivery_status") or meta.get("customer_email_delivery_status") or "").strip().upper()
    if delivery_status not in {"ACCEPTED_ALL", "SMTP_ACCEPTED"}:
        return {"ok": False, "error": "frozen_preview_requires_accepted_delivery"}

    review_id = str(meta.get("delegated_review_id") or "").strip()
    candidate_sha256 = str(meta.get("delegated_candidate_sha256") or "").strip()
    if not review_id or not candidate_sha256:
        return {"ok": False, "error": "missing_delegated_review_identity"}

    s_product = PRODUCTS.get("today_genie")
    if not s_product or len(run_id) < 8 or not run_id[:8].isdigit():
        return {"ok": False, "error": "invalid_run_identity"}

    s_day = f"{run_id[:4]}-{run_id[4:6]}-{run_id[6:8]}"
    attempt_id = str(meta.get("delegated_delivery_attempt_id") or "").strip()
    expected_attempt_id = "publication_" + _digest([s_product, s_day])
    if attempt_id and attempt_id != expected_attempt_id:
        return {"ok": False, "error": "delegated_attempt_id_mismatch"}
    attempt_id = expected_attempt_id

    # 1. Load and verify delegated_review_events/<review_id>.json
    event_record = s_store._read_json(f"delegated_review_events/{review_id}.json")
    if not event_record or not isinstance(event_record, dict):
        return {"ok": False, "error": "delegated_review_event_missing"}
    ev_inner = event_record.get("event")
    if not isinstance(ev_inner, dict) or str(ev_inner.get("run_id") or "").strip() != run_id:
        return {"ok": False, "error": "delegated_review_event_run_mismatch"}
    ev_cand = str(ev_inner.get("candidate_sha256") or "").strip()
    if not ev_cand or ev_cand != candidate_sha256:
        return {"ok": False, "error": "delegated_review_event_candidate_mismatch"}

    review = ev_inner.get("review")
    if not isinstance(review, dict):
        return {"ok": False, "error": "delegated_review_payload_missing"}

    from delegated_gate import digest

    orig_art_meta = review.get("artifact_metadata")
    orig_art_sha = str(review.get("artifact_sha256") or "").strip()
    if not orig_art_sha:
        return {"ok": False, "error": "missing_signed_artifact_sha"}
    if orig_art_meta is not None:
        if not isinstance(orig_art_meta, dict) or digest(orig_art_meta) != orig_art_sha:
            return {"ok": False, "error": "signed_artifact_metadata_tampered"}

    orig_recv_html_sha = str(review.get("received_html_sha256") or "").strip()
    if not orig_recv_html_sha:
        return {"ok": False, "error": "missing_signed_received_html_sha"}
    actual_recv_html_sha = hashlib.sha256(saved_html.encode("utf-8")).hexdigest()
    if actual_recv_html_sha != orig_recv_html_sha:
        return {"ok": False, "error": "received_html_sha_mismatch"}

    orig_subject_sha = str(review.get("subject_sha256") or "").strip()
    if not orig_subject_sha:
        return {"ok": False, "error": "missing_signed_subject_sha"}
    subject = build_customer_final_subject(meta, saved_html)
    actual_subject_sha = hashlib.sha256(str(subject).encode("utf-8")).hexdigest()
    if actual_subject_sha != orig_subject_sha:
        return {"ok": False, "error": "signed_subject_sha_mismatch"}

    orig_body_sha = str(review.get("body_sha256") or "").strip()
    if not orig_body_sha:
        return {"ok": False, "error": "missing_signed_body_sha"}
    try:
        html_body = prepare_customer_final_html(
            saved_html,
            review_confirmation_state=REVIEW_CONFIRMATION_STATE_REVIEW_PASSED,
            approval_source=DELEGATED_WORK_REVIEW,
        )
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    actual_body_sha = hashlib.sha256(html_body.encode("utf-8")).hexdigest()
    if actual_body_sha != orig_body_sha:
        return {"ok": False, "error": "signed_body_sha_mismatch"}

    global _LAST_CUSTOMER_IMAGE_RESOLUTION_REASON
    _LAST_CUSTOMER_IMAGE_RESOLUTION_REASON = ""
    inline_parts = _resolve_today_genie_inline_jpeg_parts(meta)
    if inline_parts is None:
        return {
            "ok": False,
            "error": _LAST_CUSTOMER_IMAGE_RESOLUTION_REASON or "today_image_resolution_failed",
        }

    orig_image_identity = review.get("image_identity")
    orig_image_sha256 = review.get("image_sha256")
    if not orig_image_identity and not orig_image_sha256:
        return {"ok": False, "error": "missing_signed_image_proof"}

    resolved_images = []
    for index, (path, cid, filename) in enumerate(inline_parts):
        role = "top" if index == 0 else "bottom" if index == 1 else f"image_{index+1}"
        p = Path(path)
        if not p.is_file():
            return {"ok": False, "error": "resolved_image_file_missing"}
        img_bytes = p.read_bytes()
        if not img_bytes:
            return {"ok": False, "error": "resolved_image_empty"}
        c_sha = hashlib.sha256(img_bytes).hexdigest()
        resolved_images.append({
            "role": role,
            "cid": str(cid),
            "filename": Path(filename).name,
            "sha256": c_sha,
        })

    if isinstance(orig_image_identity, list):
        if len(resolved_images) != len(orig_image_identity):
            return {"ok": False, "error": "signed_image_count_mismatch"}
        for res_img, exp_img in zip(resolved_images, orig_image_identity):
            if not isinstance(exp_img, dict):
                return {"ok": False, "error": "signed_image_identity_malformed"}
            if res_img["role"] != exp_img.get("role") or res_img["cid"] != str(exp_img.get("cid")) or res_img["sha256"] != exp_img.get("sha256"):
                return {"ok": False, "error": "signed_image_identity_mismatch"}

    if isinstance(orig_image_sha256, dict):
        for res_img in resolved_images:
            exp_sha = orig_image_sha256.get(res_img["role"])
            if not exp_sha or exp_sha != res_img["sha256"]:
                return {"ok": False, "error": "signed_image_sha_mismatch"}

    # 2. Load and verify delegated_review_results/<review_id>.json
    result_record = s_store._read_json(f"delegated_review_results/{review_id}.json")
    if not result_record or not isinstance(result_record, dict):
        return {"ok": False, "error": "delegated_review_result_missing"}
    if result_record.get("verdict") != "PASS":
        return {"ok": False, "error": "delegated_review_result_not_pass"}
    if str(result_record.get("run_id") or "").strip() != run_id:
        return {"ok": False, "error": "delegated_review_result_run_mismatch"}
    if str(result_record.get("review_id") or "").strip() != review_id:
        return {"ok": False, "error": "delegated_review_result_review_mismatch"}
    if str(result_record.get("candidate_sha256") or "").strip() != candidate_sha256:
        return {"ok": False, "error": "delegated_review_candidate_mismatch"}
    if str(result_record.get("attempt_id") or "").strip() != attempt_id:
        return {"ok": False, "error": "delegated_review_result_attempt_mismatch"}

    # 3. Load and verify publication_attempts/<attempt_id>.json
    attempt_record = s_store._read_json(f"publication_attempts/{attempt_id}.json")
    if not attempt_record or not isinstance(attempt_record, dict):
        return {"ok": False, "error": "publication_attempt_missing"}
    if str(attempt_record.get("run_id") or "").strip() != run_id:
        return {"ok": False, "error": "publication_attempt_run_mismatch"}
    if str(attempt_record.get("candidate_sha256") or "").strip() != candidate_sha256:
        return {"ok": False, "error": "publication_attempt_candidate_mismatch"}
    if str(attempt_record.get("review_id") or "").strip() != review_id:
        return {"ok": False, "error": "publication_attempt_review_mismatch"}
    att_prod = attempt_record.get("product_code") or attempt_record.get("product")
    if att_prod and str(att_prod) != s_product:
        return {"ok": False, "error": "publication_attempt_product_mismatch"}
    att_day = attempt_record.get("publication_date") or attempt_record.get("day")
    if att_day and str(att_day) != s_day:
        return {"ok": False, "error": "publication_attempt_date_mismatch"}

    # 4. Load and verify publication_outcomes/<attempt_id>.json
    outcome_record = s_store._read_json(f"publication_outcomes/{attempt_id}.json")
    if not outcome_record or not isinstance(outcome_record, dict):
        return {"ok": False, "error": "publication_outcome_missing"}
    if outcome_record.get("outcome") != "PROVIDER_ACCEPTED":
        return {"ok": False, "error": "publication_outcome_not_accepted"}
    if str(outcome_record.get("attempt_id") or "").strip() != attempt_id:
        return {"ok": False, "error": "publication_outcome_attempt_mismatch"}

    recipients = (
        list(recipients_override)
        if recipients_override is not None
        else list(resolve_customer_recipients()["final_recipients"])
    )
    if not recipients:
        return {"ok": False, "error": "missing_customer_to"}

    return {
        "ok": True,
        "html_body": html_body,
        "subject": subject,
        "inline_jpeg_parts": list(inline_parts),
        "recipients": recipients,
    }


def send_customer_timeout_draft_email(*_args: Any, **_kwargs: Any) -> bool:
    """Retired: timeout-based customer auto-send is not active policy."""
    logger.info("send_customer_timeout_draft_email: retired no-op (timeout auto-send removed)")
    return False
