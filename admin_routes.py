"""Minimal password-protected owner admin for run review and reissue."""
from __future__ import annotations

import html
import hmac
import hashlib
import os
from typing import Optional

from fastapi import APIRouter, Form, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse

from admin_store import (
    EXECUTABLE_REISSUE_SCOPE,
    REISSUE_SCOPES,
    UNSUPPORTED_REISSUE_SCOPES,
    admin_runs_dir,
    apply_reissue_child_metadata,
    approve_run,
    can_approve_customer_send,
    customer_delivery_status_label_ko,
    load_run_artifact,
    load_run_email_html,
    list_run_artifacts,
    owner_review_email_label_ko,
    record_parent_reissue_audit,
    validate_run_id,
)
from orchestrator import execute_orchestrator_run

router = APIRouter(tags=["admin"])

SESSION_COOKIE = "genie_admin_session"
SESSION_SALT = b"genie-admin-session-v1"
REISSUE_REASONS = (
    "제목 수정 요청",
    "요약 수정 요청",
    "문장 표현 수정 요청",
    "이미지 품질 이슈",
    "구성 품질 이슈",
    "기타",
)

REISSUE_SCOPE_OPTIONS = (
    ("text_only", "본문만 재발행", "텍스트, 제목, 출처, 수치, 문장 흐름만 다시 생성합니다. 기존 이미지는 유지합니다."),
    ("image_only", "이미지만 재발행", "이미지 프롬프트와 이미지 산출물만 다시 생성합니다. 본문은 유지합니다."),
    (
        "text_and_image",
        "본문·이미지 모두 재발행",
        "본문과 이미지 산출물을 모두 다시 생성합니다. 전체 방향이 틀렸을 때 선택합니다.",
    ),
)

