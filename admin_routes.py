"""Minimal password-protected owner admin for run review and reissue."""
from __future__ import annotations

import hashlib
import hmac
import html
import logging
import os
import secrets
import time
from typing import Optional

logger = logging.getLogger(__name__)

from fastapi import APIRouter, Form, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse

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
    load_beta_recipient_config,
    now_kst_iso,
    load_run_artifact,
    load_run_email_html,
    list_run_artifacts,
    owner_review_email_label_ko,
    record_parent_reissue_audit,
    remove_beta_recipient,
    resolve_customer_recipients,
    validate_run_id,
)
from keysuri_service_full_run import run_keysuri_image_only_reissue
from orchestrator import execute_orchestrator_run

router = APIRouter(tags=["admin"])

SESSION_COOKIE = "genie_admin_session"
SESSION_SALT = b"genie-admin-session-v1"
APPROVE_NONCE_COOKIE = "genie_approve_nonce"
APPROVE_NONCE_SALT = b"genie-approve-nonce-v1"
APPROVE_NONCE_TTL_SECONDS = 900
APPROVE_NONCE_FORM_FIELD = "approve_nonce"
CUSTOMER_SEND_CONFIRM_FIELD = "customer_send_confirm"
REISSUE_REASONS = (
    "제목 수정 요청",
    "요약 수정 요청",
    "문장 표현 수정 요청",
    "이미지 품질 이슈",
    "구성 품질 이슈",
    "기타",
)

REISSUE_SCOPE_OPTIONS = (
    ("text_only", "본문만 재발행", "준비 중 — 본문만 재발행은 아직 지원하지 않습니다."),
    ("image_only", "이미지만 재발행", "이미지 prompt와 이미지 산출물만 다시 생성합니다. 본문은 유지됩니다."),
    (
        "text_and_image",
        "본문·이미지 모두 재발행",
        "본문과 이미지를 모두 새로 생성합니다. 전체 방향이 틀렸을 때 사용합니다.",
    ),
)

_REISSUE_ERROR_MESSAGES = {
    "invalid_reissue_scope": "재발행 범위가 올바르지 않습니다.",
    "missing_reissue_scope": "재발행 범위를 선택하세요.",
    "unsupported_reissue_scope": (
        "선택한 재발행 범위는 아직 실행할 수 없습니다. "
        "화면에 표시된 실행 가능 범위를 확인하세요."
    ),
}

_APPROVE_ERROR_MESSAGES = {
    "already_approved": "이미 승인된 실행입니다.",
    "customer_already_sent": "고객 발송이 이미 완료된 실행입니다.",
    "legacy_timeout_sent": "과거 타임아웃 자동 발송 기록입니다. 새 승인 발송은 불가합니다.",
    "missing_customer_to": "GENIE_CUSTOMER_EMAIL_TO가 설정되지 않았습니다.",
    "missing_email_html": "저장된 이메일 HTML이 없습니다.",
    "missing_smtp": "SMTP 설정이 없습니다.",
    "not_approvable": "승인할 수 없는 검증 상태입니다.",
    "send_failed": "고객 이메일 발송에 실패했습니다.",
    "unsupported_mode": "승인 발송을 지원하지 않는 mode입니다.",
    "keysuri_customer_delivery_not_ready": "Kee-Suri 고객 발송은 아직 안전 검증 전입니다.",
    "missing_approval_nonce": "승인 확인 토큰이 없습니다. 승인 검토 페이지에서 다시 시도하세요.",
    "invalid_approval_nonce": "승인 확인 토큰이 유효하지 않습니다. 승인 검토 페이지에서 다시 시도하세요.",
    "approval_nonce_expired": "승인 확인 토큰이 만료되었습니다. 승인 검토 페이지에서 다시 시도하세요.",
    "missing_customer_send_confirm": "고객 이메일 발송 승인 체크박스를 선택해야 합니다.",
}

_KEYSURI_CUSTOMER_DELIVERY_BLOCKED_MODES = frozenset({"keysuri_korea_tech"})


def admin_password() -> str:
    return os.getenv("GENIE_ADMIN_PASSWORD", "").strip()


