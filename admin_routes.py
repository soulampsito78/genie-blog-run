"""Minimal password-protected owner admin for run review and reissue."""
from __future__ import annotations

import hashlib
import hmac
import html
import json
import logging
import os
import re
import secrets
import time
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Mapping, Optional
from urllib.parse import urlencode

logger = logging.getLogger(__name__)

from fastapi import APIRouter, Form, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse

from admin_components import (
    badge as _ui_badge,
    email_preview as _ui_email_preview,
    empty_state as _ui_empty_state,
    esc as _ui_esc,
    layout as _ui_layout,
    metric as _ui_metric,
    page_header as _ui_page_header,
    technical_details as _ui_technical_details,
)
from admin_view_models import (
    ACTIVE_PROGRAMS,
    ACTIVE_PROGRAM_IDS,
    delivery_projection,
    incident_projection,
    incident_current_projection,
    is_active_program,
    latest_by_program,
    needs_review,
    preflight_projection,
    run_projection,
    review_actionability_projection,
    scheduler_label,
)
from admin_preview_assets import read_preview_asset, stream_customer_html_for_admin_preview

from admin_store import (
    EXECUTABLE_REISSUE_SCOPE,
    REISSUE_SCOPES,
    UNSUPPORTED_REISSUE_SCOPES,
    add_beta_recipient,
    artifact_store_display_path,
    apply_reissue_child_metadata,
    approve_run,
    build_customer_delivery_admin_panel,
    can_approve_customer_send,
    hold_run,
    load_beta_recipient_config,
    normalize_reissue_scope,
    now_kst_iso,
    load_run_artifact,
    load_run_email_html,
    list_run_artifact_page,
    list_run_artifacts,
    owner_review_email_label_ko,
    record_parent_reissue_audit,
    reopen_held_run,
    reissue_parent_block_reason,
    remove_beta_recipient,
    resolve_customer_recipients,
    run_email_html_exists,
    update_run_artifact,
    validate_run_id,
)
from admin_cost_ledger import (
    COST_LEDGER_COLUMNS,
    cost_ledger_display_path,
    load_cost_ledger_csv,
    parse_cost_ledger_csv,
    render_cost_ledger_csv,
    month_from_run_meta,
)
from genie_cost_estimate import standard_text_pricing_for_model
from today_genie_orchestrator_images import TODAY_IMAGE_REGEN_INPUTS_KEY
from genie_billing_export import load_billing_summary
from genie_cost_allocation import allocation_metrics, modeled_service_cost
from keysuri_service_full_run import (
    run_keysuri_image_only_reissue,
    run_keysuri_text_and_image_reissue,
    run_keysuri_text_only_reissue,
)
from orchestrator import execute_orchestrator_run
from today_genie_reissue import (
    run_today_body_only_reissue,
    run_today_image_only_reissue,
)

from admin_notice_store import (
    NOTICE_STATUSES,
    NOTICE_TEMPLATES,
    NOTICE_TYPES,
    VISIBLE_RECIPIENT_POLICY,
    create_notice_draft,
    list_notice_page,
    load_notice,
    mark_failed,
    mark_previewed,
    mark_sent,
    validate_notice_id,
)
from admin_notice_delivery import (
    notice_recipient_source_label,
    render_notice_body_html,
    send_admin_notice_email,
)
from admin_safety_store import (
    append_operator_audit,
    list_operator_audit_page,
    safety_storage_display_path,
)
from admin_operational_status import default_operational_status_service
from memory_observability import MemoryEvidenceRecorder
from natural_run_activity import active_natural_run_snapshot

router = APIRouter(tags=["admin"])

NOTICE_SEND_CONFIRM_PHRASE = "공지 발송에 동의합니다"
NOTICE_PROGRAM_OPTIONS = (
    ("keysuri_global_tech", "KeeSuri Global Tech"),
    ("keysuri_korea_tech", "KeeSuri Korea Tech"),
    ("today_genie", "Today Genie"),
    ("all", "전체 프로그램"),
)
_NOTICE_TYPE_LABELS = {
    "delay_notice": "발송 지연 안내",
    "quality_check_notice": "품질 점검 안내",
    "resolved_notice": "지연 해소 안내",
    "incident_notice": "장애 안내",
    "custom_notice": "자유 작성",
}

ADMIN_UI_PAGE_SIZE = 50

SESSION_COOKIE = "genie_admin_session"
SESSION_SALT = b"genie-admin-session-v1"
APPROVE_NONCE_COOKIE = "genie_approve_nonce"
APPROVE_NONCE_SALT = b"genie-approve-nonce-v1"
APPROVE_NONCE_TTL_SECONDS = 900
APPROVE_NONCE_FORM_FIELD = "approve_nonce"
CUSTOMER_SEND_CONFIRM_FIELD = "customer_send_confirm"
REVIEW_WARNING_CONFIRM_FIELD = "review_warning_confirm"
APPROVAL_SNAPSHOT_FORM_FIELD = "approval_snapshot_id"
CSRF_FORM_FIELD = "csrf_token"
CSRF_SALT = b"genie-admin-csrf-v1"
REISSUE_REASON_OPTIONS_BY_SCOPE = {
    "body_only": (
        "뉴스 중복 이슈",            # DEFAULT
        "오래된 뉴스 포함",
        "관련도 낮은 뉴스 포함",
        "국내/글로벌 범위 불일치",
        "핵심 시그널 누락",
        "제목 수정 요청",
        "요약 수정 요청",
        "문장 표현 수정 요청",
    ),
    "image_only": (
        "이미지 품질 이슈",          # DEFAULT
        "인물/헤어 일관성 이슈",
        "장면/역할 불일치",
        "배경/아이콘 오염",
    ),
    "body_and_image": (
        "전체 방향 수정 요청",       # DEFAULT
        "뉴스 수집부터 재실행 필요",
        "이미지+본문 불일치",
        "구성 품질 이슈",
    ),
}
REISSUE_REASON_FALLBACKS = ("기타",)

REISSUE_SCOPE_OPTIONS = (
    ("body_only", "본문만 재발행", "중복·부적합 뉴스를 제외하고 후보군의 다음 순위 뉴스로 본문을 다시 생성합니다. 기존 이미지는 유지됩니다."),
    ("image_only", "이미지만 재발행", "이미지 prompt와 이미지 산출물만 다시 생성합니다. 본문은 유지됩니다."),
    (
        "body_and_image",
        "본문·이미지 모두 재발행",
        "뉴스 수집부터 다시 수행하고, 본문과 이미지 산출물을 모두 새로 생성합니다.",
    ),
)

_REISSUE_ERROR_MESSAGES = {
    "invalid_reissue_scope": "재발행 범위가 올바르지 않습니다.",
    "missing_reissue_scope": "재발행 범위를 선택하세요.",
    "unsupported_reissue_scope": (
        "선택한 재발행 범위는 아직 실행할 수 없습니다. "
        "화면에 표시된 실행 가능 범위를 확인하세요."
    ),
    "today_image_prompt_snapshot_missing": (
        "이 실행에는 이미지 prompt 기록이 없어 이미지만 재발행할 수 없습니다. "
        "본문·이미지 모두 재발행을 사용하세요."
    ),
}

_REISSUE_MODE_LABELS = {
    "today_genie": "Today Genie",
    "tomorrow_genie": "Tomorrow Genie",
    "keysuri_global_tech": "KeeSuri Global Tech",
    "keysuri_korea_tech": "KeeSuri Korea Tech",
}


def _reissue_mode_label(mode: str) -> str:
    mode = str(mode or "").strip()
    return _REISSUE_MODE_LABELS.get(mode, f"알 수 없는 mode({mode or '없음'})")


# Modes whose reissue paths support send_owner_email=False, so the QA dry-run
# (no owner-review send) option can be offered. tomorrow_genie is excluded: it is
# not activated for reissue execution.
_DRY_RUN_REISSUE_MODES = frozenset(
    {"keysuri_global_tech", "keysuri_korea_tech", "today_genie"}
)

# Operator-facing text for each parent-eligibility block. Keeps the reason
# actionable without echoing artifact internals onto the page.
_REISSUE_PARENT_BLOCK_MESSAGES = {
    "parent_validation_not_pass": (
        "검증을 통과하지 못한 실행은 재발행 원본으로 사용할 수 없습니다. "
        "정상 발행된 실행을 선택해 주세요."
    ),
    "parent_run_errored": (
        "오류로 종료된 실행은 재발행 원본으로 사용할 수 없습니다. "
        "정상 발행된 실행을 선택해 주세요."
    ),
    "parent_placeholder_content": (
        "원본 실행의 TOP5에 자동 생성된 임시 제목이 포함되어 있어 재발행을 차단했습니다."
    ),
    "parent_not_reissuable_dry_run": (
        "무발송 검증(dry-run) 실행은 재발행 원본으로 사용할 수 없습니다."
    ),
}

# Markers recorded on a dry-run child artifact so operators (and tests) can see
# the reissue pipeline ran without dispatching the owner-review email.
_DRY_RUN_REISSUE_META = {
    "admin_reissue_dry_run": True,
    "send_owner_email": False,
    "owner_review_email_sent": False,
    "customer_send": False,
    "approve_customer_final_send": False,
}


def _is_dry_run_no_send(raw: str) -> bool:
    return str(raw or "").strip().lower() in ("1", "true", "on", "yes")


def _apply_dry_run_reissue_metadata(child_run_id: str) -> None:
    """Record dry-run / no-send markers on the freshly created child artifact."""
    def _mut(child: Dict[str, Any]) -> None:
        child.update(_DRY_RUN_REISSUE_META)

    update_run_artifact(child_run_id, _mut)


def _render_reissue_dry_run_field(mode: str) -> str:
    """QA dry-run toggle: runs the real reissue pipeline but skips owner-review send."""
    if mode not in _DRY_RUN_REISSUE_MODES:
        return ""
    return (
        '<label style="display:block;margin:8px 0;">'
        '<input type="checkbox" name="dry_run_no_send" value="1"> '
        "QA dry-run으로 실행 — 운영자 검토(owner-review) 이메일을 발송하지 않습니다"
        "</label>"
    )


def _format_cost_usd(value: Any) -> str:
    if value is None or value == "":
        return "—"
    try:
        return f"{Decimal(str(value)):.6f}"
    except (InvalidOperation, TypeError, ValueError):
        return str(value)


def _format_image_cost_display(components: Dict[str, Any], cost: Dict[str, Any]) -> str:
    image_cost = components.get("image_cost_usd")
    if image_cost is not None:
        return _format_cost_usd(image_cost)
    model_pricing = cost.get("model_pricing") if isinstance(cost.get("model_pricing"), dict) else {}
    status = str(model_pricing.get("image_pricing_status") or "")
    usage = cost.get("usage") if isinstance(cost.get("usage"), dict) else {}
    generated = usage.get("generated_image_count") or 0
    if status == "unsupported_or_unconfigured" or generated:
        return "unknown / not calculated"
    if status == "failed_request_billing_unknown":
        return "unknown (failed request billing unavailable)"
    if status == "known_zero_paid_outputs":
        return _format_cost_usd(0)
    return "—"


def _render_cost_estimate_section(meta: Dict[str, Any]) -> str:
    cost = meta.get("cost_estimate")
    if not isinstance(cost, dict):
        return ""
    usage = cost.get("usage") if isinstance(cost.get("usage"), dict) else {}
    components = cost.get("components") if isinstance(cost.get("components"), dict) else {}
    model = cost.get("model")
    text_model = model.get("text_model") if isinstance(model, dict) else model
    image_model = model.get("image_model") if isinstance(model, dict) else ""
    text_total = components.get("text_total_cost_usd")
    if text_total is None:
        known_text = [
            components.get("text_input_cost_usd"),
            components.get("text_output_cost_usd"),
            components.get("text_thoughts_cost_usd"),
        ]
        priced = [c for c in known_text if c is not None]
        text_total = sum(priced) if priced else None
    missing = (
        "|".join(str(v) for v in cost.get("missing_price_env") or [])
        if isinstance(cost.get("missing_price_env"), list)
        else cost.get("missing_price_env")
    )
    rows = [
        ("Cost estimate status", cost.get("cost_estimate_status")),
        ("Pricing source", cost.get("pricing_source")),
        ("Price env configured", cost.get("price_env_configured")),
        ("Text model", text_model),
        ("Image model", image_model),
        ("Prompt token count", usage.get("prompt_token_count")),
        ("Candidates token count", usage.get("candidates_token_count")),
        ("Thoughts token count", usage.get("thoughts_token_count")),
        ("Paid successful image outputs", usage.get("generated_image_count")),
        ("Text input cost USD", _format_cost_usd(components.get("text_input_cost_usd"))),
        ("Text response cost USD", _format_cost_usd(components.get("text_output_cost_usd"))),
        ("Text reasoning cost USD", _format_cost_usd(components.get("text_thoughts_cost_usd"))),
        ("Text total cost USD", _format_cost_usd(text_total)),
        ("Image model list-price cost", _format_image_cost_display(components, cost)),
        ("Total AI model production cost USD", _format_cost_usd(cost.get("total_cost_usd"))),
        ("Total cost KRW (optional)", _format_cost_usd(cost.get("total_cost_krw"))),
        ("Missing price env", missing or "—"),
        ("Pricing note", cost.get("pricing_note")),
        ("Cost record path", meta.get("cost_record_path")),
        ("Cost ledger path", meta.get("cost_ledger_path")),
    ]
    row_html = "".join(f"<dt>{_esc(k)}</dt><dd>{_esc(v)}</dd>" for k, v in rows)
    month = month_from_run_meta(meta)
    return (
        '<div class="card">'
        "<h2>AI 모델 생산 원가</h2>"
        f'<dl class="meta">{row_html}</dl>'
        f'<p><a href="/admin/costs/ledger.csv?month={_esc(month)}">월별 CSV ledger 다운로드</a></p>'
        "</div>"
    )


def _render_reissue_failure_page(
    *,
    title: str,
    run_id: str,
    mode: str,
    failed_step: str,
    safe_message: str,
    status_code: int,
    dry_run: bool = False,
) -> HTMLResponse:
    """Render a reissue failure page without leaking raw exception text.

    Always shows the actual requested mode, its label, the failed step, and a
    pre-approved safe message — never a bare exception/ValueError message.
    """
    dry_run_note = (
        "<p>QA dry-run(no-send) 실행이었습니다. 운영자 검토 이메일/고객 발송 모두 수행하지 않았습니다.</p>"
        if dry_run
        else ""
    )
    inner = (
        f"<p>요청 mode: {_esc(mode or '(없음)')} ({_esc(_reissue_mode_label(mode))})</p>"
        f"<p>실패 단계: {_esc(failed_step)}</p>"
        f"<p>{_esc(safe_message)}</p>"
        f"{dry_run_note}"
        f"<p><a href=\"/admin/runs/{_esc(run_id)}\">돌아가기</a></p>"
    )
    return HTMLResponse(_layout(title, inner), status_code=status_code)


def _safe_reissue_result_error_code(raw_error: str) -> str:
    code = str(raw_error or "").strip()
    if not code:
        return "keysuri_reissue_failed"
    lowered = code.lower()
    if "gemini parse failed" in lowered or "top_5_news" in lowered:
        return "generated_briefing_contract_invalid"
    if len(code) > 80 or any(ch.isspace() for ch in code):
        return "keysuri_reissue_failed"
    return re.sub(r"[^A-Za-z0-9_.:-]", "_", code)[:80]


_APPROVE_ERROR_MESSAGES = {
    "already_approved": "이미 승인된 실행입니다.",
    "customer_already_sent": "고객 발송이 이미 완료된 실행입니다.",
    "delivery_submission_pending": "SMTP 제출이 시작된 실행입니다. 결과를 확인할 때까지 중복 발송을 차단합니다.",
    "delivery_partial_refusal": "일부 수신자는 접수되고 일부는 즉시 거절되었습니다. 중복 위험 때문에 새 발송을 차단합니다.",
    "delivery_refused_all": "모든 수신자가 즉시 거절된 기록입니다. 원인을 확인하기 전 새 발송을 차단합니다.",
    "delivery_outcome_unknown": "SMTP 제출 후 결과를 확정하지 못했습니다. 중복 위험 때문에 새 발송을 차단합니다.",
    "legacy_timeout_sent": "과거 타임아웃 자동 발송 기록입니다. 새 승인 발송은 불가합니다.",
    "missing_customer_to": "GENIE_CUSTOMER_EMAIL_TO가 설정되지 않았습니다.",
    "missing_email_html": "저장된 이메일 HTML이 없습니다.",
    "missing_smtp": "SMTP 설정이 없습니다.",
    "not_approvable": "승인할 수 없는 검증 상태입니다.",
    "keysuri_safety_not_safe": "안전성 판정이 SAFE가 아니어서 고객 발송할 수 없습니다.",
    "keysuri_editorial_poor": "편집 품질이 POOR인 후보는 고객 승인을 제공하지 않습니다.",
    "keysuri_editorial_unclassified": "편집 품질 판정이 없어 고객 발송할 수 없습니다.",
    "REVIEW_WARNING_CONFIRMATION_REQUIRED": "검토 경고를 확인한 뒤 승인해야 합니다.",
    "send_failed": "고객 이메일 발송에 실패했습니다.",
    "unsupported_mode": "승인 발송을 지원하지 않는 mode입니다.",
    "keysuri_customer_delivery_not_ready": "Kee-Suri 고객 발송은 아직 안전 검증 전입니다.",
    "missing_approval_nonce": "승인 확인 토큰이 없습니다. 승인 검토 페이지에서 다시 시도하세요.",
    "invalid_approval_nonce": "승인 확인 토큰이 유효하지 않습니다. 승인 검토 페이지에서 다시 시도하세요.",
    "approval_nonce_expired": "승인 확인 토큰이 만료되었습니다. 승인 검토 페이지에서 다시 시도하세요.",
    "missing_customer_send_confirm": "고객 이메일 발송 승인 체크박스를 선택해야 합니다.",
    "review_held": "보류된 검수입니다. 다시 검수하기로 전환한 뒤 승인하세요.",
    "INVALID_APPROVAL_SNAPSHOT": "승인 스냅샷이 없거나 위조되었습니다. 최종 확인을 다시 진행하세요.",
    "STALE_APPROVAL_SNAPSHOT": "승인 스냅샷이 만료되었습니다. 최종 확인을 다시 진행하세요.",
    "APPROVAL_TARGET_CHANGED": "확인 후 콘텐츠·이미지·수신자가 변경되었습니다. 발송하지 않았습니다. 다시 확인하세요.",
    "DUPLICATE_DELIVERY_COMMAND": "동일 발송 명령은 이미 제출되었거나 결과 확인 중입니다. 재전송하지 말고 기록을 확인하세요.",
}

def admin_password() -> str:
    return os.getenv("GENIE_ADMIN_PASSWORD", "").strip()


def admin_enabled() -> bool:
    return bool(admin_password())


def _admin_cookie_secure() -> bool:
    explicit = os.getenv("GENIE_ADMIN_COOKIE_SECURE", "").strip().lower()
    if explicit:
        return explicit not in {"0", "false", "no", "off"}
    return bool(os.getenv("K_SERVICE", "").strip())


def _csrf_enabled() -> bool:
    explicit = os.getenv("GENIE_ADMIN_CSRF_ENABLED", "").strip().lower()
    if explicit:
        return explicit not in {"0", "false", "no", "off"}
    return bool(os.getenv("K_SERVICE", "").strip())


def _session_token(password: str) -> str:
    return hmac.new(password.encode("utf-8"), SESSION_SALT, hashlib.sha256).hexdigest()


def _session_token_from_request(request: Request) -> str:
    return str(request.cookies.get(SESSION_COOKIE, "") or "")


def _operator_id(request: Request) -> str:
    token = _session_token_from_request(request)
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()[:16] if token else "anonymous"
    return f"owner_session:{digest}"


def _csrf_token(request: Request, action: str) -> str:
    session_token = _session_token_from_request(request)
    payload = f"{session_token}|{action}".encode("utf-8")
    return hmac.new(admin_password().encode("utf-8"), CSRF_SALT + payload, hashlib.sha256).hexdigest()


