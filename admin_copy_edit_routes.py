"""Authenticated literal-copy editor; separate from paid regeneration/send."""
import html
import json
from hashlib import sha256

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from original_copy_edit import (
    CopyEditError, _digest, _eligible, editable_segments, prepare_copy_edit, apply_copy_edit,
)
from publication_content_guard import ContentMutationBusy

router = APIRouter()


def _error(admin, exc):
    code = str(exc)
    messages = {
        "COPY_EDIT_BASE_CHANGED": "원문 또는 발송 상태가 바뀌었습니다. 최신 원문을 다시 확인해 주세요.",
        "COPY_EDIT_NOT_CURRENT_LEAF": "후속 수정본이 있습니다. 최신 수정본에서 문구를 고쳐 주세요.",
        "COPY_EDIT_CUSTOMER_ALREADY_ATTEMPTED": "이미 발송을 시작한 브리핑은 수정하지 않습니다.",
        "COPY_EDIT_PUBLICATION_ALREADY_ATTEMPTED": "이 회차는 발송 기록이 있어 원문을 변경하지 않습니다.",
        "COPY_EDIT_OWNER_STATE_CONFLICT": "현재 보류·승인 상태를 유지합니다. 이 화면에서 해제하지 않습니다.",
        "COPY_EDIT_OWNER_MAIL_RECONCILE": "원문은 저장됐습니다. 검수 메일의 발송 결과를 확인해야 하므로 다시 전송하지 마세요.",
        "PUBLICATION_CONTENT_OPERATION_RUNNING_OR_UNKNOWN": "같은 회차의 수정 또는 발송이 진행 중입니다. 현재 작업 결과를 먼저 확인합니다.",
    }
    message = messages.get(code, "수정 조건을 확인할 수 없습니다. 원문과 현재 운영 기록을 먼저 확인해 주세요.")
    return HTMLResponse(admin._layout("문구 수정 확인", "<p>" + html.escape(message) + "</p>"), status_code=409)


@router.get("/admin/runs/{run_id}/copy-edit", response_class=HTMLResponse)
def copy_edit_page(request: Request, run_id: str):
    import admin_routes as admin
    import admin_store as store
    from datetime import datetime
    from zoneinfo import ZoneInfo
    need = admin._require_login(request)
    if need is not None:
        return need
    meta = store.load_run_artifact(run_id, normalize=False)
    if not meta:
        return HTMLResponse("Not found", status_code=404)
    try:
        _eligible(meta, now=datetime.now(ZoneInfo("Asia/Seoul")))
        original = store.load_run_email_html(run_id) or ""
        _, fields = editable_segments(original)
    except (CopyEditError, ContentMutationBusy) as exc:
        return _error(admin, exc)
    rows = []
    for field in fields:
        rows.append('<div class="surface" style="margin-top:12px"><p>현재 문장</p><p>'
                    + html.escape(field["text"]) + '</p><label>바꿀 문장<textarea rows="3" '
                    + 'style="width:100%" data-copy-field="' + field["field_id"]
                    + '" data-before-sha256="' + field["text_sha256"] + '">'
                    + html.escape(field["text"]) + '</textarea></label></div>')
    script = """<script>document.getElementById('copy-edit-form').addEventListener('submit',function(){
      const edits=Array.from(this.querySelectorAll('[data-copy-field]')).filter(e=>e.value!==e.defaultValue)
        .map(e=>({field_id:e.dataset.copyField,before_sha256:e.dataset.beforeSha256,replacement:e.value}));
      this.querySelector('[name=changes_json]').value=JSON.stringify(edits);
    });</script>"""
    inner = '<h1>문구만 수정</h1><p>선택한 문장만 고칩니다. 기사·이미지를 다시 생성하지 않습니다. 수정 전 원문과 검수 기록은 보존하며, 수정본은 새 검수를 거칩니다.</p>'
    inner += '<form id="copy-edit-form" method="post" action="/admin/runs/' + run_id + '/copy-edit">'
    inner += admin._csrf_field(request, "copy-edit:" + run_id)
    inner += '<input type="hidden" name="expected_html_sha256" value="' + sha256(original.encode()).hexdigest() + '">'
    inner += '<input type="hidden" name="expected_meta_sha256" value="' + _digest(meta) + '">'
    inner += '<input type="hidden" name="changes_json" value="[]">' + ''.join(rows)
    inner += '<button type="submit" formaction="/admin/runs/' + run_id + '/copy-edit/preview">변경 내용 확인</button> '
    inner += '<button type="submit">수정본 저장·검수 메일 보내기</button></form>' + script
    return HTMLResponse(admin._layout("문구만 수정", inner))