def admin_enabled() -> bool:
    return bool(admin_password())


def _session_token(password: str) -> str:
    return hmac.new(password.encode("utf-8"), SESSION_SALT, hashlib.sha256).hexdigest()


def _session_token_from_request(request: Request) -> str:
    return str(request.cookies.get(SESSION_COOKIE, "") or "")


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
    return str(mode or "").strip() in ("keysuri_global_tech", "keysuri_korea_tech")


def _mode_supports_text_and_image_reissue(mode: str) -> bool:
    return str(mode or "").strip() in ("today_genie", "tomorrow_genie")


def _render_reissue_scope_field(mode: str) -> str:
    mode = str(mode or "").strip()
    image_only_enabled = _mode_supports_image_only_reissue(mode)
    text_and_image_enabled = _mode_supports_text_and_image_reissue(mode)
    default_scope = "image_only" if image_only_enabled else EXECUTABLE_REISSUE_SCOPE
    rows = [
        '<p style="margin:0 0 12px 0;font-size:12px;line-height:1.6;color:#9a3412;">'
        "선택 가능한 범위만 서버에서 실행됩니다. 본문만 재발행은 아직 준비 중입니다."
        "</p>"
    ]
    for scope, label, helper in REISSUE_SCOPE_OPTIONS:
        scope_helper = helper
        disabled = False
        if scope == "text_only":
            disabled = True
        elif scope == "image_only" and not image_only_enabled:
            disabled = True
            scope_helper = "이 실행 mode에서는 아직 지원하지 않습니다."
        elif scope == "text_and_image" and not text_and_image_enabled:
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


def _layout(title: str, inner: str) -> str:
    return f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_esc(title)}</title>