def _csrf_field(request: Request, action: str) -> str:
    return (
        f'<input type="hidden" name="{CSRF_FORM_FIELD}" '
        f'value="{_esc(_csrf_token(request, action))}">'
    )


def _verify_csrf(request: Request, action: str, supplied: str) -> bool:
    if not _csrf_enabled():
        return True
    if not supplied:
        return False
    return hmac.compare_digest(str(supplied), _csrf_token(request, action))


def _csrf_rejected() -> HTMLResponse:
    return HTMLResponse(
        _layout("Request blocked", '<div class="warn">CSRF 검증에 실패했습니다. 페이지를 새로 열어 다시 시도하세요.</div>'),
        status_code=403,
    )


def _sign_approval_nonce(run_id: str, nonce: str, exp: int, session_token: str) -> str:
    pwd = admin_password()
    payload = f"{session_token}|{run_id}|{nonce}|{exp}".encode("utf-8")
    return hmac.new(pwd.encode("utf-8"), APPROVE_NONCE_SALT + payload, hashlib.sha256).hexdigest()


def issue_approval_nonce(run_id: str, session_token: str) -> tuple[str, str]:
    nonce = secrets.token_urlsafe(32)
    exp = int(time.time()) + APPROVE_NONCE_TTL_SECONDS
    sig = _sign_approval_nonce(run_id, nonce, exp, session_token)
    cookie_value = f"{run_id}|{nonce}|{exp}|{sig}"
    return nonce, cookie_value


def verify_approval_nonce(
    run_id: str,
    nonce: str,
    cookie_value: str,
    session_token: str,
) -> tuple[bool, str]:
    if not str(nonce or "").strip():
        return False, "missing_approval_nonce"
    if not str(cookie_value or "").strip():
        return False, "missing_approval_nonce"
    parts = str(cookie_value).split("|", 3)
    if len(parts) != 4:
        return False, "invalid_approval_nonce"
    cookie_run_id, cookie_nonce, exp_raw, sig = parts
    if cookie_run_id != run_id or cookie_nonce != nonce:
        return False, "invalid_approval_nonce"
    try:
        exp = int(exp_raw)
    except ValueError:
        return False, "invalid_approval_nonce"
    if exp < int(time.time()):
        return False, "approval_nonce_expired"
    expected = _sign_approval_nonce(run_id, nonce, exp, session_token)
    if not hmac.compare_digest(expected, sig):
        return False, "invalid_approval_nonce"
    return True, "ok"


def _clear_approval_nonce_cookie(response: Response) -> None:
    response.delete_cookie(APPROVE_NONCE_COOKIE, path="/")


def _request_client_ip(request: Request) -> str:
    client = request.client
    return str(client.host if client and client.host else "")


def is_logged_in(request: Request) -> bool:
    pwd = admin_password()
    if not pwd:
        return False
    token = request.cookies.get(SESSION_COOKIE, "")
    if not token:
        return False
    expected = _session_token(pwd)
    return hmac.compare_digest(token, expected)


def _esc(text: object) -> str:
    return html.escape(str(text or ""), quote=True)


def _admin_list_cursor(request: Request) -> str:
    """Return a bounded opaque list cursor; each store validates its format."""
    return str(request.query_params.get("cursor") or "").strip()[:256]


def _admin_audit_cursor(request: Request) -> str:
    """Keep audit pagination independent from the run-history cursor."""
    return str(request.query_params.get("audit_cursor") or "").strip()[:256]


def _admin_pagination_controls(
    path: str,
    page: Dict[str, Any],
    *,
    preserved_query: Optional[Dict[str, str]] = None,
    cursor_param: str = "cursor",
) -> str:
    """Render one-way cursor navigation without retaining prior page payloads."""
    links = []
    if str(page.get("cursor") or ""):
        first_query = {
            key: value
            for key, value in (preserved_query or {}).items()
            if str(value or "")
        }
        first_href = path
        if first_query:
            first_href = f"{path}?{urlencode(first_query)}"
        links.append(
            f'<a class="btn btn--secondary" href="{_esc(first_href)}">최신 기록으로</a>'
        )

    next_cursor = str(page.get("next_cursor") or "")
    if bool(page.get("has_more")) and next_cursor:
        next_query = {
            key: value
            for key, value in (preserved_query or {}).items()
            if str(value or "")
        }
        next_query[cursor_param] = next_cursor
        next_href = f"{path}?{urlencode(next_query)}"
        links.append(
            f'<a class="btn btn--secondary" rel="next" href="{_esc(next_href)}">이전 기록 더 보기</a>'
        )

    if not links:
        return ""
    return f'<nav class="actions" aria-label="목록 페이지 이동">{"".join(links)}</nav>'


def _render_panel_row(label: str, value: str) -> str:
    return (
        f"<tr><th scope=\"row\" style=\"width:34%;font-weight:700;background:#f8fafc;\">{_esc(label)}</th>"
        f"<td class=\"break-long\">{_esc(value)}</td></tr>"
    )


def _render_customer_delivery_status_panel(meta: dict) -> str:
    panel = build_customer_delivery_admin_panel(meta)
    recipients = panel.get("recipients_masked") or []
    recipients_display = ", ".join(str(item) for item in recipients) if recipients else "미기록"
    image = panel.get("image") if isinstance(panel.get("image"), dict) else {}
    rows = [
        _render_panel_row("발송 상태", f"{panel.get('status_grade')} / {panel.get('status_detail')} ({panel.get('status_code')})"),
        _render_panel_row("상태 라벨", str(panel.get("status_label_ko") or "미기록")),
        _render_panel_row("발송 시각 (KST)", str(panel.get("sent_at_kst") or "미기록")),
        _render_panel_row("수신자 수", str(panel.get("recipient_count") or "미기록")),
        _render_panel_row("수신자 목록 (마스킹)", recipients_display),
        _render_panel_row("SMTP accepted", str(panel.get("smtp_accepted") or "미기록")),
        _render_panel_row("SMTP message id", str(panel.get("smtp_message_id") or "미기록")),
        _render_panel_row("실패 reason code", str(panel.get("failure_reason_code") or "없음")),
        _render_panel_row("실패 message", str(panel.get("failure_message") or "없음")),
        _render_panel_row("double-send 차단", str(panel.get("double_send_blocked") or "미기록")),
        _render_panel_row("mode", str(panel.get("mode") or "미기록")),
        _render_panel_row("run_id", str(panel.get("run_id") or "미기록")),
        _render_panel_row("subject", str(panel.get("subject") or "미기록")),
        _render_panel_row("MIME HTML sha256", str(panel.get("mime_html_sha256") or "미기록")),
        _render_panel_row("MIME HTML bytes", str(panel.get("mime_html_bytes_len") or "미기록")),
        _render_panel_row("inline image hash count", str(panel.get("inline_image_count") or "미기록")),
    ]
    image_rows = [
        _render_panel_row("Top image source", str(image.get("top_image_source") or "없음")),
        _render_panel_row("Bottom image source", str(image.get("bottom_image_source") or "없음")),
        _render_panel_row("Top image path", str(image.get("top_image_path") or "없음")),
        _render_panel_row("Bottom image path", str(image.get("bottom_image_path") or "없음")),
        _render_panel_row("Top CID present", str(image.get("top_cid_present") or "미기록")),
        _render_panel_row("Bottom CID present", str(image.get("bottom_cid_present") or "미기록")),
        _render_panel_row("Top CID", str(image.get("top_cid") or "없음")),
        _render_panel_row("Bottom CID", str(image.get("bottom_cid") or "없음")),
        _render_panel_row("MIME inline part count", str(image.get("mime_inline_part_count") or "미기록")),
        _render_panel_row("static latest used", str(image.get("static_latest_used") or "미기록")),
        _render_panel_row("generated image path used", str(image.get("generated_image_path_used") or "미기록")),
    ]
    return f"""
<div class="card">
<h2>고객 이메일 발송 상태</h2>
<p style="margin:0 0 12px 0;font-size:12px;line-height:1.6;color:#64748b;">
SMTP 접수는 메일 서버가 발송 요청을 받은 상태입니다. 실제 수신함 도착과는 다를 수 있습니다.
고객 발송은 운영자 승인 후에만 실행됩니다.
</p>
<div class="table-wrap">
<table aria-label="고객 이메일 발송 상태">
{"".join(rows)}
</table>
</div>
<h3 style="margin:20px 0 8px 0;font-size:15px;">이미지 발송 근거</h3>
<div class="table-wrap">
<table aria-label="고객 이메일 이미지 발송 근거">
{"".join(image_rows)}
</table>
</div>
</div>
"""


def _render_delivery_report_sections(meta: dict) -> str:
    owner_label = owner_review_email_label_ko(meta)
    customer_panel = _render_customer_delivery_status_panel(meta)
    return f"""
{customer_panel}
<div class="card">
<h2>운영자 검토 메일</h2>
<p style="margin:0;font-size:14px;"><strong>{_esc(owner_label)}</strong></p>
<p style="margin:8px 0 0 0;font-size:12px;color:#64748b;">고객 최종 배포와 별도입니다.</p>
</div>
"""


def _mode_supports_image_only_reissue(mode: str) -> bool:
    return str(mode or "").strip() in (
        "today_genie",
        "keysuri_global_tech",
        "keysuri_korea_tech",
    )


def _mode_supports_body_only_reissue(mode: str) -> bool:
    return str(mode or "").strip() in (
        "today_genie",
        "keysuri_global_tech",
        "keysuri_korea_tech",
    )


def _mode_supports_body_and_image_reissue(mode: str) -> bool:
    return str(mode or "").strip() in (
        "today_genie",
        "tomorrow_genie",
        "keysuri_global_tech",
        "keysuri_korea_tech",
    )


def _today_run_supports_image_only_reissue(meta: Optional[Dict[str, Any]]) -> bool:
    """Today image_only needs the run's stored image prompts (no text regeneration)."""
    if not isinstance(meta, dict):
        return True
    return isinstance(meta.get(TODAY_IMAGE_REGEN_INPUTS_KEY), dict) and bool(
        meta.get(TODAY_IMAGE_REGEN_INPUTS_KEY)
    )


def _render_reissue_scope_field(mode: str, meta: Optional[Dict[str, Any]] = None) -> str:
    mode = str(mode or "").strip()
    body_only_enabled = _mode_supports_body_only_reissue(mode)
    image_only_enabled = _mode_supports_image_only_reissue(mode)
    body_and_image_enabled = _mode_supports_body_and_image_reissue(mode)
    image_only_unavailable_helper = "이 실행 mode에서는 아직 지원하지 않습니다."
    if (
        image_only_enabled
        and mode == "today_genie"
        and not _today_run_supports_image_only_reissue(meta)
    ):
        image_only_enabled = False
        image_only_unavailable_helper = (
            "이 실행에는 이미지 prompt 기록이 없어 본문 재생성 없이 이미지만 다시 만들 수 없습니다. "
            "본문·이미지 모두 재발행을 사용하세요."
        )
    # No image_only fallback: always default to the full (body_and_image)
    # scope regardless of which partial scopes are available, so a partial
    # reissue is always an explicit operator choice, never a pre-selected default.
    default_scope = EXECUTABLE_REISSUE_SCOPE
    rows = [
        '<p style="margin:0 0 12px 0;font-size:12px;line-height:1.6;color:#9a3412;">'
        "선택한 범위만 서버에서 재발행합니다. 재발행 결과는 운영자 검토용 이메일로만 발송되며, 고객 최종 발송은 별도 승인 전까지 수행되지 않습니다."
        "</p>"
    ]
    for scope, label, helper in REISSUE_SCOPE_OPTIONS:
        scope_helper = helper
        disabled = False
        if scope == "body_only" and not body_only_enabled:
            disabled = True
            scope_helper = "이 실행 mode에서는 아직 지원하지 않습니다."
        elif scope == "image_only" and not image_only_enabled:
            disabled = True
            scope_helper = image_only_unavailable_helper
        elif scope == "body_and_image" and not body_and_image_enabled:
            disabled = True
            scope_helper = "이 실행 mode에서는 아직 지원하지 않습니다."
        checked = " checked" if scope == default_scope and not disabled else ""
        disabled_attr = " disabled" if disabled else ""
        disabled_class = " radio-scope--disabled" if disabled else ""
        rows.append(
            f"<label class=\"radio-scope{disabled_class}\">"
            f"<span class=\"radio-scope__control\">"
            f"<input type=\"radio\" name=\"reissue_scope\" value=\"{_esc(scope)}\" required"
            f"{checked}{disabled_attr}>"
            f"</span>"
            f"<span class=\"radio-scope__body\">"
            f"<strong>{_esc(label)}</strong>"
            f"<span class=\"radio-helper\">{_esc(scope_helper)}</span>"
            f"</span></label>"
        )
    return "\n".join(rows)


def _ordered_reissue_reasons_for_mode(mode: str) -> tuple[str, ...]:
    mode = str(mode or "").strip()
    if mode in ("keysuri_global_tech", "keysuri_korea_tech"):
        ordered: list[str] = []
        for scope in ("image_only", "body_only", "body_and_image"):
            for reason in REISSUE_REASON_OPTIONS_BY_SCOPE.get(scope, ()):
                if reason not in ordered:
                    ordered.append(reason)
        for reason in REISSUE_REASON_FALLBACKS:
            if reason not in ordered:
                ordered.append(reason)
        return tuple(ordered)
    ordered = list(REISSUE_REASON_OPTIONS_BY_SCOPE["body_and_image"])
    for reason in (
        "제목 수정 요청",
        "요약 수정 요청",
        "문장 표현 수정 요청",
        "이미지 품질 이슈",
        *REISSUE_REASON_FALLBACKS,
    ):
        if reason not in ordered:
            ordered.append(reason)
    return tuple(ordered)


def _render_reissue_reason_select(mode: str) -> str:
    options = _ordered_reissue_reasons_for_mode(mode)
    options_html = "".join(
        f'<option value="{_esc(reason)}">{_esc(reason)}</option>'
        for reason in options
    )
    reason_map = {
        scope: list(REISSUE_REASON_OPTIONS_BY_SCOPE.get(scope, ()))
        for scope, _label, _helper in REISSUE_SCOPE_OPTIONS
    }
    reason_map["fallback"] = list(REISSUE_REASON_FALLBACKS)
    return f"""
<select id="reissue-reason-select" name="reason_option" required>{options_html}</select>
<script>
(() => {{
  const form = document.currentScript && document.currentScript.closest("form");
  if (!form) return;
  const select = form.querySelector("#reissue-reason-select");
  const radios = Array.from(form.querySelectorAll('input[name="reissue_scope"]'));
  const reasonMap = {html.escape(json.dumps(reason_map), quote=False)};
  const defaultReason = (scope) => {{
    const choices = reasonMap[scope] || reasonMap.fallback || [];
    return choices[0] || "";
  }};
  const syncReason = () => {{
    const checked = radios.find((radio) => radio.checked);
    if (!checked || !select) return;
    const next = defaultReason(checked.value);
    if (next) select.value = next;
  }};
  radios.forEach((radio) => radio.addEventListener("change", syncReason));
  syncReason();
}})();
</script>
"""


def _admin_disabled_response() -> HTMLResponse:
    body = """
<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Genie Admin</title></head>
<body style="font-family:system-ui,sans-serif;margin:0;padding:16px 12px;max-width:640px;overflow-wrap:anywhere;">
<h1>Genie Owner Admin</h1>
<p>관리자 기능이 비활성화되어 있습니다. <code>GENIE_ADMIN_PASSWORD</code> 환경 변수를 설정하세요.</p>
</body></html>
"""
    return HTMLResponse(body, status_code=503)


def _require_admin(request: Request) -> Optional[HTMLResponse]:
    if not admin_enabled():
        return _admin_disabled_response()
    return None


def _require_login(request: Request) -> Optional[RedirectResponse]:
    gate = _require_admin(request)
    if gate is not None:
        return gate  # type: ignore[return-value]
    if not is_logged_in(request):
        return RedirectResponse(url="/admin", status_code=303)
    return None


def _layout(title: str, inner: str, *, active: str = "", authenticated: bool = True) -> str:
    return _ui_layout(title, inner, active=active, authenticated=authenticated)


def _begin_heavy_admin_projection(
    *, title: str, active: str
) -> tuple[MemoryEvidenceRecorder, Optional[HTMLResponse]]:
    """Start a bounded list projection or defer it during same-instance natural work."""
    recorder = MemoryEvidenceRecorder()
    recorder.record("route_start")
    snapshot = active_natural_run_snapshot()
    if not snapshot.get("active"):
        return recorder, None
    recorder.record("after_projection")
    programs = ", ".join(snapshot.get("program_ids") or []) or "natural_scheduled"
    inner = f"""
{_ui_page_header('잠시 후 다시 확인해 주세요', '자연 실행과 같은 인스턴스에서 큰 운영 화면을 동시에 만들지 않습니다.', 'NATURAL RUN ACTIVE')}
<div class="notice"><strong>브리핑 자연 실행 진행 중</strong><p>{_esc(programs)} 실행이 끝나면 이 화면의 최신 목록을 다시 불러올 수 있습니다. 로그인과 서비스 상태 확인은 계속 사용할 수 있습니다.</p></div>
"""
    page = _layout(title, inner, active=active)
    recorder.record("after_template")
    response = HTMLResponse(
        page,
        status_code=200,
        headers={"Retry-After": "30", "X-Genie-Admin-Projection": "deferred"},
    )
    recorder.record("route_end")
    return recorder, response


def _finish_heavy_admin_projection(
    recorder: MemoryEvidenceRecorder,
    *,
    title: str,
    inner: str,
    active: str,
) -> HTMLResponse:
    page = _layout(title, inner, active=active)
    recorder.record("after_template")
    response = HTMLResponse(page)
    recorder.record("route_end")
    return response


@router.get("/admin", response_class=HTMLResponse)
def admin_home(request: Request):
    gate = _require_admin(request)
    if gate is not None:
        return gate
    if is_logged_in(request):
        return RedirectResponse(url="/admin/operations", status_code=303)
    inner = """
<h1>Genie Owner Admin</h1>
<p>운영자 검토용 관리 페이지입니다. 고객 배포용이 아닙니다.</p>
<div class="card">
<form method="post" action="/admin/login">
<label>비밀번호<br><input type="password" name="password" required autocomplete="current-password"></label><br><br>
<div class="form-actions"><button class="btn" type="submit">로그인</button></div>
</form>
</div>
"""
    return HTMLResponse(_layout("Genie Admin Login", inner, authenticated=False))


@router.post("/admin/login")
def admin_login(request: Request, password: str = Form(...)) -> Response:
    gate = _require_admin(request)
    if gate is not None:
        return gate
    pwd = admin_password()
    if not pwd or not hmac.compare_digest(password, pwd):
        inner = """
<h1>Genie Owner Admin</h1>
<p style="color:#b91c1c;">비밀번호가 올바르지 않습니다.</p>
<div class="card">
<form method="post" action="/admin/login">
<label>비밀번호<br><input type="password" name="password" required autocomplete="current-password"></label><br><br>
<div class="form-actions"><button class="btn" type="submit">로그인</button></div>
</form>
</div>
"""
        return HTMLResponse(_layout("Login failed", inner, authenticated=False), status_code=401)
    resp = RedirectResponse(url="/admin/operations", status_code=303)
    resp.set_cookie(
        SESSION_COOKIE,
        _session_token(pwd),
        httponly=True,
        secure=_admin_cookie_secure(),
        samesite="lax",
        max_age=7 * 86400,
        path="/",
    )
    return resp


@router.post("/admin/logout")
def admin_logout() -> RedirectResponse:
    resp = RedirectResponse(url="/admin", status_code=303)
    resp.delete_cookie(SESSION_COOKIE, path="/")
    _clear_approval_nonce_cookie(resp)
    return resp


def _current_recipient_count() -> tuple[int, bool]:
    """Return current resolved recipient count and whether its source loaded cleanly."""
    try:
        resolved = resolve_customer_recipients()
    except Exception:  # read projection must fail visibly, never break Admin
        return 0, False
    recipients = resolved.get("final_recipients")
    return (len(recipients) if isinstance(recipients, list) else 0, bool(resolved.get("admin_config_ok", True)))