_REISSUE_ERROR_MESSAGES = {
    "invalid_reissue_scope": "재발행 범위가 올바르지 않습니다.",
    "missing_reissue_scope": "재발행 범위를 선택하세요.",
    "unsupported_reissue_scope": (
        "선택한 재발행 범위는 아직 실행할 수 없습니다. "
        "현재는 본문·이미지 모두 재발행만 실행 가능합니다."
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
}

_KEYSURI_CUSTOMER_DELIVERY_BLOCKED_MODES = frozenset(
    {"keysuri_global_tech", "keysuri_korea_tech"}
)


def admin_password() -> str:
    return os.getenv("GENIE_ADMIN_PASSWORD", "").strip()


def admin_enabled() -> bool:
    return bool(admin_password())


def _session_token(password: str) -> str:
    return hmac.new(password.encode("utf-8"), SESSION_SALT, hashlib.sha256).hexdigest()


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


def _render_delivery_report_sections(meta: dict) -> str:
    owner_label = owner_review_email_label_ko(meta)
    delivery_status = str(meta.get("customer_delivery_status") or "not_sent")
    delivery_label = customer_delivery_status_label_ko(delivery_status)
    delivery_summary = str(meta.get("customer_delivery_error_summary") or "").strip()
    delivery_summary_row = ""
    if delivery_summary:
        delivery_summary_row = (
            f"<p class=\"break-long\" style=\"margin:8px 0 0 0;font-size:13px;color:#b91c1c;\">"
            f"오류 요약: {_esc(delivery_summary)}</p>"
        )
    helper = (
        "<p style=\"margin:8px 0 0 0;font-size:12px;line-height:1.6;color:#64748b;\">"
        "SMTP 접수는 메일 서버가 발송 요청을 받은 상태입니다. 실제 수신함 도착과는 다를 수 있습니다.<br>"
        "반송/거절/지연 이벤트는 메일 제공자의 회신 또는 웹훅 기준으로 표시됩니다.<br>"
        "고객 발송은 운영자 승인 후에만 실행됩니다.<br>"
        "운영자 검토 메일 발송 상태와 고객 이메일 전달 상태는 별도로 표시됩니다."
        "</p>"
    )
    return f"""
<div class="card">
<h2>운영자 검토 메일</h2>
<p style="margin:0;font-size:14px;"><strong>{_esc(owner_label)}</strong></p>
<p style="margin:8px 0 0 0;font-size:12px;color:#64748b;">고객 최종 배포와 별도입니다.</p>
</div>
<div class="card">
<h2>고객 이메일 전달</h2>
<p style="margin:0;font-size:14px;"><strong>{_esc(delivery_label)}</strong>
<span style="color:#64748b;font-size:12px;"> ({_esc(delivery_status)})</span></p>
{delivery_summary_row}
{helper}
</div>
"""


def _render_reissue_scope_field() -> str:
    rows = [
        '<p style="margin:0 0 12px 0;font-size:12px;line-height:1.6;color:#9a3412;">'
        "현재 본문만/이미지만 재발행은 선택할 수 있지만, 실행은 아직 차단됩니다. "
        "범위 보존 및 병합 로직이 준비된 뒤 활성화됩니다."
        "</p>"
    ]
    for scope, label, helper in REISSUE_SCOPE_OPTIONS:
        scope_helper = helper
        if scope in UNSUPPORTED_REISSUE_SCOPES:
            scope_helper = f"{helper} (현재는 선택만 가능하며 실행은 차단됩니다.)"
        checked = " checked" if scope == EXECUTABLE_REISSUE_SCOPE else ""
        rows.append(
            f"<label class=\"radio-scope\">"
            f"<span class=\"radio-scope__control\">"
            f"<input type=\"radio\" name=\"reissue_scope\" value=\"{_esc(scope)}\" required"
            f"{checked}>"
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
.radio-scope__control{{flex:0 0 auto;padding-top:2px;}}
.radio-scope__control input[type=radio]{{width:20px;height:20px;margin:0;cursor:pointer;}}
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
<form method="post" action="/admin/logout" style="margin:0;"><button class="btn" type="submit">로그아웃</button></form>
</div>
<p class="break-long">저장 경로: <code>{_esc(admin_runs_dir())}</code></p>
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
    scope_field = _render_reissue_scope_field()
    inner = f"""
<div class="page-head">
<h1>실행 상세</h1>
<a href="/admin/runs">← 목록</a>
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
재발행은 새 브리핑을 생성하고 <strong>운영자 검토용 이메일</strong>을 다시 보냅니다. 고객 최종 배포가 아닙니다.<br>
현재 실행 경로는 새 본문 생성과 운영자 검토용 이메일 재발송을 수행합니다. 이미지는 현재 최신 이미지 자산을 재사용할 수 있습니다.<br>
본문만/이미지만 재발행은 선택할 수 있지만 실행은 서버에서 차단됩니다. 현재 즉시 실행 가능한 경로는 본문·이미지 모두 재발행입니다.
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
    inner = f"""
<h1>고객 발송 승인 확인</h1>
<p>run_id: <code>{_esc(run_id)}</code></p>
<p>mode: {_esc(meta.get('mode'))}</p>
<p>승인 시 고객에게 HTML 본문 이메일이 즉시 발송됩니다. (첨부/Naver 패키지 없음)</p>
<div class="card warn">
<strong>주의</strong> — 승인은 되돌릴 수 없으며 중복 승인 발송은 차단됩니다.
</div>
<form method="post" action="/admin/runs/{_esc(run_id)}/approve">
<label>승인 메모 (선택)<br>
<input type="text" name="approve_note" maxlength="500" placeholder="승인 메모">
</label><br><br>
<div class="form-actions"><button class="btn" type="submit">승인 및 고객 발송</button></div>
</form>
<p><a href="/admin/runs/{_esc(run_id)}">← 실행 상세</a></p>
"""
    return HTMLResponse(_layout(f"Approve {run_id}", inner))


@router.post("/admin/runs/{run_id}/approve")
def admin_run_approve(
    request: Request,
    run_id: str,
    approve_note: str = Form(""),
):
    need = _require_login(request)
    if need is not None:
        return need
    if not validate_run_id(run_id):
        return HTMLResponse(_layout("Not found", "<p>잘못된 run_id</p>"), status_code=404)
    updated, status = approve_run(run_id, note=approve_note)
    if status != "ok" or not updated:
        code = status if status in _APPROVE_ERROR_MESSAGES else "send_failed"
        return RedirectResponse(
            url=f"/admin/runs/{run_id}?approve_error={code}",
            status_code=303,
        )
    return RedirectResponse(url=f"/admin/runs/{run_id}", status_code=303)


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
    if scope in UNSUPPORTED_REISSUE_SCOPES:
        return RedirectResponse(
            url=f"/admin/runs/{run_id}?reissue_error=unsupported_reissue_scope",
            status_code=303,
        )
    if scope != EXECUTABLE_REISSUE_SCOPE:
        return RedirectResponse(
            url=f"/admin/runs/{run_id}?reissue_error=invalid_reissue_scope",
            status_code=303,
        )

    mode = str(parent.get("mode") or "").strip()
    if mode not in ("today_genie", "tomorrow_genie"):
        inner = f"<p>재발행할 수 없는 mode: {_esc(mode)}</p><p><a href=\"/admin/runs/{_esc(run_id)}\">돌아가기</a></p>"
        return HTMLResponse(_layout("Reissue failed", inner), status_code=400)

    reason_code = reason_option.strip()
    note = reason_note.strip()
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
