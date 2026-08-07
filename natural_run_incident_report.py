"""Korean natural-run failure / recovery report emails for operators.

Never includes secrets, raw prompts, stack traces, or customer addresses.
Never triggers recovery — report only.
"""
from __future__ import annotations

import html
import logging
import re
from typing import Any, Dict, List, Mapping, Optional, Tuple

from natural_run_incident_store import (
    RETRY_ALLOWED_WITH_WARNING,
    RETRY_BLOCKED,
    RETRY_REQUIRES_PATCH,
    RETRY_SAFE,
    RETRY_SAFE_TO_RETRY,
    RETRY_STATUS_UNKNOWN,
    is_retry_actionable,
    normalize_retry_actionability,
    program_display_name,
)

logger = logging.getLogger(__name__)

_SECRETISH = re.compile(
    r"(password|secret|api[_-]?key|authorization|token|smtp_password|raw_response|prompt)",
    re.IGNORECASE,
)
_STACK_LINE = re.compile(r"(File \".+\", line \d+|Traceback \(most recent call last\))")


def _esc(value: Any) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def _sanitize_text(text: Any, *, max_len: int = 400) -> str:
    raw = str(text or "").strip()
    if not raw:
        return ""
    if _SECRETISH.search(raw) or _STACK_LINE.search(raw):
        return "[생략: 민감 또는 개발자 로그]"
    if len(raw) > max_len:
        return raw[: max_len - 1] + "…"
    return raw


def failure_report_subject(incident: Mapping[str, Any]) -> str:
    display = incident.get("program_display") or program_display_name(
        str(incident.get("program_id") or "")
    )
    slot = str(incident.get("scheduled_slot") or "").strip()
    if incident.get("smoke_failure") or incident.get("smoke_only"):
        return f"[GENIE SMOKE 장애보고] {display} {slot} — 스모크 실패 (실슬롯 아님)"
    if incident.get("verification_only"):
        return f"[GENIE WATCHDOG TEST] {display} {slot} 검증용 장애보고 (실슬롯 아님)"
    return f"[GENIE 장애보고] {display} {slot} 자연실행 실패 — 재실행 승인 필요"


def recovery_success_subject(incident: Mapping[str, Any]) -> str:
    display = incident.get("program_display") or program_display_name(
        str(incident.get("program_id") or "")
    )
    slot = str(incident.get("scheduled_slot") or "").strip()
    return f"[GENIE 복구완료] {display} {slot} 재실행 성공"


def recovery_failure_subject(incident: Mapping[str, Any]) -> str:
    display = incident.get("program_display") or program_display_name(
        str(incident.get("program_id") or "")
    )
    slot = str(incident.get("scheduled_slot") or "").strip()
    return f"[GENIE 복구실패] {display} {slot} 재실행 실패"


def _direct_cause_ko(incident: Mapping[str, Any]) -> str:
    cause = incident.get("confirmed_cause")
    if cause is None or str(cause).strip() == "":
        return "원인 미확정"
    return _sanitize_text(cause, max_len=500)


def _list_block(title: str, items: List[str]) -> str:
    if not items:
        return f"<p><strong>{_esc(title)}</strong>: (없음)</p>"
    lis = "".join(f"<li>{_esc(_sanitize_text(i))}</li>" for i in items if str(i).strip())
    return f"<p><strong>{_esc(title)}</strong></p><ul>{lis}</ul>"