def _run_card(meta: Dict[str, Any], *, recipient_count: int, action_label: str = "검수하기") -> str:
    view = run_projection(meta, current_recipient_count=recipient_count)
    delivery = view["delivery"]
    return f"""
<article class="run-card">
  <div class="run-card__top">
    <div><p class="eyebrow">{_esc(view['program']['display'])}</p><h3>{_esc(view['subject'])}</h3></div>
    {_ui_badge(view['state']['label'], view['state']['tone'])}
  </div>
  <div class="run-card__meta"><span>{_esc(view['time'])}</span><span>{_esc(view['origin'])}</span><span>{_esc(view['validation']['label'])}</span></div>
  <p class="run-card__flow">{_esc(delivery['flow'])}</p>
  <p style="color:var(--muted);margin:4px 0 14px;">{_esc(delivery['summary'])}</p>
  <a class="btn btn--secondary" href="/admin/runs/{_esc(view['run_id'])}">{_esc(action_label)}</a>
</article>
"""


def _admin_email_preview_for_run(
    run_id: str,
    *,
    title: str = "고객에게 보이는 브리핑",
    approval_snapshot_id: str = "",
) -> str:
    """Point at the bounded preview route; never duplicate HTML in ``srcdoc``."""
    url = f"/admin/runs/{run_id}/email"
    if approval_snapshot_id:
        url += f"?approval_snapshot_id={approval_snapshot_id}"
    return _ui_email_preview(url, title=title)


@router.get("/admin/operations", response_class=HTMLResponse)
def admin_operations(request: Request):
    need = _require_login(request)
    if need is not None:
        return need
    memory, deferred = _begin_heavy_admin_projection(
        title="Operations", active="operations"
    )
    if deferred is not None:
        return deferred
    from natural_run_incident_store import list_incidents
    from natural_run_reliability import load_readiness

    runs = [meta for meta in list_run_artifacts(limit=100) if is_active_program(meta)]
    incidents = list_incidents(limit=50)
    recipient_count, recipients_ok = _current_recipient_count()
    latest = latest_by_program(runs)
    review_projection = review_actionability_projection(runs)
    review_runs = list(review_projection["current"])
    incident_rows = [item for item in incidents if str(item.get("program_id") or "") in ACTIVE_PROGRAM_IDS]
    open_incidents = list(incident_current_projection(incident_rows, runs)["current"])
    action_items = "".join(
        f"""
<div class="action-card">
  <div><strong>{_esc(run_projection(meta)['program']['display'])} 브리핑 검수 필요</strong>
  <p>{_esc(run_projection(meta)['time'])} · 고객 발송 전 owner 결정이 필요합니다.</p></div>
  <a class="btn" href="/admin/runs/{_esc(meta.get('run_id'))}">검수하기</a>
</div>"""
        for meta in review_runs[:5]
    )
    if not action_items:
        action_items = _ui_empty_state("대기 중인 검수 없음", "현재 저장된 근거에서 즉시 필요한 owner 검수는 없습니다.")
    incident_items = "".join(
        f"""
<div class="action-card" style="border-left-color:var(--red);">
  <div><strong>{_esc(incident_projection(item)['program']['display'])} 장애 확인 필요</strong>
  <p>{_esc(incident_projection(item)['customer_impact'])} · {_esc(incident_projection(item)['current'])}</p></div>
  <a class="btn btn--danger" href="/admin/incidents/{_esc(item.get('incident_id'))}">안전한 다음 행동 확인</a>
</div>"""
        for item in open_incidents[:5]
    )
    if not incident_items:
        incident_items = _ui_empty_state("열린 장애 없음", "현재 저장된 장애 기록에서 owner 개입이 필요한 항목이 없습니다.")

    cards = []
    for program in ACTIVE_PROGRAMS:
        pid = program["id"]
        meta = latest.get(pid)
        readiness = load_readiness(pid) or {}
        preflight = str(readiness.get("status") or "NOT RUN")
        if meta:
            view = run_projection(meta, current_recipient_count=recipient_count)
            state = view["state"]
            latest_line = f"최근 {view['time']} · {view['origin']}"
            href = f"/admin/runs/{_esc(view['run_id'])}"
        else:
            state = {"label": "실행 전", "tone": "neutral", "impact": "최근 실행 근거가 없습니다.", "action": "시스템 상태 보기"}
            latest_line = "최근 실행 없음"
            href = "/admin/system"
        cards.append(f"""
<article class="program-card">
  <div class="program-card__top"><div><p class="eyebrow">{_esc(program['display'])}</p><h2>{_esc(program['name'])}</h2>
  <p class="program-card__time">자연 실행 {program['natural_time']} · Preflight {program['preflight_time']}</p></div>
  {_ui_badge(preflight_projection(readiness, program)['label'], 'good' if preflight_projection(readiness, program)['state'] == 'pass' else 'warn' if preflight_projection(readiness, program)['state'] != 'not_yet_run' else 'neutral')}</div>
  <p class="program-card__state">{_esc(state['label'])}</p><p class="program-card__impact">{_esc(state['impact'])}</p>
  <div class="program-card__footer"><span>{_esc(latest_line)}</span><a href="{href}">{_esc(state['action'])}</a></div>
</article>""")

    recipient_note = "현재 수신자 설정을 정상적으로 읽었습니다." if recipients_ok else "수신자 설정 근거를 읽지 못했습니다. 발송 전 재확인이 필요합니다."
    memory.record("after_projection")
    inner = f"""
{_ui_page_header('오늘의 운영', '세 프로그램의 현재 상태와 owner가 지금 해야 할 일만 먼저 보여줍니다.')}
<div class="metrics">
  {_ui_metric('검수 필요', len(review_runs), '현재 실행')}
  {_ui_metric('열린 장애', len(open_incidents), '건')}
  {_ui_metric('현재 수신자', recipient_count if recipients_ok else '확인 필요', '명')}
  {_ui_metric('활성 프로그램', 3, 'Today · Global · Korea')}
</div>
<div class="section-heading"><div><p class="eyebrow">ACTION</p><h2>내 결정이 필요합니다</h2></div></div>
<div class="stack">{action_items}</div>
<div class="section-heading"><div><p class="eyebrow">INCIDENTS</p><h2>장애와 경고</h2></div></div>
<div class="stack">{incident_items}</div>
<div class="section-heading"><div><p class="eyebrow">PROGRAMS</p><h2>오늘의 프로그램</h2></div><span class="evidence-label">{_esc(recipient_note)}</span></div>
<div class="card-grid">{''.join(cards)}</div>
"""
    return _finish_heavy_admin_projection(
        memory, title="Operations", inner=inner, active="operations"
    )


@router.get("/admin/reviews", response_class=HTMLResponse)
def admin_review_queue(request: Request):
    need = _require_login(request)
    if need is not None:
        return need
    memory, deferred = _begin_heavy_admin_projection(
        title="Review Queue", active="reviews"
    )
    if deferred is not None:
        return deferred
    recipient_count, recipients_ok = _current_recipient_count()
    page = list_run_artifact_page(
        limit=ADMIN_UI_PAGE_SIZE,
        cursor=_admin_list_cursor(request),
    )
    runs = [meta for meta in page["items"] if is_active_program(meta)]
    if str(page.get("cursor") or ""):
        # Older cursor pages are evidence-only. A superseding child can live on
        # a newer page, so an old parent must never regain an actionable CTA
        # merely because the child is outside this page's bounded window.
        queue = {
            "current": (),
            "delivery_attention": (),
            "historical_unresolved": tuple(runs),
        }
    else:
        queue = review_actionability_projection(runs)
    current_cards = "".join(_run_card(dict(meta), recipient_count=recipient_count) for meta in queue["current"])
    if not current_cards:
        current_cards = _ui_empty_state("현재 검수 대기 없음", "오늘의 안전한 owner 결정 대기 브리핑이 없습니다.")
    delivery_cards = "".join(_run_card(dict(meta), recipient_count=recipient_count, action_label="발송 근거 보기") for meta in queue["delivery_attention"])
    historical_cards = "".join(_run_card(dict(meta), recipient_count=recipient_count, action_label="기록 확인") for meta in queue["historical_unresolved"])
    source_note = f"현재 수신자 {recipient_count}명" if recipients_ok else "수신자 설정 확인 필요"
    memory.record("after_projection")
    inner = f"""
{_ui_page_header('검수함', '현재 owner 결정과 발송 결과 확인을 구분합니다. 과거 원본은 변경하지 않습니다.', 'REVIEW QUEUE')}
<div class="section-heading"><div><h2>내 결정이 필요합니다</h2></div><span class="evidence-label">{_esc(source_note)}</span></div>
<div class="stack">{current_cards}</div>
<div class="section-heading"><div><h2>발송 결과 확인 필요</h2></div></div>
<div class="stack">{delivery_cards or _ui_empty_state('확인할 발송 결과 없음','일부 거절 또는 결과 미확정 기록이 없습니다.')}</div>
<details class="technical-details"><summary>과거 미처리 · 확인 필요 ({len(queue['historical_unresolved'])})</summary><div class="technical-details__body"><p>후속 실행이나 고객 발송으로 대체되었다는 근거가 없는 과거 항목입니다. 현재 고객 발송 결정으로 취급하지 않습니다.</p><div class="stack">{historical_cards or _ui_empty_state('과거 미처리 없음','확인할 과거 검수 기록이 없습니다.')}</div></div></details>
{_admin_pagination_controls('/admin/reviews', page)}
"""
    return _finish_heavy_admin_projection(
        memory, title="Review Queue", inner=inner, active="reviews"
    )


@router.get("/admin/delivery", response_class=HTMLResponse)
def admin_delivery(request: Request):
    need = _require_login(request)
    if need is not None:
        return need
    memory, deferred = _begin_heavy_admin_projection(
        title="Delivery", active="delivery"
    )
    if deferred is not None:
        return deferred
    page = list_run_artifact_page(
        limit=ADMIN_UI_PAGE_SIZE,
        cursor=_admin_list_cursor(request),
    )
    runs = [meta for meta in page["items"] if is_active_program(meta)]
    rows = []
    for meta in runs:
        view = run_projection(meta)
        delivery = view["delivery"]
        counts = []
        if delivery.get("accepted") is not None:
            counts.append(f"접수 {delivery['accepted']}명")
        if delivery.get("refused") is not None:
            counts.append(f"거절 {delivery['refused']}명")
        count_line = " · ".join(counts) or "접수/거절 인원 근거 없음"
        rows.append(f"""
<article class="run-card">
  <div class="run-card__top"><div><p class="eyebrow">{_esc(view['program']['display'])}</p><h3>{_esc(view['subject'])}</h3></div>{_ui_badge(delivery['label'], delivery['tone'])}</div>
  <div class="run-card__meta"><span>{_esc(view['time'])}</span><span>{_esc(count_line)}</span></div>
  <p class="run-card__flow">{_esc(delivery['summary'])}</p>
  <p style="color:var(--muted);">Provider acceptance는 수신함 도착 확인이 아닙니다.</p>
  <a class="btn btn--secondary" href="/admin/runs/{_esc(view['run_id'])}">발송 근거 보기</a>
</article>""")
    memory.record("after_projection")
    inner = f"""
{_ui_page_header('발송', 'SMTP가 남긴 근거만 표시합니다. 실제 수신함 도착을 추정하지 않습니다.', 'DELIVERY EVIDENCE')}
<div class="stack">{''.join(rows) if rows else _ui_empty_state('발송 기록 없음','현재 확인 가능한 고객 발송 기록이 없습니다.')}</div>
{_admin_pagination_controls('/admin/delivery', page)}
"""
    return _finish_heavy_admin_projection(
        memory, title="Delivery", inner=inner, active="delivery"
    )


@router.get("/admin/system", response_class=HTMLResponse)
def admin_system(request: Request):
    need = _require_login(request)
    if need is not None:
        return need
    memory, deferred = _begin_heavy_admin_projection(
        title="System", active="system"
    )
    if deferred is not None:
        return deferred
    from natural_run_reliability import load_readiness

    latest = latest_by_program(list_run_artifacts(limit=100))
    recent_evidence = {program["id"]: (load_readiness(program["id"]) or {}) for program in ACTIVE_PROGRAMS}
    status = default_operational_status_service().status(recent_evidence=recent_evidence)
    status_by_program = {row["program_id"]: row for row in status["programs"]}
    cards = []
    for program in ACTIVE_PROGRAMS:
        operational = status_by_program[program["id"]]
        meta = latest.get(program["id"])
        latest_result = run_projection(meta)["state"]["label"] if meta else "최근 실행 없음"
        latest_delivery = run_projection(meta)["delivery"]["label_ko"] if meta else "근거 없음"
        readiness = recent_evidence.get(program["id"]) or {}
        preflight = preflight_projection(readiness, program)
        provenance = str(operational["provenance"])
        scheduler_live = provenance == "LIVE"
        provenance_ko = "현재 확인됨" if scheduler_live else "확인 불가"
        scheduler_state = scheduler_label(operational.get("state") if scheduler_live else "UNAVAILABLE")
        scheduler_helper = provenance_ko if scheduler_live else "사전점검 근거와 별도"
        cards.append(f"""
<article class="program-card"><p class="eyebrow">{_esc(program['display'])}</p><h2>{_esc(program['name'])}</h2>{_ui_badge(provenance_ko, 'good' if provenance == 'LIVE' else ('warn' if provenance == 'RECENT EVIDENCE' else 'danger'))}
<div class="metrics" style="grid-template-columns:1fr;margin-top:16px;">
{_ui_metric('Scheduler 상태', scheduler_state, scheduler_helper)}
{_ui_metric('자연 실행', f"평일 {program['natural_time']} KST", operational.get('schedule') or '저장된 일정')}
{_ui_metric('오늘 사전점검', preflight['label'], preflight['detail'])}
{_ui_metric('최근 실행 결과', latest_result, run_projection(meta)['time'] if meta else '근거 없음')}
{_ui_metric('최근 고객 발송', latest_delivery, run_projection(meta)['delivery']['summary'] if meta else '근거 없음')}
</div>{_ui_technical_details(dict(operational), (('Scheduler provenance', provenance), ('Scheduler state raw', operational.get('state')), ('Scheduler schedule raw', operational.get('schedule')), ('Scheduler last attempt ISO', operational.get('last_attempt')), ('Preflight provenance', preflight['provenance']), ('Preflight evidence ISO', readiness.get('checked_at') or readiness.get('finished_at'))))}</article>""")
    cloud_run = status["cloud_run"]
    memory.record("after_projection")
    inner = f"""
{_ui_page_header('시스템 상태', '읽기 전용 근거에서 Scheduler, 사전점검, 최근 실행과 발송을 각각 보여줍니다.', 'READ-ONLY OPERATIONAL TRUTH')}
<div class="notice">현재 확인됨은 Cloud API 응답, 최근 확인됨은 저장된 근거, 확인 불가는 현재 조회 불가를 뜻합니다. Scheduler 조회 실패가 사전점검 미실행을 뜻하지는 않습니다. 이 화면에는 pause·resume·run-now·deploy 권한이 없습니다.</div>
<div class="card-grid" style="margin-top:14px;">{''.join(cards)}</div>
<div class="section-heading"><div><p class="eyebrow">PRODUCTION</p><h2>런타임 식별</h2></div></div>
<div class="metrics">{_ui_metric('근거 출처',{'LIVE':'현재 확인됨','RECENT EVIDENCE':'최근 확인됨','UNAVAILABLE':'확인 불가'}.get(cloud_run['provenance'],cloud_run['provenance']))}{_ui_metric('상태',cloud_run.get('health') or '확인 불가')}{_ui_metric('Revision',cloud_run.get('serving_revision') or '확인 불가')}{_ui_metric('Commit SHA',cloud_run.get('commit_sha') or '확인 불가')}</div>
"""
    return _finish_heavy_admin_projection(
        memory, title="System", inner=inner, active="system"
    )


@router.get("/admin/settings", response_class=HTMLResponse)
def admin_settings(request: Request):
    need = _require_login(request)
    if need is not None:
        return need
    items = (
        ("베타 고객 수신자 관리", "고객 발송 대상 설정", "/admin/customer-recipients"),
        ("비용 ledger", "실행 비용과 CSV", "/admin/costs"),
        ("공지 메일 관리", "공지 작성·미리보기·발송", "/admin/notices"),
    )
    cards = "".join(
        f'<article class="program-card"><h2>{_esc(title)}</h2><p class="program-card__impact">{_esc(desc)}</p><a class="btn btn--secondary" href="{href}">열기</a></article>'
        for title, desc, href in items
    )
    inner = f"""
{_ui_page_header('설정', '매일 사용하지 않는 수신자·비용·공지 도구입니다.', 'SETTINGS & UTILITIES')}
<div class="card-grid">{cards}</div>
<div class="surface" style="margin-top:14px;"><h2>보안과 세션</h2><p style="color:var(--muted);">이 Admin은 customer 인증과 분리된 owner 전용 비밀번호 세션을 사용합니다. 고객 계정은 이 화면에 접근할 수 없습니다.</p></div>
"""
    return HTMLResponse(_layout("Settings", inner, active="settings"))


def _history_page(request: Request) -> HTMLResponse:
    memory, deferred = _begin_heavy_admin_projection(
        title="History", active="history"
    )
    if deferred is not None:
        return deferred
    mode_filter = str(request.query_params.get("program") or "").strip()
    state_filter = str(request.query_params.get("state") or "").strip()
    date_filter = str(request.query_params.get("date") or "").strip()
    recipient_count, _ = _current_recipient_count()
    page = list_run_artifact_page(
        limit=ADMIN_UI_PAGE_SIZE,
        cursor=_admin_list_cursor(request),
    )
    runs = [meta for meta in page["items"] if is_active_program(meta)]
    if mode_filter in ACTIVE_PROGRAM_IDS:
        runs = [
            meta
            for meta in runs
            if run_projection(meta)["program"]["id"] == mode_filter
        ]
    if date_filter:
        runs = [meta for meta in runs if date_filter.replace("-", ".") in run_projection(meta)["date"]]
    if state_filter:
        def _matches(meta: Dict[str, Any]) -> bool:
            view = run_projection(meta)
            if state_filter == "normal":
                return view["validation"]["tone"] == "good" and view["delivery"]["label"] == "NOT SENT"
            if state_filter == "review":
                return needs_review(meta)
            if state_filter == "incident":
                return view["validation"]["tone"] == "danger"
            if state_filter == "sent":
                return view["delivery"]["label"] in {"SMTP SUBMITTED", "PARTIAL DELIVERY"}
            return True
        runs = [meta for meta in runs if _matches(meta)]
    groups: Dict[str, list[Dict[str, Any]]] = {}
    for meta in runs:
        view = run_projection(meta, current_recipient_count=recipient_count)
        groups.setdefault(view["date"], []).append(meta)
    group_html = []
    for date, items in groups.items():
        cards = "".join(_run_card(meta, recipient_count=recipient_count, action_label="기록 보기") for meta in items)
        group_html.append(f'<section><div class="section-heading"><h2>{_esc(date)}</h2></div><div class="stack">{cards}</div></section>')
    options = "".join(f'<option value="{p["id"]}"{" selected" if mode_filter == p["id"] else ""}>{p["display"]}</option>' for p in ACTIVE_PROGRAMS)
    state_options = "".join(
        f'<option value="{value}"{" selected" if state_filter == value else ""}>{label}</option>'
        for value, label in (("", "전체"), ("normal", "정상"), ("review", "검수 필요"), ("incident", "장애"), ("sent", "발송 완료"))
    )
    audit_page = list_operator_audit_page(
        limit=ADMIN_UI_PAGE_SIZE,
        cursor=_admin_audit_cursor(request),
    )
    audit_rows = "".join(
        f'<tr><td>{_esc(row.get("timestamp"))}</td><td>{_esc(row.get("action"))}</td><td>{_esc(row.get("run_id") or row.get("incident_id") or "-")}</td><td>{_esc(row.get("result") or row.get("reason_code") or "-")}</td></tr>'
        for row in audit_page["items"]
    ) or '<tr><td colspan="4">저장된 operator action이 없습니다.</td></tr>'
    memory.record("after_projection")
    inner = f"""
{_ui_page_header('실행 이력', '날짜별로 자연 실행, 복구, 재발행과 고객 발송 흐름을 봅니다.', 'HISTORY')}
<form method="get" action="/admin/history" class="surface form-grid history-filter">
<label>프로그램<select name="program"><option value="">전체</option>{options}</select></label>
<label>상태<select name="state">{state_options}</select></label>
<label>날짜<input type="date" name="date" value="{_esc(date_filter)}"></label>
<button class="btn" type="submit">필터 적용</button></form>
{''.join(group_html) if group_html else _ui_empty_state('조건에 맞는 이력 없음','필터를 바꾸거나 새 실행 기록을 기다리세요.')}
{_admin_pagination_controls(str(request.url.path), page, preserved_query={'program': mode_filter, 'state': state_filter, 'date': date_filter})}
<details class="technical-details"><summary>Operator action audit</summary><div class="technical-details__body"><p>저장소: {_esc(safety_storage_display_path())}</p><div class="table-wrap"><table><thead><tr><th>시각</th><th>행동</th><th>대상</th><th>결과</th></tr></thead><tbody>{audit_rows}</tbody></table></div>{_admin_pagination_controls(str(request.url.path), audit_page, preserved_query={'program': mode_filter, 'state': state_filter, 'date': date_filter, 'cursor': str(page.get('cursor') or '')}, cursor_param='audit_cursor')}</div></details>
<nav class="surface" aria-label="운영 보조 메뉴" style="margin-top:18px;display:flex;flex-wrap:wrap;gap:12px 18px;">
<a href="/admin/notices">고객 공지 메일</a><a href="/admin/customer-recipients">베타 고객 수신자 관리</a><a href="/admin/costs">비용 ledger</a></nav>
"""
    return _finish_heavy_admin_projection(
        memory, title="History", inner=inner, active="history"
    )