<style>
body{{font-family:-apple-system,BlinkMacSystemFont,system-ui,sans-serif;margin:0;padding:24px;background:#f8fafc;color:#0f172a;overflow-wrap:break-word;}}
.wrap{{max-width:960px;width:100%;margin:0 auto;box-sizing:border-box;}}
.card{{background:#fff;border:1px solid #e2e8f0;border-radius:10px;padding:20px;margin:16px 0;box-sizing:border-box;}}
.page-head{{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap;}}
.table-wrap{{overflow-x:auto;-webkit-overflow-scrolling:touch;}}
.table-wrap table{{min-width:640px;}}
table{{width:100%;border-collapse:collapse;font-size:14px;}}
th,td{{border-top:1px solid #e2e8f0;padding:10px;text-align:left;vertical-align:top;}}
th{{background:#f1f5f9;font-weight:700;}}
a{{color:#0f172a;}}
.btn{{display:inline-block;padding:12px 16px;min-height:44px;line-height:1.2;background:#0f172a;color:#fff;text-decoration:none;border-radius:8px;border:0;font-size:14px;cursor:pointer;box-sizing:border-box;}}
.btn:hover{{background:#1e293b;}}
.btn:focus-visible{{outline:2px solid #0f172a;outline-offset:2px;}}
.warn{{background:#fff7ed;border:1px solid #fdba74;padding:12px;border-radius:8px;font-size:14px;line-height:1.6;overflow-wrap:anywhere;}}
.break-long{{overflow-wrap:anywhere;word-break:break-word;}}
.meta dt{{font-weight:700;margin-top:8px;}}
.meta dd{{margin:4px 0 0 0;overflow-wrap:anywhere;word-break:break-word;}}
pre,code{{overflow-wrap:anywhere;word-break:break-word;}}
pre{{overflow-x:auto;max-width:100%;}}
.radio-scope{{display:flex;align-items:flex-start;gap:10px;margin:0 0 10px;padding:14px 16px;border:1px solid #e2e8f0;border-radius:10px;background:#f8fafc;cursor:pointer;-webkit-tap-highlight-color:transparent;box-sizing:border-box;}}
.radio-scope:has(input:checked){{border-color:#0f172a;background:#fff;box-shadow:inset 0 0 0 1px #0f172a;}}
.radio-scope--disabled{{opacity:.58;cursor:not-allowed;background:#f1f5f9;}}
.radio-scope__control{{flex:0 0 auto;padding-top:2px;}}
.radio-scope__control input[type=radio]{{width:20px;height:20px;margin:0;cursor:pointer;}}
.radio-scope--disabled .radio-scope__control input[type=radio]{{cursor:not-allowed;}}
.radio-scope__body{{flex:1;min-width:0;}}
.radio-helper{{display:block;margin-top:6px;font-size:12px;color:#64748b;line-height:1.5;overflow-wrap:anywhere;}}
input[type=password],input[type=text],select,textarea{{width:100%;max-width:420px;padding:10px 8px;font-size:16px;box-sizing:border-box;}}
@media (max-width:640px){{
body{{padding:16px 12px;}}
.card{{padding:16px;margin:12px 0;}}
.page-head{{flex-direction:column;align-items:stretch;}}
.page-head h1{{margin:0 0 4px 0;font-size:1.35rem;}}
.page-head .btn,.form-actions .btn{{width:100%;text-align:center;}}
th,td{{padding:8px 6px;font-size:13px;}}
input[type=password],input[type=text],select,textarea{{max-width:100%;}}
}}
</style></head><body><div class="wrap">{inner}</div></body></html>"""


@router.get("/admin", response_class=HTMLResponse)
def admin_home(request: Request):
    gate = _require_admin(request)
    if gate is not None:
        return gate
    if is_logged_in(request):
        return RedirectResponse(url="/admin/runs", status_code=303)
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
    return HTMLResponse(_layout("Genie Admin Login", inner))


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
        return HTMLResponse(_layout("Login failed", inner), status_code=401)
    resp = RedirectResponse(url="/admin/runs", status_code=303)
    resp.set_cookie(
        SESSION_COOKIE,
        _session_token(pwd),
        httponly=True,
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


@router.get("/admin/runs", response_class=HTMLResponse)
def admin_runs_list(request: Request):
    need = _require_login(request)
    if need is not None:
        return need
    runs = list_run_artifacts(limit=50)
    rows = []
    for r in runs:
        rid = _esc(r.get("run_id"))
        rows.append(
            f"<tr>"
            f"<td><a href=\"/admin/runs/{rid}\">{rid}</a></td>"
            f"<td>{_esc(r.get('mode'))}</td>"
            f"<td>{_esc(r.get('created_at'))}</td>"
            f"<td>{_esc(r.get('artifact_status'))}</td>"
            f"<td>{_esc(r.get('validation_result'))}</td>"
            f"<td>{_esc(r.get('workflow_status'))}</td>"
            f"<td>{'Y' if r.get('email_sent') else 'N'}</td>"
            f"<td>{_esc(r.get('reissue_count', 0))}</td>"
            f"</tr>"
        )
    table = (
        "<table><thead><tr>"
        "<th>run_id</th><th>mode</th><th>created_at</th><th>status</th>"
        "<th>validation</th><th>workflow</th><th>email_sent</th><th>reissues</th>"
        "</tr></thead><tbody>"
        + ("".join(rows) if rows else "<tr><td colspan=\"8\">저장된 실행 기록이 없습니다.</td></tr>")
        + "</tbody></table>"
    )
    inner = f"""
<div class="page-head">
<h1>최근 실행 기록</h1>
<div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center;">
<a href="/admin/customer-recipients" class="btn" style="background:#0f172a;">베타 고객 수신자 관리</a>
<form method="post" action="/admin/logout" style="margin:0;"><button class="btn" type="submit">로그아웃</button></form>
</div>
</div>
<p class="break-long">저장 경로: <code>{_esc(artifact_store_display_path())}</code></p>
<div class="card"><div class="table-wrap">{table}</div></div>
"""
    return HTMLResponse(_layout("Runs", inner))


@router.get("/admin/runs/{run_id}", response_class=HTMLResponse)
def admin_run_detail(request: Request, run_id: str):
    need = _require_login(request)
    if need is not None:
        return need
    if not validate_run_id(run_id):
        return HTMLResponse(_layout("Not found", "<p>잘못된 run_id</p>"), status_code=404)
    meta = load_run_artifact(run_id)
    if not meta:
        return HTMLResponse(_layout("Not found", "<p>실행 기록을 찾을 수 없습니다.</p>"), status_code=404)
    warn = ""
    if request.query_params.get("reissue_warn") == "email_not_sent":
        warn = (
            '<div class="warn">재발행 실행은 완료되었지만 운영자 검토용 이메일은 발송되지 않았습니다. '
            "SMTP 설정, EMAIL_TO(소유자 계정), 정책/이미지 자산을 확인하세요.</div>"
        )
    has_email = load_run_email_html(run_id) is not None
    email_link = f'<a href="/admin/runs/{_esc(run_id)}/email" target="_blank">이메일 HTML 미리보기</a>' if has_email else "<em>저장된 이메일 HTML 없음</em>"
    can_approve, approve_err = can_approve_customer_send(meta, has_email_html=has_email)
    mode = str(meta.get("mode") or "")
    approve_block = ""
    if can_approve:
        approve_block = (
            f'<div class="form-actions"><p style="margin:0;"><a class="btn" href="/admin/runs/{_esc(run_id)}/approve-confirm">'
            "승인 검토 페이지 열기</a></p></div>"
        )
    elif mode in _KEYSURI_CUSTOMER_DELIVERY_BLOCKED_MODES:
        approve_block = (
            f'<p class="warn">{_esc(_APPROVE_ERROR_MESSAGES.get(approve_err, approve_err))}</p>'
        )
    elif mode == "today_genie":
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
    reason_opts = "".join(
        f'<option value="{_esc(o)}">{_esc(o)}</option>' for o in REISSUE_REASONS
    )
    delivery_sections = _render_delivery_report_sections(meta)
    meta_rows = "".join(
        f"<dt>{_esc(k)}</dt><dd>{_esc(v)}</dd>"
        for k, v in sorted(meta.items())
        if k not in ("issue_details", "customer_delivery_events")
    )
    scope_field = _render_reissue_scope_field(mode)
    inner = f"""
<div class="page-head">
<h1>실행 상세</h1>
<div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center;">
<a href="/admin/runs" class="btn" style="background:#475569;">← 목록</a>
<a href="/admin/customer-recipients" class="btn" style="background:#0f172a;">베타 고객 수신자 관리</a>
</div>
</div>
{warn}
{delivery_sections}
<div class="card">
<dl class="meta">{meta_rows}</dl>
<p>{email_link}</p>
{approve_block}
</div>
<div class="card warn">
<strong>재발행 안내</strong><br>
재발행은 <strong>운영자 검토용 이메일</strong>을 다시 보내는 작업입니다. 고객 최종 배포가 아닙니다.<br>
이미지만 재발행은 KeeSuri 실행에서 본문을 보존하고 이미지 prompt와 이미지 산출물만 다시 생성합니다.<br>
본문만 재발행은 준비 중이며, 본문·이미지 모두 재발행은 기존 Today/Tomorrow 실행 경로에서만 사용할 수 있습니다.
</div>
<div class="card">
<h2>재발행 요청</h2>
<form method="post" action="/admin/runs/{_esc(run_id)}/reissue">
<label>재발행 범위<br>
{scope_field}
</label><br>
<label>사유<br>
<select name="reason_option" required>{reason_opts}</select>
</label><br><br>
<label>추가 메모 (선택)<br>
<input type="text" name="reason_note" maxlength="500" placeholder="선택 사유 보완">
</label><br><br>
<div class="form-actions"><button class="btn" type="submit">재발행 실행</button></div>
</form>
</div>
"""
    return HTMLResponse(_layout(f"Run {run_id}", inner))


@router.get("/admin/runs/{run_id}/email", response_class=HTMLResponse)
def admin_run_email_preview(request: Request, run_id: str):
    need = _require_login(request)
    if need is not None:
        return need
    if not validate_run_id(run_id):
        return HTMLResponse("<p>잘못된 run_id</p>", status_code=404)
    content = load_run_email_html(run_id)
    if content is None:
        return HTMLResponse(
            _layout("Email missing", "<p>저장된 이메일 HTML이 없습니다.</p>"),
            status_code=404,
        )
    return HTMLResponse(content)


@router.get("/admin/runs/{run_id}/approve-confirm", response_class=HTMLResponse)
def admin_run_approve_confirm(request: Request, run_id: str):
    need = _require_login(request)
    if need is not None:
        return need
    if not validate_run_id(run_id):
        return HTMLResponse(_layout("Not found", "<p>잘못된 run_id</p>"), status_code=404)
    meta = load_run_artifact(run_id)
    if not meta:
        return HTMLResponse(_layout("Not found", "<p>실행 기록을 찾을 수 없습니다.</p>"), status_code=404)
    has_email = load_run_email_html(run_id) is not None
    can_approve, approve_err = can_approve_customer_send(meta, has_email_html=has_email)
    if not can_approve:
        msg = _APPROVE_ERROR_MESSAGES.get(approve_err, approve_err)
        inner = f"<p>{_esc(msg)}</p><p><a href=\"/admin/runs/{_esc(run_id)}\">돌아가기</a></p>"
        return HTMLResponse(_layout("Approve blocked", inner), status_code=400)
    session_token = _session_token_from_request(request)
    nonce, cookie_value = issue_approval_nonce(run_id, session_token)
    inner = f"""
<h1>고객 발송 승인 확인</h1>
<p>run_id: <code>{_esc(run_id)}</code></p>
<p>mode: {_esc(meta.get('mode'))}</p>
<p>승인 시 고객에게 HTML 본문 이메일이 즉시 발송됩니다. (첨부/Naver 패키지 없음)</p>
<div class="card warn">
<strong>주의</strong> — 승인은 되돌릴 수 없으며 중복 승인 발송은 차단됩니다.
</div>
<form method="post" action="/admin/runs/{_esc(run_id)}/approve">
<input type="hidden" name="{_esc(APPROVE_NONCE_FORM_FIELD)}" value="{_esc(nonce)}">
<label>승인 메모 (선택)<br>
<input type="text" name="approve_note" maxlength="500" placeholder="승인 메모">
</label><br><br>
<label style="display:block;margin:0 0 16px 0;">
<input type="checkbox" name="{_esc(CUSTOMER_SEND_CONFIRM_FIELD)}" value="1" required>
고객 이메일 발송을 승인합니다
</label>
<div class="form-actions"><button class="btn" type="submit">승인 및 고객 발송</button></div>
</form>
<p><a href="/admin/runs/{_esc(run_id)}">← 실행 상세</a></p>
"""
    resp = HTMLResponse(_layout(f"Approve {run_id}", inner))
    resp.set_cookie(
        APPROVE_NONCE_COOKIE,
        cookie_value,
        httponly=True,
        samesite="lax",
        max_age=APPROVE_NONCE_TTL_SECONDS,
        path="/",
    )
    return resp


@router.post("/admin/runs/{run_id}/approve")
def admin_run_approve(
    request: Request,
    run_id: str,
    approve_note: str = Form(""),
    approve_nonce: str = Form(""),
    customer_send_confirm: str = Form(""),
):
    need = _require_login(request)
    if need is not None:
        return need
    if not validate_run_id(run_id):
        return HTMLResponse(_layout("Not found", "<p>잘못된 run_id</p>"), status_code=404)

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
    updated, status = approve_run(run_id, note=approve_note, approval_audit=approval_audit)
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
):
    need = _require_login(request)
    if need is not None:
        return need
    if not validate_run_id(run_id):
        return HTMLResponse(_layout("Not found", "<p>잘못된 run_id</p>"), status_code=404)
    parent = load_run_artifact(run_id)
    if not parent:
        return HTMLResponse(_layout("Not found", "<p>원본 실행 기록을 찾을 수 없습니다.</p>"), status_code=404)

    scope = str(reissue_scope or "").strip()
    if not scope:
        return RedirectResponse(
            url=f"/admin/runs/{run_id}?reissue_error=missing_reissue_scope",
            status_code=303,
        )
    if scope not in REISSUE_SCOPES:
        return RedirectResponse(
            url=f"/admin/runs/{run_id}?reissue_error=invalid_reissue_scope",
            status_code=303,
        )
    mode = str(parent.get("mode") or parent.get("program_id") or "").strip()
    if scope in UNSUPPORTED_REISSUE_SCOPES:
        return RedirectResponse(
            url=f"/admin/runs/{run_id}?reissue_error=unsupported_reissue_scope",
            status_code=303,
        )
    reason_code = reason_option.strip()
    note = reason_note.strip()

    if scope == "image_only":
        if not _mode_supports_image_only_reissue(mode):
            return RedirectResponse(
                url=f"/admin/runs/{run_id}?reissue_error=unsupported_reissue_scope",
                status_code=303,
            )
        try:
            result = run_keysuri_image_only_reissue(
                run_id,
                parent_meta=parent,
                reissue_reason_code=reason_code,
                reissue_reason_note=note,
            )
        except Exception as exc:  # noqa: BLE001
            inner = (
                f"<p>이미지만 재발행 실행 중 오류가 발생했습니다.</p>"
                f"<p>{_esc(type(exc).__name__)}</p>"
                f"<p><a href=\"/admin/runs/{_esc(run_id)}\">돌아가기</a></p>"
            )
            return HTMLResponse(_layout("Reissue error", inner), status_code=500)
        new_run_id = str(result.get("run_id") or "").strip()
        if new_run_id and not result.get("email_sent") and not result.get("error"):
            return RedirectResponse(
                url=f"/admin/runs/{new_run_id}?reissue_warn=email_not_sent",
                status_code=303,
            )
        if not result.get("ok") or not new_run_id:
            inner = (
                f"<p>이미지만 재발행을 완료하지 못했습니다.</p>"
                f"<p>{_esc(str(result.get('error') or 'image_only_reissue_failed'))}</p>"
                f"<p><a href=\"/admin/runs/{_esc(run_id)}\">돌아가기</a></p>"
            )
            return HTMLResponse(_layout("Reissue failed", inner), status_code=500)
        return RedirectResponse(url=f"/admin/runs/{new_run_id}", status_code=303)

    if scope != EXECUTABLE_REISSUE_SCOPE:
        return RedirectResponse(
            url=f"/admin/runs/{run_id}?reissue_error=invalid_reissue_scope",
            status_code=303,
        )

    if mode not in ("today_genie", "tomorrow_genie"):
        inner = f"<p>재발행할 수 없는 mode: {_esc(mode)}</p><p><a href=\"/admin/runs/{_esc(run_id)}\">돌아가기</a></p>"
        return HTMLResponse(_layout("Reissue failed", inner), status_code=400)

    reason = reason_code
    if note:
        reason = f"{reason} — {note}"

    try:
        new_run_id, _result, email_sent = execute_orchestrator_run(
            mode,
            parent_run_id=run_id,
            reissue_reason=reason,
            admin_reissue=True,
        )
    except Exception as exc:  # noqa: BLE001
        inner = (
            f"<p>재발행 실행 중 오류가 발생했습니다.</p>"
            f"<p>{_esc(type(exc).__name__)}</p>"
            f"<p><a href=\"/admin/runs/{_esc(run_id)}\">돌아가기</a></p>"
        )
        return HTMLResponse(_layout("Reissue error", inner), status_code=500)

    if not new_run_id:
        inner = (
            f"<p>재발행 아티팩트를 저장하지 못했습니다.</p>"
            f"<p><a href=\"/admin/runs/{_esc(run_id)}\">돌아가기</a></p>"
        )
        return HTMLResponse(_layout("Reissue failed", inner), status_code=500)

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
) -> Response:
    gate = _require_login(request)
    if gate is not None:
        return gate  # type: ignore[return-value]
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
    return RedirectResponse(url="/admin/customer-recipients?added=1", status_code=303)


@router.post("/admin/customer-recipients/remove")
def admin_customer_recipients_remove(
    request: Request,
    email: str = Form(...),
) -> Response:
    gate = _require_login(request)
    if gate is not None:
        return gate  # type: ignore[return-value]
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
    return RedirectResponse(url="/admin/customer-recipients?removed=1", status_code=303)
