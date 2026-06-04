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
    admin_runs_dir,
    approve_run,
    can_approve_customer_send,
    load_run_artifact,
    load_run_email_html,
    list_run_artifacts,
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
}


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


def _admin_disabled_response() -> HTMLResponse:
    body = """
<!doctype html><html lang="ko"><head><meta charset="utf-8"><title>Genie Admin</title></head>
<body style="font-family:system-ui,sans-serif;padding:24px;max-width:640px;">
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
body{{font-family:-apple-system,BlinkMacSystemFont,system-ui,sans-serif;margin:0;padding:24px;background:#f8fafc;color:#0f172a;}}
.wrap{{max-width:960px;margin:0 auto;}}
.card{{background:#fff;border:1px solid #e2e8f0;border-radius:10px;padding:20px;margin:16px 0;}}
table{{width:100%;border-collapse:collapse;font-size:14px;}}
th,td{{border-top:1px solid #e2e8f0;padding:10px;text-align:left;vertical-align:top;}}
th{{background:#f1f5f9;font-weight:700;}}
a{{color:#0f172a;}}
.btn{{display:inline-block;padding:10px 16px;background:#0f172a;color:#fff;text-decoration:none;border-radius:8px;border:0;font-size:14px;cursor:pointer;}}
.warn{{background:#fff7ed;border:1px solid #fdba74;padding:12px;border-radius:8px;font-size:14px;}}
.meta dt{{font-weight:700;margin-top:8px;}}
.meta dd{{margin:4px 0 0 0;}}
input[type=password],input[type=text],select,textarea{{width:100%;max-width:420px;padding:8px;font-size:14px;}}
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
<button class="btn" type="submit">로그인</button>
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
<button class="btn" type="submit">로그인</button>
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
<div style="display:flex;justify-content:space-between;align-items:center;">
<h1>최근 실행 기록</h1>
<form method="post" action="/admin/logout" style="margin:0;"><button class="btn" type="submit">로그아웃</button></form>
</div>
<p>저장 경로: <code>{_esc(admin_runs_dir())}</code></p>
<div class="card">{table}</div>
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
    approve_block = ""
    if meta.get("mode") == "today_genie":
        if can_approve:
            approve_block = (
                f'<p><a class="btn" href="/admin/runs/{_esc(run_id)}/approve-confirm">'
                "승인 검토 페이지 열기</a></p>"
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
    reason_opts = "".join(
        f'<option value="{_esc(o)}">{_esc(o)}</option>' for o in REISSUE_REASONS
    )
    meta_rows = "".join(
        f"<dt>{_esc(k)}</dt><dd>{_esc(v)}</dd>"
        for k, v in sorted(meta.items())
        if k not in ("issue_details",)
    )
    inner = f"""
<div style="display:flex;justify-content:space-between;align-items:center;">
<h1>실행 상세</h1>
<a href="/admin/runs">← 목록</a>
</div>
{warn}
<div class="card">
<dl class="meta">{meta_rows}</dl>
<p>{email_link}</p>
{approve_block}
</div>
<div class="card warn">
<strong>재발행 안내</strong><br>
재발행은 새 브리핑을 생성하고 <strong>운영자 검토용 이메일</strong>을 다시 보냅니다. 고객 최종 배포가 아닙니다.
</div>
<div class="card">
<h2>재발행 요청</h2>
<form method="post" action="/admin/runs/{_esc(run_id)}/reissue">
<label>사유<br>
<select name="reason_option" required>{reason_opts}</select>
</label><br><br>
<label>추가 메모 (선택)<br>
<input type="text" name="reason_note" maxlength="500" placeholder="선택 사유 보완">
</label><br><br>
<button class="btn" type="submit">재발행 실행</button>
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
<button class="btn" type="submit">승인 및 고객 발송</button>
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
):
    need = _require_login(request)
    if need is not None:
        return need
    if not validate_run_id(run_id):
        return HTMLResponse(_layout("Not found", "<p>잘못된 run_id</p>"), status_code=404)
    parent = load_run_artifact(run_id)
    if not parent:
        return HTMLResponse(_layout("Not found", "<p>원본 실행 기록을 찾을 수 없습니다.</p>"), status_code=404)

    mode = str(parent.get("mode") or "").strip()
    if mode not in ("today_genie", "tomorrow_genie"):
        inner = f"<p>재발행할 수 없는 mode: {_esc(mode)}</p><p><a href=\"/admin/runs/{_esc(run_id)}\">돌아가기</a></p>"
        return HTMLResponse(_layout("Reissue failed", inner), status_code=400)

    reason = reason_option.strip()
    note = reason_note.strip()
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

    if not email_sent:
        return RedirectResponse(
            url=f"/admin/runs/{new_run_id}?reissue_warn=email_not_sent",
            status_code=303,
        )
    return RedirectResponse(url=f"/admin/runs/{new_run_id}", status_code=303)