@router.get("/admin/history", response_class=HTMLResponse)
def admin_history(request: Request):
    need = _require_login(request)
    if need is not None:
        return need
    return _history_page(request)


@router.get("/admin/runs", response_class=HTMLResponse)
def admin_runs_list(request: Request):
    need = _require_login(request)
    if need is not None:
        return need
    return _history_page(request)


_SERVICE_HEALTH_TONE = {"HEALTHY": "success", "DEGRADED": "warn", "INCIDENT": "danger"}
_CONTENT_STATUS_LABELS = {
    "ready": "고객 발송 가능",
    "quality_degraded": "품질 미달 — 고객 발송 불가",
    "unusable": "발행 본문 없음",
    "missing": "예정 실행 기록 없음",
}
_NOTICE_STATE_LABELS = {
    "not_required": "불필요",
    "recommended": "권장",
    "required": "필요",
    "sent": "발송됨",
}


def _program_service_state_cards(runs, incidents) -> dict:
    """One card per program, from the canonical service state.

    The incident store alone cannot answer "is today's briefing customer-ready":
    a run that produced an unreadable surface still completes without writing an
    incident, which is how a degraded Global slot read as "현재 장애 없음".
    """
    from admin_view_models import ACTIVE_PROGRAMS, latest_by_program
    from service_state import DEGRADED, HEALTHY, INCIDENT, derive_service_state

    try:
        from admin_notice_store import list_notices

        notices = list_notices(limit=20)
    except Exception:  # noqa: BLE001 - notice history is advisory here.
        notices = []

    latest = latest_by_program(runs)
    incident_by_program = {}
    for item in incidents or []:
        pid = str(item.get("program_id") or "")
        if pid and pid not in incident_by_program:
            incident_by_program[pid] = item

    cards = []
    unhealthy = 0
    for program in ACTIVE_PROGRAMS:
        pid = program["id"]
        state = derive_service_state(
            latest.get(pid),
            program=program,
            incident=incident_by_program.get(pid),
            notices=notices,
        )
        if state["service_health"] != HEALTHY:
            unhealthy += 1
        action = state["owner_next_action"]
        action_html = ""
        if action.get("href"):
            action_html = (
                f'<div class="actions"><a class="btn" href="{_esc(action["href"])}">'
                f'{_esc(action["label"])}</a></div>'
            )
        else:
            action_html = f'<p class="page-description">{_esc(action["label"])}</p>'
        notice_html = ""
        # The next action may already be the notice; offering it twice reads as
        # two different actions on a phone, where they stack.
        if action.get("kind") != "notice" and state["customer_notice_state"] in {
            "recommended",
            "required",
        }:
            notice_html = (
                '<div class="actions" style="margin-top:8px;">'
                f'<a class="btn btn--secondary" href="/admin/notices/new?program_id={_esc(pid)}">'
                "고객 공지 작성</a></div>"
            )
        reasons = "".join(f"<li>{_esc(r)}</li>" for r in state["reasons"][:4])
        cards.append(f"""
<article class="run-card">
  <div class="run-card__top"><div><p class="eyebrow">{_esc(state['program_display'])} · {_esc(state['scheduled_time'])}</p>
  <h3>{_esc(state['program_name'])}</h3></div>{_ui_badge(state['service_health'], _SERVICE_HEALTH_TONE.get(state['service_health'], 'neutral'))}</div>
  <div class="metrics" style="margin:14px 0;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));">
    {_ui_metric('콘텐츠 상태', _CONTENT_STATUS_LABELS.get(state['content_status'], state['content_status']))}
    {_ui_metric('고객 발송 가능', '예' if state['customer_ready'] else '아니오')}
    {_ui_metric('고객 공지', _NOTICE_STATE_LABELS.get(state['customer_notice_state'], state['customer_notice_state']))}
  </div>
  {f'<ul class="page-description">{reasons}</ul>' if reasons else ''}
  {action_html}{notice_html}
</article>""")

    if unhealthy:
        empty = _ui_empty_state(
            "장애 기록은 없음",
            "장애 기록은 없지만 위 프로그램 상태에 고객 발송이 불가한 항목이 있습니다.",
        )
    else:
        empty = _ui_empty_state("현재 장애 없음", "현재 조치가 필요한 활성 프로그램 장애가 없습니다.")
    return {"html": "".join(cards), "incident_empty_state": empty, "unhealthy": unhealthy}


@router.get("/admin/incidents", response_class=HTMLResponse)
def admin_incidents_list(request: Request):
    need = _require_login(request)
    if need is not None:
        return need
    memory, deferred = _begin_heavy_admin_projection(
        title="Incidents", active="incidents"
    )
    if deferred is not None:
        return deferred
    from natural_run_incident_store import list_incident_page

    page = list_incident_page(
        limit=ADMIN_UI_PAGE_SIZE,
        cursor=_admin_list_cursor(request),
    )
    incidents = [
        item for item in page["items"]
        if str(item.get("program_id") or "") in ACTIVE_PROGRAM_IDS
    ]
    runs = [meta for meta in list_run_artifacts(limit=100) if is_active_program(meta)]
    projected = incident_current_projection(incidents, runs)
    service_cards = _program_service_state_cards(runs, incidents)
    cards = []
    for item in projected["current"]:
        view = incident_projection(item)
        cards.append(f"""
<article class="run-card">
  <div class="run-card__top"><div><p class="eyebrow">{_esc(view['program']['display'])}</p><h3>{_esc(view['scheduled'] or '실행 시각 미기록')} 발행 장애</h3></div>{_ui_badge(view['current'], view['tone'])}</div>
  <div class="metrics" style="margin:14px 0;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));">
    {_ui_metric('고객 영향', view['customer_impact'])}
    {_ui_metric('실패 단계', view['failed_stage'])}
    {_ui_metric('안전 상태', view['duplicate_risk'])}
  </div>
  <div class="actions"><a class="btn" href="/admin/incidents/{_esc(view['incident_id'])}">{_esc(view['next_action'])}</a></div>
</article>""")
    memory.record("after_projection")
    inner = f"""
{_ui_page_header('장애·복구', '고객 영향과 안전한 다음 행동을 먼저 보여줍니다. 자동 재실행과 자동 고객 발송은 없습니다.', 'INCIDENTS & RECOVERY')}
<div class="notice">장애 상세를 여는 것만으로 복구가 실행되지 않습니다. 기존 확인 화면과 명시적 POST 안전 장치를 유지합니다.</div>
<div class="section-heading"><div><h2>프로그램 서비스 상태</h2></div></div>
<div class="stack" style="margin-top:14px;">{service_cards['html']}</div>
<div class="section-heading"><div><h2>현재 장애 / 조치 필요</h2></div></div>
<div class="stack" style="margin-top:14px;">{''.join(cards) if cards else service_cards['incident_empty_state']}</div>
<details class="technical-details"><summary>해결된 장애 / 이력 ({len(projected['historical'])})</summary><div class="technical-details__body"><p>명시적 종료·복구 성공 또는 이후 검증된 정상 고객 발송 근거가 있는 기록입니다.</p><div class="stack">{''.join(f'<article class="run-card"><div class="run-card__top"><div><p class="eyebrow">{_esc(incident_projection(item)["program"]["display"])}</p><h3>{_esc(incident_projection(item)["scheduled"] or "실행 시각 미기록")} 발행 장애</h3></div>{_ui_badge("해결됨 / 이력", "neutral")}</div><div class="actions"><a class="btn btn--secondary" href="/admin/incidents/{_esc(item.get("incident_id"))}">기록 보기</a></div></article>' for item in projected['historical']) or _ui_empty_state('해결된 장애 이력 없음','현재 표시할 해결된 활성 프로그램 장애가 없습니다.')}</div></div></details>
{_admin_pagination_controls('/admin/incidents', page)}
"""
    return _finish_heavy_admin_projection(
        memory, title="Incidents", inner=inner, active="incidents"
    )


@router.get("/admin/incidents/{incident_id}", response_class=HTMLResponse)
def admin_incident_detail(request: Request, incident_id: str):
    need = _require_login(request)
    if need is not None:
        return need
    memory, deferred = _begin_heavy_admin_projection(
        title="Incident", active="incidents"
    )
    if deferred is not None:
        return deferred
    from natural_run_incident_store import (
        RETRY_ALLOWED_WITH_WARNING,
        RETRY_BLOCKED,
        RETRY_REQUIRES_PATCH,
        RETRY_SAFE,
        RETRY_SAFE_TO_RETRY,
        RETRY_STATUS_UNKNOWN,
        ROOT_CAUSE_CONFIRMED,
        ROOT_CAUSE_PARTIAL,
        ROOT_CAUSE_UNKNOWN,
        STATUS_RETRY_BLOCKED_PENDING_PATCH,
        incident_retry_review_allowed,
        is_retry_actionable,
        load_incident,
        normalize_retry_actionability,
        recovery_effective_retry_verdict,
        recovery_guard_is_blocked,
        validate_incident_id,
    )

    if not validate_incident_id(incident_id):
        return HTMLResponse(_layout("Not found", "<p>잘못된 incident_id</p>"), status_code=404)
    meta = load_incident(incident_id)
    if not meta:
        return HTMLResponse(_layout("Not found", "<p>장애 기록을 찾을 수 없습니다.</p>"), status_code=404)

    warn = ""
    if request.query_params.get("recovery_error"):
        warn = f'<div class="warn">재실행 차단: {_esc(request.query_params.get("recovery_error"))}</div>'
    if request.query_params.get("recovery_ok") == "1":
        warn = (
            f'<div class="card">재실행이 완료되었습니다. recovery run_id='
            f'{_esc(request.query_params.get("recovery_run_id"))}</div>'
        )

    cause = meta.get("confirmed_cause")
    cause_ko = "원인 미확정" if cause in (None, "") else str(cause)
    stage_rows = "".join(
        f"<tr><td>{_esc(k)}</td><td>{_esc(v)}</td></tr>"
        for k, v in (meta.get("stage_map") or {}).items()
    )
    status = str(meta.get("status") or "")
    verdict = recovery_effective_retry_verdict(meta)
    recovery_guard_blocked = recovery_guard_is_blocked(meta)
    root_cause = str(meta.get("root_cause_verdict") or ROOT_CAUSE_UNKNOWN)
    retry_review_allowed = incident_retry_review_allowed(meta)
    smoke = bool(meta.get("smoke_failure") or meta.get("smoke_only") or meta.get("verification_only"))
    outcomes = meta.get("outcomes") if isinstance(meta.get("outcomes"), dict) else {}
    customer_status = outcomes.get("고객 메일") or meta.get("recovery_customer_send_count") or "발송되지 않음"

    # Completed / in-flight recovery UX
    if status == "recovery_succeeded":
        actions = f"""
<div class="card">
<strong>재실행 승인 완료</strong>
<ul>
<li>recovery_run_id: <code>{_esc(meta.get('recovery_run_id') or '(없음)')}</code></li>
<li>승인 시각: {_esc(meta.get('recovery_approved_at') or '-')}</li>
<li>완료 시각: {_esc(meta.get('recovery_completed_at') or '-')}</li>
<li>상태: recovery_succeeded (RESOLVED)</li>
</ul>
<p>추가 자동 재실행은 수행하지 않습니다. 승인 버튼은 비활성입니다.</p>
</div>
"""
    elif status == "recovery_approved":
        actions = f"""
<div class="card warn">
<strong>재실행이 이미 승인되어 진행 중이거나 임대가 보유 중입니다.</strong>
<ul>
<li>승인 시각: {_esc(meta.get('recovery_approved_at') or '-')}</li>
<li>recovery_run_id: <code>{_esc(meta.get('recovery_run_id') or '(대기/없음)')}</code></li>
</ul>
<p>중복 승인은 차단됩니다.</p>
</div>
"""
    elif status == "dismissed":
        actions = '<p class="warn">이 incident는 재실행 안 함으로 종료되었습니다.</p>'
    elif smoke:
        actions = """
<div class="card warn">
<strong>검증/스모크 incident</strong> — 실제 recovery 승인이 금지됩니다.
<p>메일 CTA의 「검증 incident 보기」는 조회 전용입니다.</p>
</div>
"""
    elif recovery_guard_blocked:
        actions = f"""
<div class="card warn">
<button class="btn" type="button" disabled style="background:#94a3b8;cursor:not-allowed;">재실행 승인</button>
<p><strong>{_esc(meta.get('recovery_guard_message_ko'))}</strong></p>
<p>상태: <code>{_esc(STATUS_RETRY_BLOCKED_PENDING_PATCH)}</code></p>
</div>
"""
    elif status not in {"reported", "open", "recovery_failed", STATUS_RETRY_BLOCKED_PENDING_PATCH}:
        actions = f'<p class="warn">현재 상태(<code>{_esc(status)}</code>)에서는 재실행 승인 버튼이 비활성입니다.</p>'
    elif root_cause.strip().upper() in {
        "",
        "UNKNOWN",
        "INCONCLUSIVE",
        "ROOT_CAUSE_UNKNOWN",
        "ROOT_CAUSE_INCONCLUSIVE",
    }:
        actions = """
<div class="card warn">
<button class="btn" type="button" disabled style="background:#94a3b8;cursor:not-allowed;">재실행 검토 보류</button>
<p><strong>원인 조사 필요 — 재실행 보류</strong></p>
<p>원인과 재실행 부작용이 충분히 확인된 뒤에만 검토 버튼을 열 수 있습니다.</p>
</div>
"""
    elif retry_review_allowed and (verdict == RETRY_SAFE or verdict == RETRY_SAFE_TO_RETRY):
        actions = f"""
<div class="card">
<p>원인 판정: <strong>{_esc(root_cause)}</strong> · 재실행 판정: <strong>RETRY_SAFE</strong></p>
<p><a class="btn" style="background:#b91c1c;" href="/admin/incidents/{_esc(incident_id)}/approve-confirm">재실행 승인</a>
<form method="post" action="/admin/incidents/{_esc(incident_id)}/dismiss" style="display:inline-block;margin-left:12px;">
{_csrf_field(request, f'incident_dismiss:{incident_id}')}
<button class="btn" type="submit" style="background:#475569;">재실행 안 함</button>
</form></p>
<p style="font-size:12px;color:#555;">이 페이지(GET)만으로는 재실행되지 않습니다. 확인 화면에서 POST해야 합니다.</p>
</div>
"""
    elif retry_review_allowed and verdict == RETRY_ALLOWED_WITH_WARNING:
        actions = f"""
<div class="card warn">
<p>원인 판정: <strong>{_esc(root_cause)}</strong> · 재실행 판정: <strong>RETRY_ALLOWED_WITH_WARNING</strong></p>
<p>장애 원인이 완전히 제거되었는지는 확인되지 않았을 수 있습니다. 재실행이 다시 실패할 수 있습니다.</p>
<p>그러나 이번 복구 실행은 운영자 검수용으로 격리되며 고객에게 발송되지 않습니다.</p>
<p><a class="btn" style="background:#b45309;" href="/admin/incidents/{_esc(incident_id)}/approve-confirm">재실행 시도</a>
<form method="post" action="/admin/incidents/{_esc(incident_id)}/dismiss" style="display:inline-block;margin-left:12px;">
{_csrf_field(request, f'incident_dismiss:{incident_id}')}
<button class="btn" type="submit" style="background:#475569;">재실행 안 함</button>
</form></p>
</div>
"""
    elif verdict == RETRY_BLOCKED:
        actions = """
<div class="card warn">
<button class="btn" type="button" disabled style="background:#94a3b8;cursor:not-allowed;">재실행 승인</button>
<p><strong>현재는 안전한 재실행 조건이 확보되지 않았습니다.</strong> (RETRY_BLOCKED)</p>
</div>
"""
    else:
        actions = """
<div class="card warn">
<button class="btn" type="button" disabled style="background:#94a3b8;cursor:not-allowed;">재실행 검토 보류</button>
<p><strong>재실행 부작용을 확정하지 못해 검토 버튼을 열 수 없습니다.</strong> (RETRY_STATUS_UNKNOWN)</p>
<p>고객 발송·SMTP 등 부작용이 안전하다고 확인된 뒤에만 재실행을 검토합니다.</p>
</div>
"""

    if status == "recovery_failed" and not smoke and retry_review_allowed:
        label = "재실행 승인" if verdict in {RETRY_SAFE, RETRY_SAFE_TO_RETRY} else "재실행 시도"
        actions = f"""
<div class="card warn">
<strong>이전 재실행 실패</strong> — 자동 재시도는 없습니다. 운영자가 명시적으로 다시 승인할 수 있습니다.
<p><a class="btn" style="background:#b91c1c;" href="/admin/incidents/{_esc(incident_id)}/approve-confirm">{_esc(label)}</a></p>
</div>
"""

    view = incident_projection(meta)
    recovery_link = ""
    recovery_run_id = str(meta.get("recovery_run_id") or "")
    if recovery_run_id and validate_run_id(recovery_run_id):
        recovery_link = f'<a class="btn" href="/admin/runs/{_esc(recovery_run_id)}">복구본 검수하기</a>'
    auto_items = "".join(f"<li>{_esc(item)}</li>" for item in view["system_action"])
    technical = _ui_technical_details(
        meta,
        (
            ("Incident ID", incident_id),
            ("Original Run ID", meta.get("original_run_id") or meta.get("smoke_run_id")),
            ("Root cause verdict", root_cause),
            ("Retry verdict", verdict),
            ("Recovery Run ID", recovery_run_id),
            ("Detected at", meta.get("detected_at") or meta.get("created_at")),
        ),
    )
    stage_summary = "".join(
        f'<div class="timeline-item"><strong>{_esc(k)}</strong><p>{_esc(v)}</p></div>'
        for k, v in (meta.get("stage_map") or {}).items()
    ) or '<div class="timeline-item"><strong>실패 단계 근거 부족</strong><p>Cloud Run 로그 확인이 필요할 수 있습니다.</p></div>'
    inner = f"""
{_ui_page_header(f"{view['program']['display']} 발행 장애", f"예정 실행 {view['scheduled']} KST", 'INCIDENT DECISION')}
{warn}
<section class="surface">
  <div class="section-heading" style="margin-top:0;"><div><p class="eyebrow">1 · CUSTOMER IMPACT</p><h2>고객 영향</h2></div>{_ui_badge(view['customer_impact'], 'good' if view['customer_impact'] == '고객 발송 없음' else 'warn')}</div>
  <div class="metrics" style="grid-template-columns:repeat(2,minmax(0,1fr));">
    {_ui_metric('고객 발송', view['customer_impact'])}
    {_ui_metric('중복 발송', view['duplicate_risk'])}
  </div>
</section>
<section class="surface" style="margin-top:14px;">
  <div class="section-heading" style="margin-top:0;"><div><p class="eyebrow">2 · FAILURE</p><h2>무엇이 실패했나</h2></div></div>
  <p><strong>{_esc(view['failed_stage'])}</strong></p><p style="color:var(--muted);">{_esc(meta.get('summary_ko') or cause_ko)}</p>
  <div class="timeline">{stage_summary}</div>
</section>
<section class="surface" style="margin-top:14px;">
  <div class="section-heading" style="margin-top:0;"><div><p class="eyebrow">3 · AUTOMATION</p><h2>시스템이 이미 한 일</h2></div></div>
  <ul class="validation-list">{''.join(f'<li><span class="marker"></span><span>{_esc(item)}</span></li>' for item in view['system_action'])}</ul>
</section>
<section class="surface" style="margin-top:14px;">
  <div class="section-heading" style="margin-top:0;"><div><p class="eyebrow">4 · CURRENT STATE</p><h2>현재 상태</h2></div>{_ui_badge(view['current'], view['tone'])}</div>
  <p>{_esc(meta.get('recommendation_ko') or view['next_action'])}</p>{recovery_link}
</section>
<section class="surface" style="margin-top:14px;">
  <div class="section-heading" style="margin-top:0;"><div><p class="eyebrow">5 · SAFE NEXT ACTION</p><h2>안전한 다음 행동</h2></div></div>
  {actions}
</section>
<section class="notice notice--danger" style="margin-top:14px;">
  <strong>피해야 할 행동</strong><p>자동 고객 발송, 반복 클릭, 원인 근거 없이 같은 복구를 연속 실행하지 마세요. 이 페이지(GET)만으로는 재실행되지 않습니다.</p>
</section>
{technical}
"""
    memory.record("after_projection")
    return _finish_heavy_admin_projection(
        memory,
        title=f"Incident {incident_id}",
        inner=inner,
        active="incidents",
    )