async def _read_changes(request, changes_json):
    if len(changes_json.encode()) > 600_000:
        raise CopyEditError("COPY_EDIT_REQUEST_TOO_LARGE")
    try:
        return json.loads(changes_json)
    except (TypeError, ValueError):
        raise CopyEditError("COPY_EDIT_CHANGES_INVALID")


@router.post("/admin/runs/{run_id}/copy-edit/preview", response_class=HTMLResponse)
async def copy_edit_preview(request: Request, run_id: str, changes_json: str = Form(...),
                            expected_html_sha256: str = Form(...), expected_meta_sha256: str = Form(...),
                            csrf_token: str = Form("")):
    import admin_routes as admin
    from starlette.concurrency import run_in_threadpool
    need = admin._require_login(request)
    if need is not None:
        return need
    if not admin._verify_csrf(request, "copy-edit:" + run_id, csrf_token):
        return admin._csrf_rejected()
    try:
        changes = await _read_changes(request, changes_json)
        prepared = await run_in_threadpool(prepare_copy_edit, run_id, changes,
                                           expected_html_sha256=expected_html_sha256,
                                           expected_meta_sha256=expected_meta_sha256)
    except (CopyEditError, ContentMutationBusy) as exc:
        return _error(admin, exc)
    # Plain text is intentionally escaped; preview never executes replacement markup.
    inner = '<h1>변경 내용 확인</h1><p>아직 저장하거나 메일을 보내지 않았습니다.</p>'
    _, original_fields = editable_segments(prepared["before_html"])
    before_by_id = {f["field_id"]: f["text"] for f in original_fields}
    inner += ''.join('<section><p>수정 전</p><pre>' + html.escape(before_by_id[c["field_id"]])
                     + '</pre><p>수정 후</p><pre>' + html.escape(c["replacement"]) + '</pre></section>' for c in changes)
    inner += '<form method="post" action="/admin/runs/' + run_id + '/copy-edit">'
    inner += admin._csrf_field(request, "copy-edit:" + run_id)
    for name, value in {"changes_json": json.dumps(changes, ensure_ascii=False),
                        "expected_html_sha256": expected_html_sha256,
                        "expected_meta_sha256": expected_meta_sha256}.items():
        inner += '<input type="hidden" name="' + name + '" value="' + html.escape(value, quote=True) + '">'
    inner += '<button type="submit">수정본 저장·검수 메일 보내기</button></form>'
    return HTMLResponse(admin._layout("변경 내용 확인", inner))


@router.post("/admin/runs/{run_id}/copy-edit")
async def copy_edit_apply(request: Request, run_id: str, changes_json: str = Form(...),
                          expected_html_sha256: str = Form(...), expected_meta_sha256: str = Form(...),
                          csrf_token: str = Form(""), actual_actor: str = Form("ADMIN_SESSION")):
    import admin_routes as admin
    from starlette.concurrency import run_in_threadpool
    need = admin._require_login(request)
    if need is not None:
        return need
    if not admin._verify_csrf(request, "copy-edit:" + run_id, csrf_token):
        return admin._csrf_rejected()
    try:
        changes = await _read_changes(request, changes_json)
        result = await run_in_threadpool(apply_copy_edit, run_id, changes,
                                         expected_html_sha256=expected_html_sha256,
                                         expected_meta_sha256=expected_meta_sha256, actual_actor=actual_actor)
    except (CopyEditError, ContentMutationBusy) as exc:
        return _error(admin, exc)
    suffix = "saved" if result.get("owner_mail_state") == "SMTP_ACCEPTED" else "mail_reconcile"
    return RedirectResponse(f"/admin/runs/{run_id}?copy_edit={suffix}", status_code=303)