def _stage_table(stage_map: Mapping[str, Any]) -> str:
    rows = []
    for stage, status in stage_map.items():
        rows.append(
            f"<tr><td>{_esc(stage)}</td><td>{_esc(_sanitize_text(status, max_len=40))}</td></tr>"
        )
    return (
        '<table border="1" cellpadding="6" cellspacing="0" style="border-collapse:collapse;">'
        "<thead><tr><th>단계</th><th>상태</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )


def _kv_list(mapping: Mapping[str, Any]) -> str:
    items = "".join(
        f"<li><strong>{_esc(k)}</strong>: {_esc(_sanitize_text(v))}</li>"
        for k, v in mapping.items()
    )
    return f"<ul>{items}</ul>"


def _admin_cta_block(incident: Mapping[str, Any]) -> str:
    """View-only Admin deep-link CTA. Never encodes secrets or triggers recovery."""
    from admin_urls import build_incident_admin_url

    iid = str(incident.get("incident_id") or "").strip()
    smoke = bool(incident.get("smoke_failure") or incident.get("smoke_only"))
    verdict = normalize_retry_actionability(incident.get("retry_verdict"))
    url = build_incident_admin_url(iid) if iid else None

    if smoke:
        label = "검증 incident 보기"
        question = ""
    elif is_retry_actionable(verdict):
        label = "재실행 검토하기"
        question = '<p style="font-size:18px;"><strong>이 실행을 다시 시도할까요?</strong></p>'
    else:
        label = "장애 상세 보기"
        question = (
            "<p><strong>현재는 안전한 재실행 조건이 확보되지 않았습니다.</strong></p>"
        )

    if url:
        return f"""
{question}
<p style="margin:20px 0;">
<a href="{_esc(url)}" style="display:inline-block;background:#b91c1c;color:#fff;padding:12px 18px;text-decoration:none;border-radius:4px;font-weight:700;">
{_esc(label)}
</a>
</p>
<p style="color:#555;font-size:12px;">이 링크는 승인 화면을 <strong>보기만</strong> 엽니다. 클릭만으로 재실행되지 않습니다.</p>
"""
    return f"""
{question}
<p style="color:#7f1d1d;"><strong>Admin 바로가기 URL을 생성하지 못했습니다.</strong></p>
<p>운영 Admin에 로그인한 뒤 <code>/admin/incidents</code>에서 해당 incident_id를 열어
{_esc(label)} 경로로 확인하세요. (URL에 비밀값/토큰은 포함되지 않습니다.)</p>
"""


def build_failure_report_html(incident: Mapping[str, Any]) -> str:
    display = incident.get("program_display") or program_display_name(
        str(incident.get("program_id") or "")
    )
    slot = str(incident.get("scheduled_slot") or "")
    kst_date = str(incident.get("kst_date") or "")
    detected = str(incident.get("detected_at") or incident.get("created_at") or "")
    status = str(incident.get("status") or "reported")
    summary = _sanitize_text(
        incident.get("summary_ko")
        or "자연실행 SLA 실패가 감지되었습니다. 아래 사실·원인·결과를 확인한 뒤 재실행 여부를 결정해 주세요.",
        max_len=800,
    )
    facts = [str(x) for x in (incident.get("facts") or [])]
    hypotheses = [str(x) for x in (incident.get("hypotheses") or [])]
    unknowns = [str(x) for x in (incident.get("unknowns") or [])]
    stage_map = incident.get("stage_map") or {}
    outcomes = incident.get("outcomes") or {}
    system_status = incident.get("system_status") or {}
    verdict = normalize_retry_actionability(incident.get("retry_verdict"))
    verdict_ko = _sanitize_text(
        incident.get("retry_verdict_ko")
        or {
            RETRY_SAFE: "현재 장애는 종료됐으며 동일 실행을 다시 시도해도 고객 중복 발송 위험은 확인되지 않았습니다.",
            RETRY_SAFE_TO_RETRY: "현재 장애는 종료됐으며 동일 실행을 다시 시도해도 고객 중복 발송 위험은 확인되지 않았습니다.",
            RETRY_ALLOWED_WITH_WARNING: "원인이 완전히 제거되었는지는 확인되지 않을 수 있으나, 복구 실행은 운영자 검수용으로 격리되며 고객 발송은 하지 않습니다.",
            RETRY_REQUIRES_PATCH: "동일 원인이 남아 있을 수 있어 수정 완료 전에는 재실행하지 않는 것이 안전합니다.",
            RETRY_BLOCKED: "현재 상태에서는 재실행이 안전하지 않습니다.",
            RETRY_STATUS_UNKNOWN: "재실행 부작용을 확정하지 못했습니다. 추가 조사가 필요합니다.",
        }.get(verdict, "재실행 가능 여부를 확정하지 못했습니다."),
        max_len=500,
    )
    recommendation = _sanitize_text(
        incident.get("recommendation_ko") or "추가 조사 필요", max_len=200
    )
    contributing = ""
    if hypotheses:
        contributing = "<br>".join(_esc(_sanitize_text(h)) for h in hypotheses[:5])
    else:
        contributing = "(해당 없음 또는 미확정)"

    return f"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="utf-8"><title>GENIE 장애보고</title></head>
<body style="font-family:sans-serif;line-height:1.55;color:#111;max-width:720px;">
<h1>GENIE 자연실행 장애 보고</h1>
<p>
프로그램: <strong>{_esc(display)}</strong><br>
예정 실행: {_esc(kst_date)} {_esc(slot)} KST<br>
장애 감지: {_esc(detected)}<br>
현재 상태: {_esc(status)}<br>
재실행 여부: <strong>승인 대기</strong>
</p>
<hr>
<h2>1. 무슨 일이 발생했습니까?</h2>
<p>{_esc(summary)}</p>
<hr>
<h2>2. 어디까지 정상적으로 진행됐습니까?</h2>
{_stage_table(stage_map if isinstance(stage_map, dict) else {})}
<hr>
<h2>3. 장애 원인</h2>
<p><strong>직접 원인:</strong><br>{_esc(_direct_cause_ko(incident))}</p>
<p><strong>기여 원인:</strong><br>{contributing}</p>
<p><strong>탐지 상태:</strong><br>{_esc(_sanitize_text(incident.get("detection_note_ko") or "구조화 실패 이벤트 또는 Watchdog SLA 점검으로 감지했습니다."))}</p>
{_list_block("확인된 사실", facts)}
{_list_block("추정 또는 가능성", hypotheses)}
{_list_block("아직 확인되지 않은 사항", unknowns)}
<hr>
<h2>4. 이번 장애의 결과</h2>
{_kv_list(outcomes if isinstance(outcomes, dict) else {})}
<hr>
<h2>5. 현재 시스템 상태</h2>
{_kv_list(system_status if isinstance(system_status, dict) else {})}
<p style="color:#555;font-size:12px;">※ 「서비스 정상」은 health 200만으로 판단하지 않습니다. 위 항목은 확보된 증거에 근거합니다.</p>
<hr>
<h2>6. 재실행 가능 여부</h2>
<p>재실행 판정: <strong>{_esc(verdict)}</strong></p>
<p>{_esc(verdict_ko)}</p>
<hr>
<h2>7. 시스템 권고</h2>
<p>{_esc(recommendation)}</p>
<p>시스템이 실제 재실행을 수행하지 않습니다. Admin에서 명시적으로 승인해야 합니다.</p>
<hr>
<h2>8. 마지막 안내</h2>
{_admin_cta_block(incident)}
<p>승인 전에는 시스템이 자동 재실행하지 않습니다.</p>
<p style="color:#666;font-size:12px;">incident_id: {_esc(incident.get("incident_id"))}</p>
</body></html>
"""


def build_recovery_result_html(
    incident: Mapping[str, Any],
    *,
    success: bool,
) -> str:
    display = incident.get("program_display") or program_display_name(
        str(incident.get("program_id") or "")
    )
    title = "GENIE 복구완료" if success else "GENIE 복구실패"
    return f"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="utf-8"><title>{_esc(title)}</title></head>
<body style="font-family:sans-serif;line-height:1.55;color:#111;max-width:720px;">
<h1>{_esc(title)}</h1>
<p>
프로그램: <strong>{_esc(display)}</strong><br>
원 장애 incident: {_esc(incident.get("incident_id"))}<br>
승인 시각: {_esc(incident.get("recovery_approved_at"))}<br>
recovery run_id: {_esc(incident.get("recovery_run_id") or "(없음)")}<br>
결과: <strong>{"성공" if success else "실패"}</strong>
</p>
<hr>
<ul>
<li>원 장애 원인: {_esc(_direct_cause_ko(incident))}</li>
<li>생성 결과: {_esc((incident.get("recovery_outcomes") or {}).get("생성 결과", "확인불가") if isinstance(incident.get("recovery_outcomes"), dict) else "확인불가")}</li>
<li>validation: {_esc((incident.get("recovery_outcomes") or {}).get("validation", "확인불가") if isinstance(incident.get("recovery_outcomes"), dict) else "확인불가")}</li>
<li>artifact: {_esc((incident.get("recovery_outcomes") or {}).get("artifact", "확인불가") if isinstance(incident.get("recovery_outcomes"), dict) else "확인불가")}</li>
<li>owner-review SMTP: {_esc((incident.get("recovery_outcomes") or {}).get("owner_review_smtp", "확인불가") if isinstance(incident.get("recovery_outcomes"), dict) else "확인불가")}</li>
<li>고객 발송: <strong>수행하지 않음</strong></li>
<li>incident resolved: {"예" if success else "아니오 — 추가 자동 재실행 없음, 운영자 판단 대기"}</li>
</ul>
<p>추가 자동 재실행은 수행하지 않습니다.</p>
</body></html>
"""


def send_incident_email(
    *,
    subject: str,
    html_body: str,
    send_fn: Optional[Any] = None,
) -> bool:
    """Send to EMAIL_TO via shared sender. Never uses customer recipients."""
    sender = send_fn
    if sender is None:
        from email_sender import send_genie_email

        sender = send_genie_email
    try:
        return bool(sender(html_body, subject))
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "send_incident_email failed error_type=%s",
            type(exc).__name__,
        )
        return False


def send_failure_report(
    incident: Mapping[str, Any],
    *,
    send_fn: Optional[Any] = None,
) -> Tuple[bool, str]:
    subject = failure_report_subject(incident)
    html_body = build_failure_report_html(incident)
    ok = send_incident_email(subject=subject, html_body=html_body, send_fn=send_fn)
    return ok, subject


def send_recovery_report(
    incident: Mapping[str, Any],
    *,
    success: bool,
    send_fn: Optional[Any] = None,
) -> Tuple[bool, str]:
    subject = (
        recovery_success_subject(incident) if success else recovery_failure_subject(incident)
    )
    html_body = build_recovery_result_html(incident, success=success)
    ok = send_incident_email(subject=subject, html_body=html_body, send_fn=send_fn)
    return ok, subject