@router.get("/admin/incidents/{incident_id}/approve-confirm", response_class=HTMLResponse)
def admin_incident_approve_confirm(request: Request, incident_id: str):
    """Explicit confirmation page. GET never executes recovery."""
    need = _require_login(request)
    if need is not None:
        return need
    from natural_run_incident_store import (
        RETRY_ALLOWED_WITH_WARNING,
        RETRY_SAFE,
        RETRY_SAFE_TO_RETRY,
        STATUS_RETRY_BLOCKED_PENDING_PATCH,
        incident_retry_review_allowed,
        is_retry_actionable,
        load_incident,
        normalize_retry_actionability,
        recovery_effective_retry_verdict,
        recovery_guard_is_blocked,
        validate_incident_id,
    )

    if not validate_incident_id(incident_id):
        return HTMLResponse(_layout("Not found", "<p>잘못된 incident_id</p>"), status_code=404)
    meta = load_incident(incident_id)
    if not meta:
        return HTMLResponse(_layout("Not found", "<p>장애 기록을 찾을 수 없습니다.</p>"), status_code=404)

    status = str(meta.get("status") or "")
    verdict = recovery_effective_retry_verdict(meta)
    smoke = bool(meta.get("smoke_failure") or meta.get("smoke_only") or meta.get("verification_only"))
    if smoke:
        inner = (
            "<p class=\"warn\">검증/스모크 incident는 재실행할 수 없습니다.</p>"
            f"<p><a href=\"/admin/incidents/{_esc(incident_id)}\">← 상세</a></p>"
        )
        return HTMLResponse(_layout("Approve blocked", inner), status_code=400)
    if recovery_guard_is_blocked(meta):
        inner = (
            f'<p class="warn">{_esc(meta.get("recovery_guard_message_ko"))}</p>'
            f'<p><a href="/admin/incidents/{_esc(incident_id)}">← 상세</a></p>'
        )
        return HTMLResponse(_layout("Approve blocked", inner), status_code=400)
    if status not in {"reported", "open", "recovery_failed", STATUS_RETRY_BLOCKED_PENDING_PATCH}:
        inner = (
            f"<p class=\"warn\">상태 <code>{_esc(status)}</code>에서는 재실행할 수 없습니다.</p>"
            f"<p><a href=\"/admin/incidents/{_esc(incident_id)}\">← 상세</a></p>"
        )
        return HTMLResponse(_layout("Approve blocked", inner), status_code=400)
    if not incident_retry_review_allowed(meta):
        inner = (
            f"<p class=\"warn\">재실행 판정 <code>{_esc(verdict)}</code> — 승인할 수 없습니다.</p>"
            f"<p><a href=\"/admin/incidents/{_esc(incident_id)}\">← 상세</a></p>"
        )
        return HTMLResponse(_layout("Approve blocked", inner), status_code=400)

    if verdict == RETRY_ALLOWED_WITH_WARNING:
        warn_block = """
<p><strong>장애 원인이 완전히 제거되었는지는 확인되지 않았습니다.</strong><br>
재실행이 다시 실패할 수 있습니다.</p>
<p>그러나 이번 복구 실행은 운영자 검수용으로 격리되며<br>
고객에게 발송되지 않습니다.</p>
<p><strong>정확히 1회 재실행하시겠습니까?</strong></p>
"""
        submit_label = "1회 재실행"
    else:
        warn_block = """
<p><strong>운영자 검수용 복구 실행을 정확히 1회 수행합니다.</strong><br>
고객 발송은 하지 않습니다.</p>
"""
        submit_label = "재실행 승인"

    inner = f"""
<div class="page-head">
<h1>재실행 최종 확인</h1>
<a href="/admin/incidents/{_esc(incident_id)}" class="btn" style="background:#475569;">취소</a>
</div>
<div class="card warn">
{warn_block}
<ul>
<li>프로그램: {_esc(meta.get('program_display') or meta.get('program_id'))}</li>
<li>원 예정 실행: {_esc(meta.get('kst_date'))} {_esc(meta.get('scheduled_slot'))} KST</li>
<li>incident_id: <code>{_esc(incident_id)}</code></li>
<li>원 run_id: <code>{_esc(meta.get('original_run_id') or '(없음)')}</code></li>
<li>재실행 판정: <code>{_esc(verdict)}</code></li>
</ul>
<p>이미 recovery가 실행되었다면 다시 실행되지 않습니다.</p>
</div>
<form method="post" action="/admin/incidents/{_esc(incident_id)}/approve-recovery">
{_csrf_field(request, f'incident_recovery:{incident_id}')}
<div class="form-actions">
<a class="btn" style="background:#475569;margin-right:12px;" href="/admin/incidents/{_esc(incident_id)}">취소</a>
<button class="btn" type="submit" style="background:#b91c1c;" id="approve-recovery-btn">{_esc(submit_label)}</button>
</div>
</form>
<script>
(function(){{
  var form = document.querySelector('form[action$="approve-recovery"]');
  if (!form) return;
  var btn = document.getElementById('approve-recovery-btn');
  form.addEventListener('submit', function(){{
    if (btn) {{ btn.disabled = true; btn.textContent = '승인 처리 중…'; }}
  }});
}})();
</script>
"""
    return HTMLResponse(_layout(f"Confirm recovery {incident_id}", inner))


@router.post("/admin/incidents/{incident_id}/dismiss")
def admin_incident_dismiss(request: Request, incident_id: str, csrf_token: str = Form("")):
    need = _require_login(request)
    if need is not None:
        return need
    if not _verify_csrf(request, f"incident_dismiss:{incident_id}", csrf_token):
        return _csrf_rejected()
    from natural_run_incident_store import dismiss_incident, validate_incident_id

    if not validate_incident_id(incident_id):
        return RedirectResponse(url="/admin/incidents?recovery_error=invalid_id", status_code=303)
    dismiss_incident(incident_id)
    append_operator_audit(
        "incident_dismissed",
        operator_id=_operator_id(request),
        incident_id=incident_id,
        result="dismissed",
    )
    return RedirectResponse(url=f"/admin/incidents/{incident_id}", status_code=303)


@router.post("/admin/incidents/{incident_id}/approve-recovery")
def admin_incident_approve_recovery(request: Request, incident_id: str, csrf_token: str = Form("")):
    need = _require_login(request)
    if need is not None:
        return need
    if not _verify_csrf(request, f"incident_recovery:{incident_id}", csrf_token):
        return _csrf_rejected()
    from natural_run_incident_store import (
        incident_retry_review_allowed,
        recovery_effective_retry_verdict,
        recovery_guard_is_blocked,
        is_retry_actionable,
        load_incident,
        validate_incident_id,
    )
    from natural_run_recovery import execute_approved_recovery

    if not validate_incident_id(incident_id):
        return RedirectResponse(url="/admin/incidents?recovery_error=invalid_id", status_code=303)
    meta = load_incident(incident_id) or {}
    if meta.get("smoke_failure") or meta.get("smoke_only") or meta.get("verification_only"):
        return RedirectResponse(
            url=f"/admin/incidents/{incident_id}?recovery_error=smoke_or_verification_blocked",
            status_code=303,
        )
    if recovery_guard_is_blocked(meta):
        return RedirectResponse(
            url=f"/admin/incidents/{incident_id}?recovery_error=retry_blocked_pending_patch",
            status_code=303,
        )
    if not incident_retry_review_allowed(meta):
        return RedirectResponse(
            url=f"/admin/incidents/{incident_id}?recovery_error=verdict_not_actionable",
            status_code=303,
        )
    result = execute_approved_recovery(incident_id)
    append_operator_audit(
        "incident_recovery_confirmed",
        operator_id=_operator_id(request),
        incident_id=incident_id,
        result="accepted" if result.get("ok") else "blocked_or_failed",
        reason_code=str(result.get("error") or ""),
        related_id=str(result.get("recovery_run_id") or ""),
    )
    if not result.get("ok") and result.get("error") == "recovery_lease_unavailable":
        return RedirectResponse(
            url=f"/admin/incidents/{incident_id}?recovery_error=lease_unavailable",
            status_code=303,
        )
    if result.get("ok"):
        rid = result.get("recovery_run_id") or ""
        return RedirectResponse(
            url=f"/admin/incidents/{incident_id}?recovery_ok=1&recovery_run_id={rid}",
            status_code=303,
        )
    err = result.get("error") or "recovery_failed"
    return RedirectResponse(
        url=f"/admin/incidents/{incident_id}?recovery_error={err}",
        status_code=303,
    )


@router.get("/admin/costs", response_class=HTMLResponse)
def admin_costs(request: Request):
    need = _require_login(request)
    if need is not None:
        return need
    requested_month = str(request.query_params.get("month") or "")
    month = requested_month if re.match(r"^[0-9]{4}-[0-9]{2}$", requested_month) else now_kst_iso()[:7]
    records = parse_cost_ledger_csv(load_cost_ledger_csv(month) or "")
    billing = load_billing_summary(month)
    allocation = allocation_metrics(billing.get("shared_platform_net"), records)
    rows = []
    for record in reversed(records[-100:]):
        rid = _esc(record.get("run_id"))
        rows.append(
            "<tr>"
            f"<td><a href=\"/admin/runs/{rid}\">{rid}</a></td>"
            f"<td>{_esc(record.get('created_at_kst'))}</td>"
            f"<td>{_esc(record.get('text_model'))}</td>"
            f"<td>{_esc(_format_cost_usd(record.get('text_input_cost_usd')))}</td>"
            f"<td>{_esc(_format_cost_usd(record.get('text_output_cost_usd')))}</td>"
            f"<td>{_esc(_format_cost_usd(record.get('text_thoughts_cost_usd')))}</td>"
            f"<td>{_esc(_format_cost_usd(record.get('text_total_cost_usd')))}</td>"
            f"<td>{_esc(_format_cost_usd(record.get('image_cost_usd')) if record.get('image_cost_usd') not in (None, '') else 'unknown')}</td>"
            f"<td>{_esc(_format_cost_usd(record.get('total_cost_usd')))}</td>"
            f"<td>{_esc(record.get('cost_estimate_status'))}</td>"
            f"<td>{_esc(record.get('missing_price_env') or '—')}</td>"
            "</tr>"
        )

    def _known_sum(column: str) -> Decimal:
        total = Decimal("0")
        for record in records:
            raw = str(record.get(column) or "").strip()
            if not raw:
                continue
            try:
                total += Decimal(raw)
            except (InvalidOperation, TypeError, ValueError):
                continue
        return total

    status_counts: Dict[str, int] = {}
    for record in records:
        status = str(record.get("cost_estimate_status") or "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
    fully_priced = sum(
        status_counts.get(s, 0)
        for s in ("estimated", "fully_priced", "fully_priced_ai_model_cost")
    )
    partially_priced = sum(status_counts.get(s, 0) for s in ("partial", "partial_text_only"))
    unknown_models = sum(
        standard_text_pricing_for_model(record.get("text_model")) is None for record in records
    )
    known_image_cost_runs = sum(
        str(record.get("image_cost_usd") or "").strip() != "" for record in records
    )
    unknown_image_cost_runs = len(records) - known_image_cost_runs
    summary = (
        '<div class="card"><h2>월 합계</h2><dl class="meta">'
        f"<dt>Text subtotal USD</dt><dd>{_esc(_format_cost_usd(_known_sum('text_total_cost_usd')))}</dd>"
        f"<dt>Known image subtotal USD</dt><dd>{_esc(_format_cost_usd(_known_sum('image_cost_usd')))}</dd>"
        f"<dt>Complete AI model total USD</dt><dd>{_esc(_format_cost_usd(_known_sum('total_cost_usd')))}</dd>"
        f"<dt>Fully priced runs</dt><dd>{fully_priced}</dd>"
        f"<dt>Partially priced runs</dt><dd>{partially_priced}</dd>"
        f"<dt>Known image-cost runs (zero included)</dt><dd>{known_image_cost_runs}</dd>"
        f"<dt>Unknown image-cost runs</dt><dd>{unknown_image_cost_runs}</dd>"
        f"<dt>Usage-only runs</dt><dd>{status_counts.get('usage_only', 0)}</dd>"
        f"<dt>Unknown model runs</dt><dd>{unknown_models}</dd>"
        "</dl></div>"
    )
    ai_list_total = _known_sum("total_cost_usd")
    modeled = modeled_service_cost(
        ai_list_total,
        billing.get("non_ai_infra_net"),
        billing.get("external_cost_confirmed", "0"),
    )

    def _billing_value(key: str) -> str:
        value = billing.get(key)
        return "—" if value in (None, "") else str(value)

    unknown_items = billing.get("unknown_service_skus")
    unknown_count = len(unknown_items) if isinstance(unknown_items, list) else 0
    billing_summary = (
        '<div class="card"><h2>GCP 실제 청구·관리회계</h2>'
        '<p>Billing Export의 gross, signed credits, net을 표시합니다. Vertex AI billed net은 기존 AI list 원가와 비교만 하며 합산하지 않습니다.</p>'
        '<dl class="meta">'
        f"<dt>Billing data status</dt><dd>{_esc(_billing_value('billing_data_status'))}</dd>"
        f"<dt>Last usage time</dt><dd>{_esc(_billing_value('billing_export_last_usage_time'))}</dd>"
        f"<dt>Last load time</dt><dd>{_esc(_billing_value('billing_export_last_load_time'))}</dd>"
        f"<dt>Billing currency</dt><dd>{_esc(_billing_value('billing_currency'))}</dd>"
        f"<dt>GCP gross</dt><dd>{_esc(_billing_value('gcp_gross_cost'))}</dd>"
        f"<dt>Signed credits</dt><dd>{_esc(_billing_value('gcp_credits'))}</dd>"
        f"<dt>GCP net</dt><dd>{_esc(_billing_value('gcp_net_cost'))}</dd>"
        f"<dt>Billing cost USD</dt><dd>{_esc(_billing_value('billing_cost_usd'))}</dd>"
        f"<dt>Billing cost KRW</dt><dd>{_esc(_billing_value('billing_cost_krw'))}</dd>"
        f"<dt>Vertex AI billed net</dt><dd>{_esc(_billing_value('vertex_ai_billed_net'))}</dd>"
        f"<dt>Non-AI infra net</dt><dd>{_esc(_billing_value('non_ai_infra_net'))}</dd>"
        f"<dt>Run compute net</dt><dd>{_esc(_billing_value('run_compute_net'))}</dd>"
        f"<dt>Run storage net</dt><dd>{_esc(_billing_value('run_storage_net'))}</dd>"
        f"<dt>Shared platform net</dt><dd>{_esc(_billing_value('shared_platform_net'))}</dd>"
        f"<dt>Other/unclassified net</dt><dd>{_esc(_billing_value('other_unclassified_net'))}</dd>"
        f"<dt>Unknown service/SKU count</dt><dd>{unknown_count}</dd>"
        f"<dt>Operational runs</dt><dd>{allocation['operational_run_count']}</dd>"
        f"<dt>Shared overhead / operational run</dt><dd>{_esc(allocation.get('shared_overhead_per_operational_run') or '—')}</dd>"
        f"<dt>Delivered runs</dt><dd>{allocation['delivered_run_count']}</dd>"
        f"<dt>Shared burden / delivered run</dt><dd>{_esc(allocation.get('shared_overhead_burden_per_delivered_run') or '—')}</dd>"
        f"<dt>Modeled service cost USD</dt><dd>{_esc(str(modeled) if modeled is not None else '—')}</dd>"
        f"<dt>Reconciliation status</dt><dd>{_esc(_billing_value('billing_reconciliation_status'))}</dd>"
        "</dl></div>"
    )
    table = (
        "<table><thead><tr>"
        "<th>run_id</th><th>created_at_kst</th><th>text model</th>"
        "<th>Text input cost</th><th>Text response cost</th><th>Text reasoning cost</th>"
        "<th>Text total cost</th><th>Image model cost</th><th>Total AI model production cost</th>"
        "<th>Estimate status</th><th>Missing pricing component</th>"
        "</tr></thead><tbody>"
        + ("".join(rows) if rows else "<tr><td colspan=\"11\">저장된 cost ledger 행이 없습니다.</td></tr>")
        + "</tbody></table>"
    )
    inner = f"""
<div class="page-head">
<h1>AI 모델 생산 원가 ledger</h1>
<div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center;">
<a href="/admin/runs" class="btn" style="background:#475569;">← 실행 목록</a>
<a href="/admin/costs/ledger.csv?month={_esc(month)}" class="btn" style="background:#0f172a;">현재 월 CSV 다운로드</a>
</div>
</div>
<p class="break-long">월별 CSV 경로: <code>{_esc(cost_ledger_display_path(month))}</code></p>
{summary}
{billing_summary}
<div class="card"><div class="table-wrap">{table}</div></div>
"""
    return HTMLResponse(_layout("Cost Ledger", inner))


@router.get("/admin/costs/ledger.csv")
def admin_cost_ledger_csv(request: Request, month: str = "") -> Response:
    need = _require_login(request)
    if need is not None:
        return need
    selected_month = month if re.match(r"^[0-9]{4}-[0-9]{2}$", str(month or "")) else now_kst_iso()[:7]
    content = load_cost_ledger_csv(selected_month)
    if content is None:
        header = ",".join(COST_LEDGER_COLUMNS) + "\n"
        content = header
    else:
        billing = load_billing_summary(selected_month)
        monthly_fields = {
            key: billing.get(key)
            for key in (
                "billing_data_status", "billing_export_last_usage_time",
                "billing_export_last_load_time", "billing_data_freshness",
                "gcp_gross_cost", "gcp_credits", "gcp_net_cost",
                "vertex_ai_billed_gross", "vertex_ai_billed_net",
                "non_ai_infra_gross", "non_ai_infra_net", "run_compute_net",
                "run_storage_net", "shared_platform_net", "other_unclassified_net",
                "billing_currency", "billing_cost_usd", "billing_cost_krw",
                "currency_conversion_source",
            )
        }
        monthly_fields["monthly_billing_reconciliation_status"] = billing.get(
            "billing_reconciliation_status"
        )
        rows = parse_cost_ledger_csv(content)
        content = render_cost_ledger_csv([{**row, **monthly_fields} for row in rows])
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="genie_cost_ledger_{selected_month}.csv"'
        },
    )


def _render_keysuri_graded_quality_panel(meta: Mapping[str, Any]) -> str:
    mode = str(meta.get("mode") or meta.get("program_id") or "")
    if mode not in {"keysuri_global_tech", "keysuri_korea_tech"}:
        return ""
    safety = str(meta.get("safety_verdict") or "미확정")
    editorial = str(meta.get("editorial_verdict") or "미확정")
    safety_label = {"SAFE": "안전", "UNSAFE": "위험", "INCONCLUSIVE": "판정 불가"}.get(
        safety, "미확정"
    )
    editorial_label = {"READY": "준비 완료", "REVIEW": "검토 필요", "POOR": "수정 필요"}.get(
        editorial, "미확정"
    )
    findings = [row for row in meta.get("findings") or [] if isinstance(row, Mapping)]
    rows: List[str] = []
    for finding in findings[:48]:
        state = str(finding.get("finding_state") or "")
        state_label = {
            "REPAIRED": "자동 수정 완료",
            "RESIDUAL": "운영자 확인 필요",
            "TERMINAL": "안전성 차단",
            "DETECTED": "탐지됨",
        }.get(state, state or "확인 필요")
        location = " · ".join(
            part
            for part in (
                str(finding.get("field") or "").strip(),
                f"{finding.get('rank')}위" if finding.get("rank") not in (None, "") else "",
                str(finding.get("source_id") or "").strip(),
            )
            if part
        )
        before = str(finding.get("before") or "").strip()
        after = str(finding.get("after") or "").strip()
        sample = ""
        if before:
            sample += f'<div><span style="color:var(--muted);">수정 전</span> {_esc(before)}</div>'
        if after:
            sample += f'<div><span style="color:var(--muted);">수정 후</span> {_esc(after)}</div>'
        rows.append(
            '<li style="margin-bottom:12px;">'
            f'<strong>{_esc(finding.get("label_ko") or "품질 확인 필요")}</strong> '
            f'<span class="badge">{_esc(state_label)}</span>'
            f'{f"<div>{_esc(location)}</div>" if location else ""}{sample}'
            '</li>'
        )
    finding_html = "".join(rows) or "<li>추가 품질 항목 없음</li>"
    review_help = ""
    if safety == "SAFE" and editorial == "REVIEW":
        review_help = (
            '<div class="notice"><strong>검토 필요 · 고객 발송 전 확인</strong>'
            '<p>수정 요청, 거절, 또는 경고 확인 후 승인을 선택할 수 있습니다.</p></div>'
        )
    return (
        '<section class="surface" style="margin-top:14px;">'
        '<div class="section-heading" style="margin-top:0;"><div>'
        '<p class="eyebrow">GRADED QUALITY</p><h2>안전성과 편집 품질</h2></div></div>'
        f'<div class="metrics">{_ui_metric("안전성", safety_label, safety)}'
        f'{_ui_metric("편집 품질", editorial_label, editorial)}</div>{review_help}'
        f'<h3>항목별 확인</h3><ul>{finding_html}</ul>'
        '<details class="technical-details"><summary>내부 코드 보기</summary><div class="technical-details__body">'
        f'<code>{_esc(", ".join(str(code) for code in meta.get("issue_codes") or []) or "없음")}</code>'
        '</div></details></section>'
    )


@router.get("/admin/runs/{run_id}", response_class=HTMLResponse)
def admin_run_detail(request: Request, run_id: str):
    need = _require_login(request)
    if need is not None:
        return need
    memory, deferred = _begin_heavy_admin_projection(
        title="Review", active="reviews"
    )
    if deferred is not None:
        return deferred
    if not validate_run_id(run_id):
        return HTMLResponse(_layout("Not found", "<p>잘못된 run_id</p>"), status_code=404)
    meta = load_run_artifact(run_id)
    if not meta:
        return HTMLResponse(_layout("Not found", "<p>실행 기록을 찾을 수 없습니다.</p>"), status_code=404)
    warn = ""
    if request.query_params.get("reissue_dry_run") == "1":
        warn += (
            '<div class="warn">QA dry-run(no-send) 재발행이 완료되었습니다. '
            "이 실행은 실제 reissue 파이프라인을 수행했지만 운영자 검토(owner-review) 이메일과 "
            "고객 발송은 하지 않았습니다. 아래 메타에서 reissue repair 결과를 확인하세요 "
            "(admin_reissue_dry_run / reissue_top5_repair_source 등).</div>"
        )
    if request.query_params.get("reissue_warn") == "email_not_sent":
        warn += (
            '<div class="warn">재발행 실행은 완료되었지만 운영자 검토용 이메일은 발송되지 않았습니다. '
            "SMTP 설정, EMAIL_TO(소유자 계정), 정책/이미지 자산을 확인하세요.</div>"
        )
    has_email = run_email_html_exists(run_id)
    email_link = f'<a href="/admin/runs/{_esc(run_id)}/email" target="_blank">이메일 HTML 미리보기</a>' if has_email else "<em>저장된 이메일 HTML 없음</em>"
    can_approve, approve_err = can_approve_customer_send(meta, has_email_html=has_email)
    mode = str(meta.get("mode") or "")
    approve_block = ""
    if can_approve:
        approve_block = (
            f'<div class="form-actions"><p style="margin:0;"><a class="btn" href="/admin/runs/{_esc(run_id)}/approve-confirm">'
            "승인 검토 페이지 열기</a></p></div>"
        )
    else:
        approve_block = (
            f'<p class="warn">승인 발송 불가: {_esc(_APPROVE_ERROR_MESSAGES.get(approve_err, approve_err))}</p>'
        )
    if request.query_params.get("approve_error"):
        err_code = request.query_params.get("approve_error", "")
        warn += (
            f'<div class="warn">승인 실패: {_esc(_APPROVE_ERROR_MESSAGES.get(err_code, err_code))}</div>'
        )
    if request.query_params.get("reissue_error"):
        err_code = request.query_params.get("reissue_error", "")
        warn += (
            f'<div class="warn">재발행 차단: {_esc(_REISSUE_ERROR_MESSAGES.get(err_code, err_code))}</div>'
        )
    cost_section = _render_cost_estimate_section(meta)
    linked_incident_id = str(
        meta.get("original_incident_id") or meta.get("incident_id") or ""
    ).strip()
    incident_link = ""
    if linked_incident_id:
        incident_link = (
            f'<p><a class="btn" style="background:#b91c1c;" '
            f'href="/admin/incidents/{_esc(linked_incident_id)}">'
            f"장애 보고 / 재실행 승인 ({_esc(linked_incident_id)})</a></p>"
        )
    scope_field = _render_reissue_scope_field(mode, meta)
    recipient_count, recipients_ok = _current_recipient_count()
    view = run_projection(meta, current_recipient_count=recipient_count)
    validation = view["validation"]
    delivery = view["delivery"]
    validation_items = "".join(
        f'<li class="is-{_esc(item["tone"])}"><span class="marker"></span><span>{_esc(item["label"])}</span></li>'
        for item in validation["checks"]
    )
    graded_panel = _render_keysuri_graded_quality_panel(meta)
    accepted = delivery.get("accepted")
    refused = delivery.get("refused")
    recipient_display = recipient_count if recipients_ok else "확인 필요"
    approval_heading = (
        f"승인하고 {_esc(recipient_display)}명에게 발송"
        if can_approve
        else "고객 발송 차단"
    )
    approval_explanation = (
        "승인은 되돌릴 수 없습니다. 실제 발송은 기존 nonce와 확인 체크가 있는 별도 최종 확인 화면에서만 실행됩니다."
        if can_approve
        else "현재 근거로는 새 고객 발송을 시작할 수 없습니다. 차단 사유를 확인하세요."
    )
    legacy_delivery_note = ""
    if str(meta.get("customer_delivery_status") or "") == "smtp_accepted":
        legacy_delivery_note = "legacy artifact label: PASS / 발송 접수 완료 (owner 표시는 접수·거절 근거를 우선함)"
    elif str(meta.get("customer_delivery_status") or "") == "failed":
        legacy_delivery_note = f"FAIL / {meta.get('customer_delivery_error_code') or 'send_failed'}"
    if view["already_sent"]:
        legacy_delivery_note += " / 재발송 차단"
    delivery_metrics = "".join(
        (
            _ui_metric("발송 상태", delivery["label_ko"], delivery["label"]),
            _ui_metric("현재 수신자", recipient_display, "명" if recipients_ok else "설정 근거 부족"),
            _ui_metric("SMTP 접수", accepted if accepted is not None else "미기록", "명"),
            _ui_metric("즉시 거절", refused if refused is not None else "미기록", "명"),
        )
    )
    owner_status = str(meta.get("owner_review_status") or "pending_review")
    if owner_status == "held":
        hold_control = f'''
<div class="notice"><strong>보류 중</strong><p>Owner가 이 결과를 아직 고객에게 발송하지 않기로 결정했습니다. 콘텐츠는 새로 생성되지 않았습니다.</p></div>
<form method="post" action="/admin/runs/{_esc(run_id)}/reopen">
{_csrf_field(request, f'reopen:{run_id}')}
<div class="form-actions"><button class="btn btn--secondary" type="submit">다시 검수하기</button></div>
</form>'''
    elif not view["already_sent"]:
        hold_control = f'''
<form method="post" action="/admin/runs/{_esc(run_id)}/hold">
{_csrf_field(request, f'hold:{run_id}')}
<label>보류 메모 (선택)<br><input type="text" name="hold_note" maxlength="500" placeholder="보류 사유"></label><br><br>
<div class="form-actions"><button class="btn btn--secondary" type="submit">고객 발송 보류</button></div>
</form>'''
    else:
        hold_control = ""
    technical = _ui_technical_details(
        meta,
        (
            ("Run ID", run_id),
            ("Validation codes", ", ".join(validation["issues"]) or "없음"),
            ("Content identity", meta.get("customer_email_mime_html_sha256") or meta.get("artifact_sha256")),
            ("Image identity", meta.get("generated_image_sha256") or meta.get("customer_email_inline_image_hashes")),
            ("Runtime revision", view["revision"]),
            ("Parent / incident", view["parent_run_id"] or view["incident_id"]),
            ("Legacy delivery evidence", legacy_delivery_note),
        ),
        raw_url=f"/admin/runs/{run_id}/json",
    )
    inner = f"""
{_ui_page_header('브리핑 검수', '고객에게 보이는 실제 콘텐츠와 검수·발송 근거를 한 화면에서 확인합니다.', view['program']['display'])}
{warn}
{incident_link}
<section class="surface">
  <div class="run-card__top"><div><p class="eyebrow">{_esc(view['origin'])}</p><h2>{_esc(view['subject'])}</h2></div>{_ui_badge(view['state']['label'], view['state']['tone'])}</div>
  <div class="run-card__meta"><span>{_esc(view['time'])}</span><span>{_esc(view['program']['name'])}</span></div>
</section>
<section class="surface" style="margin-top:14px;">
  <div class="section-heading" style="margin-top:0;"><div><p class="eyebrow">VALIDATION</p><h2>검수 결과</h2></div>{_ui_badge(validation['label'], validation['tone'])}</div>
  <p>{_esc(validation['summary'])}</p><ul class="validation-list">{validation_items}</ul>
</section>
{graded_panel}
{_admin_email_preview_for_run(run_id) if has_email else _ui_email_preview(None)}
<section class="surface">
  <div class="section-heading" style="margin-top:0;"><div><p class="eyebrow">DELIVERY</p><h2>고객 이메일 발송 상태</h2></div>{_ui_badge(delivery['label'], delivery['tone'])}</div>
  <div class="metrics">{delivery_metrics}</div><p style="color:var(--muted);">{_esc(delivery['summary'])} Provider acceptance는 수신함 도착 확인이 아닙니다.</p>
  <p style="color:var(--muted);font-size:13px;">운영자 검토 메일 상태: {_esc(owner_review_email_label_ko(meta))}</p>
</section>
<section class="surface" style="margin-top:14px;">
  <div class="section-heading" style="margin-top:0;"><div><p class="eyebrow">OWNER DECISION</p><h2>안전한 다음 행동</h2></div></div>
  {hold_control}
  <div class="danger-zone" style="margin-top:14px;"><strong>{approval_heading}</strong><p>{approval_explanation}</p>{approve_block}</div>
</section>
<section class="surface" style="margin-top:14px;">
  <div class="section-heading" style="margin-top:0;"><div><p class="eyebrow">REISSUE</p><h2>{'수정 요청' if str(meta.get('editorial_verdict') or '') in {'REVIEW', 'POOR'} else '다시 만들기'}</h2></div></div>
<p class="notice">재발행 결과는 운영자 검토용으로만 생성됩니다. 고객에게 자동 발송되지 않습니다.</p>
<form method="post" action="/admin/runs/{_esc(run_id)}/reissue">
{_csrf_field(request, f'reissue:{run_id}')}
<label>재발행 범위<br>
{scope_field}
</label><br>
<label>사유<br>
{_render_reissue_reason_select(mode)}
</label><br><br>
<label>추가 메모 (선택)<br>
<input type="text" name="reason_note" maxlength="500" placeholder="선택 사유 보완">
</label><br><br>
{_render_reissue_dry_run_field(mode)}
<div class="form-actions"><button class="btn" type="submit">재발행 실행</button></div>
</form>
</section>
<details class="technical-details"><summary>비용 추정 보기</summary><div class="technical-details__body">{cost_section}</div></details>
{technical}
<nav class="surface" aria-label="운영 보조 메뉴" style="margin-top:18px;display:flex;flex-wrap:wrap;gap:12px 18px;">{email_link}<a href="/admin/customer-recipients">베타 고객 수신자 관리</a><a href="/admin/notices">고객 공지 메일</a></nav>
"""
    memory.record("after_projection")
    return _finish_heavy_admin_projection(
        memory,
        title=f"Review {run_id}",
        inner=inner,
        active="reviews",
    )


@router.post("/admin/runs/{run_id}/hold")
def admin_run_hold(
    request: Request,
    run_id: str,
    hold_note: str = Form(""),
    csrf_token: str = Form(""),
):
    need = _require_login(request)
    if need is not None:
        return need
    if not _verify_csrf(request, f"hold:{run_id}", csrf_token):
        return _csrf_rejected()
    updated, status = hold_run(run_id, note=hold_note, operator_id=_operator_id(request))
    append_operator_audit(
        "review_hold",
        operator_id=_operator_id(request),
        run_id=run_id,
        result="held" if updated else "blocked",
        reason_code="" if updated else status,
    )
    return RedirectResponse(url=f"/admin/runs/{run_id}", status_code=303)


@router.post("/admin/runs/{run_id}/reopen")
def admin_run_reopen(
    request: Request,
    run_id: str,
    csrf_token: str = Form(""),
):
    need = _require_login(request)
    if need is not None:
        return need
    if not _verify_csrf(request, f"reopen:{run_id}", csrf_token):
        return _csrf_rejected()
    updated, status = reopen_held_run(run_id, operator_id=_operator_id(request))
    append_operator_audit(
        "review_reopened",
        operator_id=_operator_id(request),
        run_id=run_id,
        result="reopened" if updated else "blocked",
        reason_code="" if updated else status,
    )
    return RedirectResponse(url=f"/admin/runs/{run_id}", status_code=303)


@router.get("/admin/runs/{run_id}/email", response_class=HTMLResponse)
def admin_run_email_preview(request: Request, run_id: str):
    need = _require_login(request)
    if need is not None:
        return need
    memory, deferred = _begin_heavy_admin_projection(
        title="Email preview", active="reviews"
    )
    if deferred is not None:
        return deferred
    if not validate_run_id(run_id):
        return HTMLResponse("<p>잘못된 run_id</p>", status_code=404)
    meta = load_run_artifact(run_id)
    content = load_run_email_html(run_id)
    if content is None or meta is None:
        return HTMLResponse(
            _layout("Email missing", "<p>저장된 이메일 HTML이 없습니다.</p>"),
            status_code=404,
        )
    snapshot_id = str(request.query_params.get("approval_snapshot_id") or "").strip()
    if snapshot_id:
        from admin_approval import ApprovalTargetError, verify_approval_snapshot

        try:
            _snapshot, prepared = verify_approval_snapshot(
                snapshot_id=snapshot_id,
                run_id=run_id,
                meta=meta,
                saved_html=content,
                operator_id=_operator_id(request),
            )
        except ApprovalTargetError as exc:
            return HTMLResponse(
                _layout(
                    "Preview unavailable",
                    f'<p class="warn">현재 승인 대상 미리보기를 열 수 없습니다: {_esc(exc.code)}</p>',
                    active="reviews",
                ),
                status_code=409,
            )
        content = prepared.customer_html
    memory.record("after_projection")

    def observed_preview_stream():
        memory.record("after_template")
        try:
            yield from stream_customer_html_for_admin_preview(run_id, meta, content)
        finally:
            memory.record("route_end")

    return StreamingResponse(
        observed_preview_stream(),
        media_type="text/html; charset=utf-8",
        headers={
            "Cache-Control": "private, no-store",
            "Content-Security-Policy": "default-src 'none'; img-src 'self' data: https:; style-src 'unsafe-inline'",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/admin/runs/{run_id}/json")
def admin_run_raw_json(request: Request, run_id: str):
    """Explicit detail-only raw view, isolated from the normal HTML projection."""
    need = _require_login(request)
    if need is not None:
        return need
    memory, deferred = _begin_heavy_admin_projection(
        title="Raw run JSON", active="reviews"
    )
    if deferred is not None:
        return deferred
    if not validate_run_id(run_id):
        return Response(status_code=404)
    meta = load_run_artifact(run_id)
    if meta is None:
        return Response(status_code=404)
    memory.record("after_projection")
    content = json.dumps(meta, ensure_ascii=False, indent=2, default=str)
    memory.record("after_template")
    response = Response(
        content=content,
        media_type="application/json; charset=utf-8",
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )
    memory.record("route_end")
    return response


@router.get("/admin/runs/{run_id}/preview-assets/{slot}")
def admin_run_preview_asset(request: Request, run_id: str, slot: str):
    """Authenticated exact-run image stream for browser-only CID preview resolution."""
    need = _require_login(request)
    if need is not None:
        return need
    memory = MemoryEvidenceRecorder()
    memory.record("route_start")
    if active_natural_run_snapshot().get("active"):
        memory.record("after_projection")
        memory.record("after_template")
        response = Response(
            status_code=503,
            headers={
                "Retry-After": "30",
                "X-Genie-Admin-Projection": "deferred",
            },
        )
        memory.record("route_end")
        return response
    if not validate_run_id(run_id) or slot not in {"top", "bottom"}:
        return Response(status_code=404)
    meta = load_run_artifact(run_id)
    if not meta:
        return Response(status_code=404)
    payload, media_type = read_preview_asset(run_id, meta, slot)
    if payload is None or media_type is None:
        return Response(status_code=404)
    memory.record("after_projection")
    memory.record("after_template")
    response = Response(
        content=payload,
        media_type=media_type,
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )
    memory.record("route_end")
    return response


@router.get("/admin/runs/{run_id}/approve-confirm", response_class=HTMLResponse)
def admin_run_approve_confirm(request: Request, run_id: str):
    need = _require_login(request)
    if need is not None:
        return need
    memory, deferred = _begin_heavy_admin_projection(
        title="Approve", active="reviews"
    )
    if deferred is not None:
        return deferred
    if not validate_run_id(run_id):
        return HTMLResponse(_layout("Not found", "<p>잘못된 run_id</p>"), status_code=404)
    meta = load_run_artifact(run_id)
    if not meta:
        return HTMLResponse(_layout("Not found", "<p>실행 기록을 찾을 수 없습니다.</p>"), status_code=404)
    email_html = load_run_email_html(run_id)
    has_email = email_html is not None
    can_approve, approve_err = can_approve_customer_send(meta, has_email_html=has_email)
    if not can_approve:
        msg = _APPROVE_ERROR_MESSAGES.get(approve_err, approve_err)
        inner = f"<p>{_esc(msg)}</p><p><a href=\"/admin/runs/{_esc(run_id)}\">돌아가기</a></p>"
        return HTMLResponse(_layout("Approve blocked", inner), status_code=400)
    from admin_approval import ApprovalTargetError, create_approval_snapshot

    operator_id = _operator_id(request)
    try:
        snapshot, prepared = create_approval_snapshot(
            run_id=run_id,
            meta=meta,
            saved_html=email_html or "",
            operator_id=operator_id,
        )
    except ApprovalTargetError as exc:
        msg = _APPROVE_ERROR_MESSAGES.get(exc.code, exc.code)
        return HTMLResponse(
            _layout("Approve blocked", f'<div class="warn">{_esc(msg)}</div><p><a href="/admin/runs/{_esc(run_id)}">돌아가기</a></p>'),
            status_code=400,
        )
    append_operator_audit(
        "approval_snapshot_created",
        operator_id=operator_id,
        run_id=run_id,
        result="created",
        related_id=str(snapshot["approval_snapshot_id"]),
        metadata={
            "recipient_count": snapshot["recipient_count"],
            "recipient_configuration_version": snapshot["recipient_configuration_version"],
        },
    )
    prepared_subject = prepared.subject
    approval_snapshot_id = str(snapshot["approval_snapshot_id"])
    warning_confirmation_required = bool(snapshot.get("warning_confirmation_required"))
    # The preview is served separately.  Do not retain either large HTML body
    # while constructing the confirmation-page projection.
    del prepared
    del email_html
    session_token = _session_token_from_request(request)
    nonce, cookie_value = issue_approval_nonce(run_id, session_token)
    recipient_count = int(snapshot["recipient_count"])
    recipients_ok = True
    view = run_projection(meta, current_recipient_count=recipient_count)
    delivery = view["delivery"]
    recipient_label = f"{recipient_count}명" if recipients_ok else "수신자 설정 확인 필요"
    recipient_items = "".join(f"<li>{_esc(item)}</li>" for item in snapshot.get("recipients_masked") or [])
    image_items = "".join(
        f'<li>{_esc(row.get("position"))}: {_esc(row.get("filename"))}</li>'
        for row in snapshot.get("images") or []
    )
    memory.record("after_projection")
    inner = f"""
{_ui_page_header('고객 발송 최종 확인', '이 정확한 브리핑을 아래의 정확한 수신자에게 발송합니다.', view['program']['display'])}
<section class="surface"><div class="metrics">
{_ui_metric('실제 제목', prepared_subject)}
{_ui_metric('고정 수신자', recipient_label)}
{_ui_metric('기존 발송 상태', delivery['label_ko'], delivery['label'])}
{_ui_metric('확인 스냅샷', snapshot['approval_snapshot_id'])}
</div></section>
{_admin_email_preview_for_run(run_id, title='지금 발송할 최종 브리핑', approval_snapshot_id=approval_snapshot_id)}
<section class="surface"><div class="section-heading" style="margin-top:0"><div><p class="eyebrow">WHO RECEIVES IT</p><h2>고정된 수신 대상</h2></div></div><p><strong>{recipient_label}</strong></p><ul>{recipient_items}</ul><h3>최종 이미지</h3><ul>{image_items}</ul></section>
<div class="notice notice--danger"><strong>주의</strong> — 승인 시 이 정확한 브리핑이 이 정확한 수신자에게 즉시 제출되며 되돌릴 수 없습니다. 콘텐츠·이미지·수신자 설정이 바뀌면 발송은 <code>APPROVAL_TARGET_CHANGED</code>로 차단되며 재확인이 필요합니다.</div>
<form method="post" action="/admin/runs/{_esc(run_id)}/approve">
<input type="hidden" name="{_esc(APPROVE_NONCE_FORM_FIELD)}" value="{_esc(nonce)}">
<input type="hidden" name="{_esc(APPROVAL_SNAPSHOT_FORM_FIELD)}" value="{_esc(snapshot['approval_snapshot_id'])}">
{_csrf_field(request, f'approve:{run_id}')}
<label>승인 메모 (선택)<br>
<input type="text" name="approve_note" maxlength="500" placeholder="승인 메모">
</label><br><br>
<label style="display:block;margin:0 0 16px 0;">
<input type="checkbox" name="{_esc(CUSTOMER_SEND_CONFIRM_FIELD)}" value="1" required>
고객 이메일 발송을 승인합니다
</label>
{"" if not warning_confirmation_required else f'''<label style="display:block;margin:0 0 16px 0;"><input type="checkbox" name="{_esc(REVIEW_WARNING_CONFIRM_FIELD)}" value="1" required> 편집 경고를 확인했으며 이 상태로 고객 발송하는 데 동의합니다</label>'''}
<div class="form-actions"><button class="btn btn--danger" type="submit">승인하고 {_esc(recipient_label)}에게 발송</button></div>
</form>
<p><a href="/admin/runs/{_esc(run_id)}">← 실행 상세</a></p>
<details class="technical-details"><summary>기술 세부정보 보기</summary><div class="technical-details__body"><div class="diagnostic-grid"><div class="diagnostic-row"><span>Run ID</span><code>{_esc(run_id)}</code></div><div class="diagnostic-row"><span>mode</span><code>{_esc(meta.get('mode'))}</code></div><div class="diagnostic-row"><span>content hash</span><code>{_esc(snapshot.get('rendered_content_sha256'))}</code></div><div class="diagnostic-row"><span>recipient config hash</span><code>{_esc(snapshot.get('recipient_configuration_hash'))}</code></div></div></div></details>
"""
    page = _layout(f"Approve {run_id}", inner, active="reviews")
    memory.record("after_template")
    resp = HTMLResponse(page)
    resp.set_cookie(
        APPROVE_NONCE_COOKIE,
        cookie_value,
        httponly=True,
        secure=_admin_cookie_secure(),
        samesite="lax",
        max_age=APPROVE_NONCE_TTL_SECONDS,
        path="/",
    )
    memory.record("route_end")
    return resp


@router.post("/admin/runs/{run_id}/approve")
def admin_run_approve(
    request: Request,
    run_id: str,
    approve_note: str = Form(""),
    approve_nonce: str = Form(""),
    customer_send_confirm: str = Form(""),
    review_warning_confirm: str = Form(""),
    approval_snapshot_id: str = Form(""),
    csrf_token: str = Form(""),
):
    need = _require_login(request)
    if need is not None:
        return need
    if not validate_run_id(run_id):
        return HTMLResponse(_layout("Not found", "<p>잘못된 run_id</p>"), status_code=404)
    if not _verify_csrf(request, f"approve:{run_id}", csrf_token):
        return _csrf_rejected()

    def _reject(code: str, *, consume_nonce: bool = True) -> RedirectResponse:
        resp = RedirectResponse(
            url=f"/admin/runs/{run_id}?approve_error={code}",
            status_code=303,
        )
        if consume_nonce:
            _clear_approval_nonce_cookie(resp)
        return resp

    if not str(customer_send_confirm or "").strip():
        return _reject("missing_customer_send_confirm", consume_nonce=False)

    cookie_value = str(request.cookies.get(APPROVE_NONCE_COOKIE, "") or "")
    session_token = _session_token_from_request(request)
    nonce_ok, nonce_err = verify_approval_nonce(run_id, approve_nonce, cookie_value, session_token)
    if not nonce_ok:
        return _reject(nonce_err)

    cleaned_note = approve_note.strip()
    client_ip = _request_client_ip(request)
    user_agent = str(request.headers.get("user-agent", "") or "")
    approval_audit = {
        "approved_from_ip": client_ip or None,
        "approved_user_agent": user_agent or None,
        "approval_channel": "browser_confirm",
        "approval_confirmed_at": now_kst_iso(),
        "approval_note": cleaned_note or None,
        "approval_nonce_used": True,
    }
    updated, status = approve_run(
        run_id,
        note=approve_note,
        approval_snapshot_id=approval_snapshot_id,
        operator_id=_operator_id(request),
        approval_audit=approval_audit,
        review_warning_confirmed=bool(str(review_warning_confirm or "").strip()),
    )
    if status != "ok" or not updated:
        code = status if status in _APPROVE_ERROR_MESSAGES else "send_failed"
        return _reject(code)

    mode = str(updated.get("mode") or "")
    logger.info(
        "customer_approval_success run_id=%s mode=%s approval_channel=%s ip=%s user_agent=%s",
        run_id,
        mode,
        approval_audit["approval_channel"],
        client_ip,
        user_agent,
    )
    resp = RedirectResponse(url=f"/admin/runs/{run_id}", status_code=303)
    _clear_approval_nonce_cookie(resp)
    return resp


@router.post("/admin/runs/{run_id}/reissue")
def admin_run_reissue(
    request: Request,
    run_id: str,
    reason_option: str = Form(...),
    reason_note: str = Form(""),
    reissue_scope: str = Form(""),
    dry_run_no_send: str = Form(""),
    csrf_token: str = Form(""),
):
    need = _require_login(request)
    if need is not None:
        return need
    if not validate_run_id(run_id):
        return HTMLResponse(_layout("Not found", "<p>잘못된 run_id</p>"), status_code=404)
    if not _verify_csrf(request, f"reissue:{run_id}", csrf_token):
        return _csrf_rejected()
    parent = load_run_artifact(run_id)
    if not parent:
        return HTMLResponse(_layout("Not found", "<p>원본 실행 기록을 찾을 수 없습니다.</p>"), status_code=404)

    mode = str(parent.get("mode") or parent.get("program_id") or "").strip()
    append_operator_audit(
        "reissue_requested",
        operator_id=_operator_id(request),
        run_id=run_id,
        result="requested",
        metadata={
            "mode": mode,
            "reissue_scope": str(reissue_scope or ""),
            "dry_run_no_send": _is_dry_run_no_send(dry_run_no_send),
        },
    )
    if mode not in ("today_genie", "tomorrow_genie", "keysuri_global_tech", "keysuri_korea_tech"):
        return _render_reissue_failure_page(
            title="Reissue failed",
            run_id=run_id,
            mode=mode,
            failed_step="mode_validation",
            safe_message="알 수 없는 mode로는 재발행을 실행할 수 없습니다.",
            status_code=400,
        )

    parent_block = reissue_parent_block_reason(parent)
    if parent_block is not None:
        return _render_reissue_failure_page(
            title="Reissue blocked",
            run_id=run_id,
            mode=mode,
            failed_step="parent_eligibility",
            safe_message=_REISSUE_PARENT_BLOCK_MESSAGES[parent_block],
            status_code=400,
        )

    raw_scope = str(reissue_scope or "").strip()
    if not raw_scope:
        return RedirectResponse(
            url=f"/admin/runs/{run_id}?reissue_error=missing_reissue_scope",
            status_code=303,
        )
    # Accept legacy text_only/text_and_image aliases for backward compatibility
    # with stale forms/automation; canonicalize to body_only/body_and_image.
    scope = normalize_reissue_scope(raw_scope)
    if scope is None or scope not in REISSUE_SCOPES:
        return RedirectResponse(
            url=f"/admin/runs/{run_id}?reissue_error=invalid_reissue_scope",
            status_code=303,
        )
    if scope in UNSUPPORTED_REISSUE_SCOPES:
        return RedirectResponse(
            url=f"/admin/runs/{run_id}?reissue_error=unsupported_reissue_scope",
            status_code=303,
        )
    reason_code = reason_option.strip()
    note = reason_note.strip()
    # Only honor the QA dry-run for modes whose reissue path supports a no-send run.
    dry_run = _is_dry_run_no_send(dry_run_no_send) and mode in _DRY_RUN_REISSUE_MODES

    if mode in ("keysuri_global_tech", "keysuri_korea_tech"):
        if scope == "body_only" and not _mode_supports_body_only_reissue(mode):
            return RedirectResponse(
                url=f"/admin/runs/{run_id}?reissue_error=unsupported_reissue_scope",
                status_code=303,
            )
        if scope == "image_only" and not _mode_supports_image_only_reissue(mode):
            return RedirectResponse(
                url=f"/admin/runs/{run_id}?reissue_error=unsupported_reissue_scope",
                status_code=303,
            )
        if scope == "body_and_image" and not _mode_supports_body_and_image_reissue(mode):
            return RedirectResponse(
                url=f"/admin/runs/{run_id}?reissue_error=unsupported_reissue_scope",
                status_code=303,
            )
        runner = {
            "body_only": run_keysuri_text_only_reissue,
            "image_only": run_keysuri_image_only_reissue,
            "body_and_image": run_keysuri_text_and_image_reissue,
        }.get(scope)
        if runner is None:
            return RedirectResponse(
                url=f"/admin/runs/{run_id}?reissue_error=invalid_reissue_scope",
                status_code=303,
            )
        try:
            result = runner(
                run_id,
                parent_meta=parent,
                reissue_reason_code=reason_code,
                reissue_reason_note=note,
                send_owner_email=not dry_run,
            )
        except Exception:  # noqa: BLE001
            # Log the full traceback server-side for diagnosis; never surface the
            # raw exception type/message on the operator screen.
            logger.exception(
                "keysuri reissue execution failed: run_id=%s scope=%s dry_run=%s",
                run_id,
                scope,
                dry_run,
            )
            return _render_reissue_failure_page(
                title="Reissue error",
                run_id=run_id,
                mode=mode,
                failed_step="keysuri_reissue_execution",
                safe_message=(
                    "재발행 실행 중 오류가 발생했습니다. "
                    "safe_error_code=keysuri_reissue_execution_error"
                ),
                status_code=200,
                dry_run=dry_run,
            )
        new_run_id = str(result.get("run_id") or "").strip()
        # QA dry-run: the pipeline ran without dispatching the owner-review email.
        # Record the no-send markers on the new child and surface a dry-run page.
        if dry_run and new_run_id and not result.get("error"):
            _apply_dry_run_reissue_metadata(new_run_id)
            return RedirectResponse(
                url=f"/admin/runs/{new_run_id}?reissue_dry_run=1",
                status_code=303,
            )
        if new_run_id and not result.get("email_sent") and not result.get("error"):
            return RedirectResponse(
                url=f"/admin/runs/{new_run_id}?reissue_warn=email_not_sent",
                status_code=303,
            )
        if not result.get("ok") or not new_run_id:
            error_code = str(result.get("error") or "keysuri_reissue_failed")
            safe_code = _safe_reissue_result_error_code(error_code)
            logger.warning(
                "keysuri reissue result validation failed: run_id=%s scope=%s dry_run=%s error=%s safe_error_code=%s content_codes=%s",
                run_id,
                scope,
                dry_run,
                error_code,
                safe_code,
                result.get("reissue_top5_content_issue_codes"),
            )
            return _render_reissue_failure_page(
                title="Reissue failed",
                run_id=run_id,
                mode=mode,
                failed_step="keysuri_reissue_result_validation",
                safe_message=(
                    "재발행 결과 검증 실패로 발송하지 않았습니다. "
                    f"safe_error_code={safe_code}"
                ),
                status_code=200,
                dry_run=dry_run,
            )
        return RedirectResponse(url=f"/admin/runs/{new_run_id}", status_code=303)

    if mode == "today_genie" and scope in ("body_only", "image_only"):
        if scope == "body_only" and not _mode_supports_body_only_reissue(mode):
            return RedirectResponse(
                url=f"/admin/runs/{run_id}?reissue_error=unsupported_reissue_scope",
                status_code=303,
            )
        if scope == "image_only" and not _mode_supports_image_only_reissue(mode):
            return RedirectResponse(
                url=f"/admin/runs/{run_id}?reissue_error=unsupported_reissue_scope",
                status_code=303,
            )
        # image_only regenerates images from the run's stored image prompts; runs
        # recorded before prompt capture can only be reissued in full.
        if scope == "image_only" and not _today_run_supports_image_only_reissue(parent):
            return RedirectResponse(
                url=f"/admin/runs/{run_id}?reissue_error=today_image_prompt_snapshot_missing",
                status_code=303,
            )
        today_runner = {
            "body_only": run_today_body_only_reissue,
            "image_only": run_today_image_only_reissue,
        }[scope]
        try:
            result = today_runner(
                run_id,
                parent_meta=parent,
                reissue_reason_code=reason_code,
                reissue_reason_note=note,
                send_owner_email=not dry_run,
            )
        except Exception:  # noqa: BLE001
            # Log the full traceback server-side; never surface raw exception text.
            logger.exception(
                "today scoped reissue execution failed: run_id=%s scope=%s dry_run=%s",
                run_id,
                scope,
                dry_run,
            )
            return _render_reissue_failure_page(
                title="Reissue error",
                run_id=run_id,
                mode=mode,
                failed_step="today_scoped_reissue_execution",
                safe_message=(
                    "재발행 실행 중 오류가 발생했습니다. "
                    "safe_error_code=today_scoped_reissue_execution_error"
                ),
                status_code=200,
                dry_run=dry_run,
            )
        new_run_id = str(result.get("run_id") or "").strip()
        if new_run_id and not result.get("error"):
            record_parent_reissue_audit(
                run_id,
                child_run_id=new_run_id,
                reissue_scope=scope,
            )
        if dry_run and new_run_id and not result.get("error"):
            _apply_dry_run_reissue_metadata(new_run_id)
            return RedirectResponse(
                url=f"/admin/runs/{new_run_id}?reissue_dry_run=1",
                status_code=303,
            )
        if new_run_id and not result.get("email_sent") and not result.get("error"):
            return RedirectResponse(
                url=f"/admin/runs/{new_run_id}?reissue_warn=email_not_sent",
                status_code=303,
            )
        if not result.get("ok") or not new_run_id:
            safe_code = _safe_reissue_result_error_code(
                str(result.get("error") or "today_reissue_failed")
            )
            return _render_reissue_failure_page(
                title="Reissue failed",
                run_id=run_id,
                mode=mode,
                failed_step="today_scoped_reissue_result_validation",
                safe_message=(
                    "재발행 결과 검증 실패로 발송하지 않았습니다. "
                    f"safe_error_code={safe_code}"
                ),
                status_code=200,
                dry_run=dry_run,
            )
        return RedirectResponse(url=f"/admin/runs/{new_run_id}", status_code=303)

    if scope != EXECUTABLE_REISSUE_SCOPE:
        return RedirectResponse(
            url=f"/admin/runs/{run_id}?reissue_error=invalid_reissue_scope",
            status_code=303,
        )

    reason = reason_code
    if note:
        reason = f"{reason} — {note}"

    try:
        new_run_id, _result, email_sent = execute_orchestrator_run(
            mode,
            parent_run_id=run_id,
            reissue_reason=reason,
            admin_reissue=True,
            send_owner_email=not dry_run,
        )
    except Exception as exc:  # noqa: BLE001
        return _render_reissue_failure_page(
            title="Reissue error",
            run_id=run_id,
            mode=mode,
            failed_step="orchestrator_reissue_execution",
            safe_message=f"재발행 실행 중 오류가 발생했습니다 ({type(exc).__name__}).",
            status_code=500,
        )

    if not new_run_id:
        return _render_reissue_failure_page(
            title="Reissue failed",
            run_id=run_id,
            mode=mode,
            failed_step="orchestrator_reissue_persist",
            safe_message="재발행 아티팩트를 저장하지 못했습니다.",
            status_code=500,
        )

    apply_reissue_child_metadata(
        new_run_id,
        reissue_scope=scope,
        reissue_reason_code=reason_code,
        reissue_reason_note=note,
        reissue_scope_status="executed",
    )
    record_parent_reissue_audit(
        run_id,
        child_run_id=new_run_id,
        reissue_scope=scope,
    )

    if dry_run:
        _apply_dry_run_reissue_metadata(new_run_id)
        return RedirectResponse(
            url=f"/admin/runs/{new_run_id}?reissue_dry_run=1",
            status_code=303,
        )

    if not email_sent:
        return RedirectResponse(
            url=f"/admin/runs/{new_run_id}?reissue_warn=email_not_sent",
            status_code=303,
        )
    return RedirectResponse(url=f"/admin/runs/{new_run_id}", status_code=303)


# ---------------------------------------------------------------------------
# Beta customer recipient management
# ---------------------------------------------------------------------------

def _render_customer_recipients_page(
    request: Request,
    *,
    error: str = "",
    success: str = "",
) -> HTMLResponse:
    resolved = resolve_customer_recipients()
    cfg = load_beta_recipient_config()

    env_addrs = resolved["env_recipients"]
    admin_addrs = resolved["admin_recipients"]
    final_addrs = resolved["final_recipients"]
    invalid = resolved["invalid_entries"]
    source_summary = resolved["source_summary"]
    updated_at = cfg.get("updated_at") or "—"

    # env recipients table (read-only)
    env_rows = "".join(
        f"<tr><td>{_esc(a)}</td><td style='color:#64748b;font-size:13px'>env (GENIE_CUSTOMER_EMAIL_TO)</td></tr>"
        for a in env_addrs
    ) or "<tr><td colspan='2' style='color:#94a3b8'>환경변수 미설정</td></tr>"

    # admin-managed recipients table with remove button
    admin_rows_html = ""
    for a in admin_addrs:
        admin_rows_html += (
            f"<tr><td>{_esc(a)}</td>"
            f"<td>"
            f"<form method='post' action='/admin/customer-recipients/remove' style='margin:0'>"
            f"{_csrf_field(request, 'recipient_remove')}"
            f"<input type='hidden' name='email' value='{_esc(a)}'>"
            f"<button type='submit' class='btn' style='background:#dc2626;padding:6px 12px;font-size:13px;min-height:32px;'>삭제</button>"
            f"</form>"
            f"</td></tr>"
        )
    if not admin_rows_html:
        admin_rows_html = "<tr><td colspan='2' style='color:#94a3b8'>관리 추가 수신자 없음</td></tr>"

    # invalid entries warning
    invalid_html = ""
    if invalid:
        items = "".join(f"<li>{_esc(e['email'])} — {_esc(e['reason'])}</li>" for e in invalid)
        invalid_html = f"<div class='warn' style='margin:12px 0'><strong>유효하지 않은 주소 (무시됨):</strong><ul>{items}</ul></div>"

    error_html = f"<div class='warn' style='margin:8px 0'>{_esc(error)}</div>" if error else ""
    success_html = (
        f"<div style='background:#f0fdf4;border:1px solid #86efac;padding:12px;border-radius:8px;margin:8px 0;font-size:14px'>{_esc(success)}</div>"
        if success
        else ""
    )

    inner = f"""
<div class="page-head"><h1>베타 고객 수신자 관리</h1>
<a href="/admin/runs" class="btn">← 실행 목록</a></div>

<div class="card">
<p style="font-size:14px;color:#64748b;margin:0 0 8px">
  최종 수신자 <strong>{len(final_addrs)}명</strong> &nbsp;|&nbsp;
  env 기본 <strong>{len(env_addrs)}명</strong> &nbsp;|&nbsp;
  어드민 추가 <strong>{len(admin_addrs)}명</strong> &nbsp;|&nbsp;
  출처: <code>{_esc(source_summary)}</code>
</p>
<p style="font-size:13px;color:#dc2626;font-weight:600;margin:0">
  ⚠️ 저장만으로 발송되지 않습니다. 다음 고객 발송부터 적용됩니다.
</p>
</div>

{error_html}{success_html}

<div class="card">
<h2 style="font-size:16px;margin:0 0 12px">환경변수 기본 수신자 (읽기 전용)</h2>
<div class="table-wrap"><table>
<thead><tr><th>이메일</th><th>출처</th></tr></thead>
<tbody>{env_rows}</tbody>
</table></div>
</div>

<div class="card">
<h2 style="font-size:16px;margin:0 0 4px">어드민 관리 추가 수신자</h2>
<p style="font-size:13px;color:#64748b;margin:0 0 12px">마지막 수정: {_esc(updated_at)}</p>
<div class="table-wrap"><table>
<thead><tr><th>이메일</th><th>액션</th></tr></thead>
<tbody>{admin_rows_html}</tbody>
</table></div>
</div>

{invalid_html}

<div class="card">
<h2 style="font-size:16px;margin:0 0 12px">수신자 추가</h2>
<form method="post" action="/admin/customer-recipients/add">
{_csrf_field(request, 'recipient_add')}
<label for="new-email" style="display:block;font-size:14px;font-weight:600;margin:0 0 6px">이메일 주소</label>
<input type="text" id="new-email" name="email" placeholder="example@domain.com"
  style="max-width:360px;margin-bottom:12px;" autocomplete="off" autocapitalize="none">
<div class="form-actions">
<button type="submit" class="btn">추가</button>
</div>
</form>
<p style="font-size:12px;color:#64748b;margin:12px 0 0">
  추가 후 즉시 발송되지 않습니다. 다음 고객 승인 발송 시 적용됩니다.
</p>
</div>
"""
    return HTMLResponse(_layout("베타 고객 수신자 관리", inner))


@router.get("/admin/customer-recipients", response_class=HTMLResponse)
def admin_customer_recipients(request: Request) -> HTMLResponse:
    gate = _require_login(request)
    if gate is not None:
        return gate  # type: ignore[return-value]
    return _render_customer_recipients_page(request)


@router.post("/admin/customer-recipients/add")
def admin_customer_recipients_add(
    request: Request,
    email: str = Form(...),
    csrf_token: str = Form(""),
) -> Response:
    gate = _require_login(request)
    if gate is not None:
        return gate  # type: ignore[return-value]
    if not _verify_csrf(request, "recipient_add", csrf_token):
        return _csrf_rejected()
    ok, err = add_beta_recipient(email)
    if not ok:
        _error_labels = {
            "empty_email": "이메일 주소를 입력하세요.",
            "invalid_format": "유효하지 않은 이메일 형식입니다.",
            "already_exists": "이미 목록에 있는 주소입니다.",
            "config_unavailable": "수신자 설정을 읽을 수 없어 저장을 중단했습니다. 잠시 후 다시 시도하세요.",
        }
        return _render_customer_recipients_page(
            request, error=_error_labels.get(err, f"추가 실패: {err}")
        )
    append_operator_audit(
        "recipient_config_changed",
        operator_id=_operator_id(request),
        result="recipient_added",
        metadata={"new_count": len(resolve_customer_recipients().get("final_recipients") or [])},
    )
    return RedirectResponse(url="/admin/customer-recipients?added=1", status_code=303)


@router.post("/admin/customer-recipients/remove")
def admin_customer_recipients_remove(
    request: Request,
    email: str = Form(...),
    csrf_token: str = Form(""),
) -> Response:
    gate = _require_login(request)
    if gate is not None:
        return gate  # type: ignore[return-value]
    if not _verify_csrf(request, "recipient_remove", csrf_token):
        return _csrf_rejected()
    ok, err = remove_beta_recipient(email)
    if not ok:
        _error_labels = {
            "empty_email": "이메일 주소를 입력하세요.",
            "not_found": "목록에 없는 주소입니다.",
            "config_unavailable": "수신자 설정을 읽을 수 없어 삭제를 중단했습니다. 잠시 후 다시 시도하세요.",
        }
        return _render_customer_recipients_page(
            request, error=_error_labels.get(err, f"삭제 실패: {err}")
        )
    append_operator_audit(
        "recipient_config_changed",
        operator_id=_operator_id(request),
        result="recipient_removed",
        metadata={"new_count": len(resolve_customer_recipients().get("final_recipients") or [])},
    )
    return RedirectResponse(url="/admin/customer-recipients?removed=1", status_code=303)


# ---------------------------------------------------------------------------
# Admin operational customer notices (separate from briefing approve_run)
# ---------------------------------------------------------------------------

_NOTICE_SEND_ERROR_MESSAGES = {
    "not_found": "공지를 찾을 수 없습니다.",
    "not_previewed": "미리보기를 먼저 완료해야 발송할 수 있습니다.",
    "confirm_mismatch": "발송 확인 문구가 일치하지 않습니다.",
}


def _notice_status_label(status: str) -> str:
    return {
        "draft": "초안",
        "previewed": "미리보기 완료",
        "sent": "발송 완료",
        "failed": "발송 실패",
    }.get(status, status)


@router.get("/admin/notices", response_class=HTMLResponse)
def admin_notices_list(request: Request):
    need = _require_login(request)
    if need is not None:
        return need
    page = list_notice_page(
        limit=ADMIN_UI_PAGE_SIZE,
        cursor=_admin_list_cursor(request),
    )
    notices = page["items"]
    rows = []
    for n in notices:
        nid = _esc(n.get("notice_id"))
        rows.append(
            "<tr>"
            f"<td><a href=\"/admin/notices/{nid}\">{nid}</a></td>"
            f"<td>{_esc(_NOTICE_TYPE_LABELS.get(n.get('notice_type'), n.get('notice_type')))}</td>"
            f"<td>{_esc(n.get('program_id'))}</td>"
            f"<td>{_esc(_notice_status_label(str(n.get('status') or '')))}</td>"
            f"<td>{_esc(n.get('recipients_count'))}</td>"
            f"<td>{_esc(n.get('created_at'))}</td>"
            "</tr>"
        )
    table = (
        "<table><thead><tr>"
        "<th>notice_id</th><th>유형</th><th>프로그램</th><th>상태</th><th>수신자 수</th><th>생성 시각</th>"
        "</tr></thead><tbody>"
        + ("".join(rows) if rows else "<tr><td colspan=\"6\">저장된 공지가 없습니다.</td></tr>")
        + "</tbody></table>"
    )
    inner = f"""
<div class="page-head">
<h1>운영 공지 관리</h1>
<a href="/admin/notices/new" class="btn">새 공지 작성</a>
</div>
<p style="font-size:13px;color:#64748b;">브리핑 고객 최종 발송(approve)과 완전히 분리된 별도 기능입니다.</p>
<div class="card"><div class="table-wrap">{table}</div></div>
{_admin_pagination_controls('/admin/notices', page)}
<p><a href="/admin/runs">← 실행 목록</a></p>
"""
    return HTMLResponse(_layout("운영 공지", inner))


@router.get("/admin/notices/new", response_class=HTMLResponse)
def admin_notice_new(request: Request):
    need = _require_login(request)
    if need is not None:
        return need

    from admin_notice_store import DEFAULT_NOTICE_PROGRAM, notice_template

    selected_type = str(request.query_params.get("notice_type") or "quality_check_notice")
    if selected_type not in NOTICE_TYPES:
        selected_type = "quality_check_notice"
    # A notice reached from a degraded program arrives scoped to that program, so
    # the wording names the affected service instead of defaulting to Global.
    selected_program = str(request.query_params.get("program_id") or "").strip()
    valid_programs = {pid for pid, _label in NOTICE_PROGRAM_OPTIONS}
    if selected_program not in valid_programs:
        selected_program = DEFAULT_NOTICE_PROGRAM
    template = notice_template(selected_type, selected_program)

    type_links = " ".join(
        f'<a class="btn" style="background:{"#0f172a" if t == selected_type else "#94a3b8"};" '
        f'href="/admin/notices/new?notice_type={t}&program_id={_esc(selected_program)}">'
        f'{_esc(_NOTICE_TYPE_LABELS.get(t, t))}</a>'
        for t in NOTICE_TYPES
    )
    type_options = "".join(
        f'<option value="{t}" {"selected" if t == selected_type else ""}>'
        f'{_esc(_NOTICE_TYPE_LABELS.get(t, t))}</option>'
        for t in NOTICE_TYPES
    )
    program_options = "".join(
        f'<option value="{pid}" {"selected" if pid == selected_program else ""}>'
        f'{_esc(label)}</option>'
        for pid, label in NOTICE_PROGRAM_OPTIONS
    )

    inner = f"""
<div class="page-head"><h1>새 운영 공지 작성</h1>
<a href="/admin/notices" class="btn">← 공지 목록</a></div>
<p style="font-size:13px;color:#64748b;">템플릿 선택:</p>
<p>{type_links}</p>
<div class="card">
<form method="post" action="/admin/notices/preview">
{_csrf_field(request, 'notice_preview')}
<label>공지 유형<br>
<select name="notice_type">{type_options}</select>
</label><br><br>
<label>대상 프로그램<br>
<select name="program_id">{program_options}</select>
</label><br><br>
<label>관련 run_id (선택)<br>
<input type="text" name="related_run_id" maxlength="120" placeholder="20260625_..._keysuri_global_tech_xxxxxxxx">
</label><br><br>
<label>제목<br>
<input type="text" name="subject" maxlength="200" value="{_esc(template['subject'])}" required>
</label><br><br>
<label>본문<br>
<textarea name="body_text" rows="8" required>{_esc(template['body_text'])}</textarea>
</label><br><br>
<div class="form-actions"><button class="btn" type="submit">미리보기 생성</button></div>
</form>
</div>
"""
    return HTMLResponse(_layout("새 운영 공지", inner))


@router.post("/admin/notices/preview", response_class=HTMLResponse)
def admin_notice_preview(
    request: Request,
    notice_type: str = Form(""),
    program_id: str = Form(""),
    related_run_id: str = Form(""),
    subject: str = Form(""),
    body_text: str = Form(""),
    csrf_token: str = Form(""),
):
    need = _require_login(request)
    if need is not None:
        return need
    if not _verify_csrf(request, "notice_preview", csrf_token):
        return _csrf_rejected()

    notice_type = str(notice_type or "").strip()
    if notice_type not in NOTICE_TYPES:
        return HTMLResponse(
            _layout("Invalid notice_type", "<p>알 수 없는 공지 유형입니다.</p><p><a href=\"/admin/notices/new\">돌아가기</a></p>"),
            status_code=400,
        )
    subject_clean = subject.strip()
    body_clean = body_text.strip()
    if not subject_clean or not body_clean:
        return HTMLResponse(
            _layout(
                "Missing fields",
                "<p>제목과 본문을 모두 입력하세요.</p><p><a href=\"/admin/notices/new\">돌아가기</a></p>",
            ),
            status_code=400,
        )

    body_html = render_notice_body_html(body_clean)
    notice = create_notice_draft(
        notice_type=notice_type,
        program_id=program_id,
        related_run_id=related_run_id.strip() or None,
        subject=subject_clean,
        body_text=body_clean,
        body_html=body_html,
    )

    # Preview only computes recipients_count/recipient_source — never the address list,
    # and never calls send_admin_notice_email().
    recipients = resolve_customer_recipients()["final_recipients"]
    notice = mark_previewed(
        notice,
        recipients_count=len(recipients),
        recipient_source=notice_recipient_source_label(),
    )

    nid = _esc(notice["notice_id"])
    inner = f"""
<div class="page-head"><h1>공지 미리보기</h1>
<a href="/admin/notices" class="btn">← 공지 목록</a></div>
<div class="card warn">
<p><strong>이 화면은 브리핑 발송이 아닙니다.</strong></p>
<p>고객 최종 승인(브리핑 approve)이 아닙니다.</p>
<p>수신자 이메일 주소는 visible MIME 헤더(To/Cc/Bcc)에 노출되지 않습니다.</p>
</div>
<div class="card">
<p>notice_id: <code>{nid}</code></p>
<p>유형: {_esc(_NOTICE_TYPE_LABELS.get(notice_type, notice_type))} &nbsp;|&nbsp; 프로그램: {_esc(program_id)}</p>
<p>수신자 수: <strong>{notice['recipients_count']}</strong> &nbsp;|&nbsp; 수신자 출처: <code>{_esc(notice['recipient_source'])}</code></p>
<p>수신자 공개 정책: <code>{_esc(notice['visible_recipient_policy'])}</code></p>
</div>
<div class="card">
<h2 style="font-size:16px;margin:0 0 12px">제목</h2>
<p>{_esc(notice['subject'])}</p>
<h2 style="font-size:16px;margin:16px 0 12px">고객에게 보일 본문</h2>
<div style="border:1px solid #e2e8f0;border-radius:8px;padding:12px;">{notice['body_html']}</div>
</div>
<div class="card">
<form method="post" action="/admin/notices/send">
{_csrf_field(request, f'notice_send:{notice["notice_id"]}')}
<input type="hidden" name="notice_id" value="{nid}">
<label>발송 확인 문구를 정확히 입력하세요: <code>{_esc(NOTICE_SEND_CONFIRM_PHRASE)}</code><br>
<input type="text" name="confirm" required>
</label><br><br>
<div class="form-actions"><button class="btn" type="submit">실제 발송</button></div>
</form>
</div>
"""
    return HTMLResponse(_layout("공지 미리보기", inner))


@router.post("/admin/notices/send")
def admin_notice_send(
    request: Request,
    notice_id: str = Form(""),
    confirm: str = Form(""),
    csrf_token: str = Form(""),
):
    need = _require_login(request)
    if need is not None:
        return need
    if not _verify_csrf(request, f"notice_send:{notice_id}", csrf_token):
        return _csrf_rejected()

    if not validate_notice_id(notice_id):
        return RedirectResponse(url="/admin/notices?notice_error=not_found", status_code=303)
    notice = load_notice(notice_id)
    if not notice:
        return RedirectResponse(url="/admin/notices?notice_error=not_found", status_code=303)
    if notice.get("status") != "previewed":
        return RedirectResponse(
            url=f"/admin/notices/{notice_id}?notice_error=not_previewed", status_code=303
        )
    if confirm.strip() != NOTICE_SEND_CONFIRM_PHRASE:
        return RedirectResponse(
            url=f"/admin/notices/{notice_id}?notice_error=confirm_mismatch", status_code=303
        )

    sent_by = "admin"
    append_operator_audit(
        "notice_send_attempted",
        operator_id=_operator_id(request),
        result="attempted",
        related_id=notice_id,
        metadata={"recipient_count": notice.get("recipients_count")},
    )
    sent = send_admin_notice_email(notice)
    if sent:
        mark_sent(notice, sent_by=sent_by)
    else:
        mark_failed(notice, send_error="smtp_send_failed", sent_by=sent_by)
    append_operator_audit(
        "notice_send_result",
        operator_id=_operator_id(request),
        result="SMTP_ACCEPTED" if sent else "NOT_SENT",
        reason_code="" if sent else "smtp_send_failed",
        related_id=notice_id,
    )

    return RedirectResponse(url=f"/admin/notices/{notice_id}", status_code=303)


@router.get("/admin/notices/{notice_id}", response_class=HTMLResponse)
def admin_notice_detail(request: Request, notice_id: str):
    need = _require_login(request)
    if need is not None:
        return need
    if not validate_notice_id(notice_id):
        return HTMLResponse(_layout("Not found", "<p>잘못된 notice_id</p>"), status_code=404)
    notice = load_notice(notice_id)
    if not notice:
        return HTMLResponse(_layout("Not found", "<p>공지를 찾을 수 없습니다.</p>"), status_code=404)

    error_code = str(request.query_params.get("notice_error") or "")
    error_html = ""
    if error_code:
        msg = _NOTICE_SEND_ERROR_MESSAGES.get(error_code, error_code)
        error_html = f"<div class='warn' style='margin:8px 0'>{_esc(msg)}</div>"

    inner = f"""
<div class="page-head"><h1>공지 상세</h1>
<a href="/admin/notices" class="btn">← 공지 목록</a></div>
{error_html}
<div class="card">
<p>notice_id: <code>{_esc(notice['notice_id'])}</code></p>
<p>유형: {_esc(_NOTICE_TYPE_LABELS.get(notice.get('notice_type'), notice.get('notice_type')))}</p>
<p>프로그램: {_esc(notice.get('program_id'))}</p>
<p>관련 run_id: {_esc(notice.get('related_run_id') or '없음')}</p>
<p>상태: <strong>{_esc(_notice_status_label(str(notice.get('status') or '')))}</strong></p>
<p>생성 시각: {_esc(notice.get('created_at'))}</p>
<p>미리보기 시각: {_esc(notice.get('previewed_at') or '—')}</p>
<p>발송 시각: {_esc(notice.get('sent_at') or '—')}</p>
<p>smtp_accepted: {_esc(notice.get('smtp_accepted'))}</p>
<p>send_error: {_esc(notice.get('send_error') or '없음')}</p>
<p>수신자 수: {_esc(notice.get('recipients_count'))} (실제 이메일 목록은 저장/표시하지 않음)</p>
<p>수신자 공개 정책: <code>{_esc(notice.get('visible_recipient_policy'))}</code></p>
</div>
<div class="card">
<h2 style="font-size:16px;margin:0 0 12px">제목</h2>
<p>{_esc(notice.get('subject'))}</p>
<h2 style="font-size:16px;margin:16px 0 12px">본문</h2>
<div style="border:1px solid #e2e8f0;border-radius:8px;padding:12px;">{notice.get('body_html') or ''}</div>
</div>
"""
    return HTMLResponse(_layout(f"Notice {notice_id}", inner))
