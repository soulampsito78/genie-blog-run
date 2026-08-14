"""Read-only owner-facing projections for the server-rendered Admin.

The projection intentionally keeps operational artifacts authoritative. It
translates them for an owner without changing pipeline or persistence meaning.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, Iterable, Mapping, Optional
from zoneinfo import ZoneInfo


ACTIVE_PROGRAMS = (
    {
        "id": "today_genie",
        "display": "TODAY",
        "name": "Today Genie",
        "natural_time": "06:30",
        "preflight_time": "05:45",
    },
    {
        "id": "keysuri_global_tech",
        "display": "GLOBAL",
        "name": "KeeSuri Global Tech",
        "natural_time": "12:30",
        "preflight_time": "11:45",
    },
    {
        "id": "keysuri_korea_tech",
        "display": "KOREA",
        "name": "KeeSuri Korea Tech",
        "natural_time": "18:30",
        "preflight_time": "17:45",
    },
)

ACTIVE_PROGRAM_IDS = frozenset(program["id"] for program in ACTIVE_PROGRAMS)
PROGRAM_BY_ID = {program["id"]: program for program in ACTIVE_PROGRAMS}


def as_int(value: Any) -> Optional[int]:
    if value in (None, "", "미기록"):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def program_id(meta: Mapping[str, Any]) -> str:
    return str(meta.get("program_id") or meta.get("mode") or "").strip()


def is_active_program(meta: Mapping[str, Any]) -> bool:
    return program_id(meta) in ACTIVE_PROGRAM_IDS


def program_info(meta: Mapping[str, Any]) -> Dict[str, str]:
    pid = program_id(meta)
    return dict(
        PROGRAM_BY_ID.get(
            pid,
            {
                "id": pid,
                "display": pid.replace("_", " ").upper() or "UNKNOWN",
                "name": pid or "Unknown",
                "natural_time": "--:--",
                "preflight_time": "--:--",
            },
        )
    )


def display_time(meta: Mapping[str, Any]) -> str:
    for key in ("created_at", "created_at_kst", "completed_at", "owner_reviewed_at"):
        raw = str(meta.get(key) or "").strip()
        if not raw:
            continue
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if parsed.tzinfo is not None:
                parsed = parsed.astimezone(ZoneInfo("Asia/Seoul"))
            return parsed.strftime("%Y.%m.%d %H:%M")
        except ValueError:
            return raw
    rid = str(meta.get("run_id") or "")
    match = re.match(r"^(\d{8})_(\d{6})_", rid)
    if match:
        try:
            return datetime.strptime("".join(match.groups()), "%Y%m%d%H%M%S").strftime("%Y.%m.%d %H:%M")
        except ValueError:
            pass
    return "시각 미기록"


def run_date(meta: Mapping[str, Any]) -> str:
    shown = display_time(meta)
    return shown[:10] if len(shown) >= 10 and shown[4] == "." else "날짜 미기록"


def run_origin(meta: Mapping[str, Any]) -> str:
    if meta.get("recovery_run") or meta.get("original_incident_id") or meta.get("recovery_for_incident_id"):
        return "장애 복구 실행"
    if meta.get("admin_reissue") or meta.get("parent_run_id") or meta.get("reissue_scope"):
        scope = str(meta.get("reissue_scope") or "")
        labels = {
            "body_only": "본문 재생성",
            "image_only": "이미지 재생성",
            "body_and_image": "본문·이미지 재생성",
        }
        return labels.get(scope, "재발행 실행")
    trigger = str(meta.get("trigger_source") or "").lower()
    if "manual" in trigger:
        return "수동 실행"
    return "자연 실행"


def issue_codes(meta: Mapping[str, Any]) -> list[str]:
    found: list[str] = []
    for key in ("terminal_issue_codes", "issue_codes", "validation_issue_codes"):
        value = meta.get(key)
        if isinstance(value, list):
            found.extend(str(item) for item in value if str(item).strip())
        elif isinstance(value, str) and value.strip():
            found.extend(part.strip() for part in re.split(r"[,;]", value) if part.strip())
    result = meta.get("validation_result")
    if isinstance(result, dict):
        nested = result.get("issue_codes")
        if isinstance(nested, list):
            found.extend(str(item) for item in nested if str(item).strip())
    return list(dict.fromkeys(found))


def validation_is_pass(meta: Mapping[str, Any]) -> bool:
    value = meta.get("validation_result")
    if isinstance(value, dict):
        value = value.get("status") or value.get("result")
    key = str(value or "").strip().lower()
    return key in {"pass", "passed", "ok", "valid", "success"}


def validation_is_failed(meta: Mapping[str, Any]) -> bool:
    value = meta.get("validation_result")
    if isinstance(value, dict):
        value = value.get("status") or value.get("result")
    key = str(value or "").strip().lower()
    return key in {"block", "blocked", "fail", "failed", "invalid"} or str(meta.get("artifact_status") or "") == "failed"


def validation_projection(meta: Mapping[str, Any]) -> Dict[str, Any]:
    issues = issue_codes(meta)
    image_present = any(
        meta.get(key)
        for key in (
            "generated_image_path",
            "generated_image_path_watermarked",
            "customer_top_image_path",
            "run_specific_images",
            "top_image_cid",
        )
    )
    if validation_is_pass(meta):
        checks = [
            {"label": "필수 구성 정상", "tone": "good"},
            {
                "label": "이미지 정상" if image_present else "이미지 증거는 기술 세부정보에서 확인",
                "tone": "good" if image_present else "warn",
            },
            {"label": "콘텐츠 가드레일 통과", "tone": "good"},
        ]
        return {
            "label": "검수 통과",
            "tone": "good",
            "summary": "고객 발송 검토를 진행할 수 있습니다.",
            "checks": checks,
            "issues": issues,
        }
    if validation_is_failed(meta):
        joined = " ".join(issues).lower()
        if "image" in joined:
            category = "이미지 검수"
        elif any(token in joined for token in ("news", "source", "briefing", "content")):
            category = "콘텐츠 검수"
        elif "financial" in joined or "investment" in joined:
            category = "금융 가드레일"
        else:
            category = "필수 구성 검수"
        return {
            "label": "검수 차단",
            "tone": "danger",
            "summary": f"{category}에서 문제가 확인되었습니다. 고객 발송은 차단되어 보호되었습니다.",
            "checks": [
                {"label": f"실패 범주: {category}", "tone": "danger"},
                {"label": "고객 발송 차단됨", "tone": "good"},
                {"label": "권장 행동: 장애·복구 또는 다시 만들기 검토", "tone": "warn"},
            ],
            "issues": issues,
        }
    return {
        "label": "검수 근거 확인 필요",
        "tone": "warn",
        "summary": "검수 결과가 충분히 기록되지 않았습니다. 발송 전 기술 근거를 확인하세요.",
        "checks": [
            {"label": "검수 결과 미확정", "tone": "warn"},
            {"label": "고객 발송 상태를 별도로 확인", "tone": "warn"},
        ],
        "issues": issues,
    }


def delivery_projection(meta: Mapping[str, Any]) -> Dict[str, Any]:
    status = str(
        meta.get("customer_email_delivery_status")
        or meta.get("customer_delivery_status")
        or "not_sent"
    ).strip().lower()
    accepted = as_int(meta.get("smtp_accepted_recipient_count"))
    refused = as_int(meta.get("smtp_refused_recipient_count"))
    if refused is None and isinstance(meta.get("smtp_refused_recipients_masked"), list):
        refused = len(meta.get("smtp_refused_recipients_masked") or [])
    total = as_int(meta.get("customer_email_recipient_count"))
    if total is None:
        total = as_int(meta.get("customer_recipient_count"))
    if accepted is None and total is not None and refused is not None and status == "smtp_accepted":
        accepted = max(0, total - refused)

    base = {
        "status_code": status,
        "accepted": accepted,
        "refused": refused,
        "total": total,
        "sent_at": meta.get("customer_email_sent_at_kst") or meta.get("customer_sent_at") or meta.get("customer_delivery_completed_at"),
        "receipt_confirmed": False,
        "unknown": as_int(meta.get("customer_delivery_unknown_count")),
    }
    if status == "partial_refusal" or ((accepted or 0) > 0 and (refused or 0) > 0):
        return {
            **base,
            "label": "PARTIAL DELIVERY",
            "label_ko": "일부 수신자 거절",
            "tone": "danger",
            "summary": f"SMTP 접수 {accepted}명 · 즉시 거절 {refused}명. 수신함 도착은 확인되지 않았습니다.",
            "flow": "승인 → SMTP 일부 접수 → 일부 거절",
        }
    if status in {"refused_all"}:
        return {
            **base,
            "label": "REFUSED ALL",
            "label_ko": "전체 즉시 거절",
            "tone": "danger",
            "summary": f"{refused or total or 0}명 모두 SMTP 단계에서 즉시 거절되었습니다. 자동 재전송하지 않습니다.",
            "flow": "승인 → SMTP 전체 즉시 거절",
        }
    if status in {"failed", "rejected", "bounced"}:
        return {
            **base,
            "label": "SEND FAILED",
            "label_ko": "발송 실패",
            "tone": "danger",
            "summary": "SMTP 발송이 완료되지 않았습니다. 고객 수신은 확인되지 않았습니다.",
            "flow": "승인 → 발송 실패",
        }
    if status in {"outcome_unknown"}:
        return {
            **base,
            "label": "RESULT UNKNOWN",
            "label_ko": "결과 확인 필요",
            "tone": "danger",
            "summary": "SMTP 제출 요청 이후 결과를 확정하지 못했습니다. 중복 위험 때문에 자동 재시도하지 않습니다.",
            "flow": "승인 → SMTP 제출 시도 → 결과 확인 필요",
        }
    if status in {"submitted", "send_attempted", "sending", "pending"}:
        return {
            **base,
            "label": "SEND PENDING",
            "label_ko": "발송 결과 확인 중",
            "tone": "warn",
            "summary": "발송 시도 기록은 있으나 최종 SMTP 결과가 확정되지 않았습니다.",
            "flow": "승인 → 발송 결과 확인 중",
        }
    if status in {"accepted_all", "smtp_accepted", "sent_after_approval", "approved"}:
        if accepted is not None and (refused or 0) == 0:
            return {
                **base,
                "label": "SMTP SUBMITTED",
                "label_ko": "SMTP 접수",
                "tone": "good",
                "summary": f"{accepted}명 SMTP 접수. 실제 수신함 도착을 의미하지 않습니다.",
                "flow": f"검수 통과 → 승인 → {accepted}명 SMTP 접수",
            }
        return {
            **base,
            "label": "RESULT UNKNOWN",
            "label_ko": "결과 근거 부족",
            "tone": "warn",
            "summary": "SMTP 접수 상태는 있으나 접수·거절 인원 근거가 충분하지 않습니다. 수신함 도착은 확인되지 않았습니다.",
            "flow": "승인 → SMTP 상태 기록 → 인원 근거 확인 필요",
        }
    if status in {"not_sent", "", "blocked"}:
        return {
            **base,
            "label": "NOT SENT",
            "label_ko": "미발송 / 고객 발송 없음",
            "tone": "neutral" if status != "blocked" else "warn",
            "summary": "고객에게 발송되지 않았습니다.",
            "flow": "고객 발송 없음",
        }
    return {
        **base,
        "label": "RESULT UNKNOWN",
        "label_ko": "결과 미확정",
        "tone": "warn",
        "summary": "현재 기록만으로 고객 발송 결과를 확정할 수 없습니다. 수신함 도착은 확인되지 않았습니다.",
        "flow": "발송 결과 확인 필요",
    }


def subject(meta: Mapping[str, Any]) -> str:
    for key in (
        "customer_email_subject",
        "email_subject",
        "subject",
        "owner_email_subject",
        "briefing_subject",
    ):
        value = str(meta.get(key) or "").strip()
        if value:
            return value
    return f"{program_info(meta)['name']} 브리핑"


def owner_state(meta: Mapping[str, Any]) -> Dict[str, str]:
    delivery = delivery_projection(meta)
    if delivery["label"] in {"PARTIAL DELIVERY", "REFUSED ALL", "RESULT UNKNOWN"}:
        return {
            "label": "발송 결과 확인 필요",
            "tone": "danger",
            "impact": delivery["summary"],
            "action": "발송 근거 확인",
        }
    if delivery["label"] == "SMTP SUBMITTED":
        return {
            "label": "SMTP 접수 완료",
            "tone": delivery["tone"],
            "impact": delivery["summary"],
            "action": "발송 결과 보기",
        }
    if validation_is_failed(meta):
        return {
            "label": "검수 실패",
            "tone": "danger",
            "impact": "고객 발송이 차단되었습니다.",
            "action": "장애 확인",
        }
    owner = str(meta.get("owner_review_status") or meta.get("workflow_status") or "").lower()
    if owner == "held":
        return {
            "label": "발송 보류",
            "tone": "neutral",
            "impact": "Owner가 고객 발송을 보류했습니다.",
            "action": "다시 검수하기",
        }
    if owner in {"pending_review", "review_required", "validated", "emailed", "reissued", "reopened"} or validation_is_pass(meta):
        return {
            "label": "검수 대기",
            "tone": "warn",
            "impact": "고객 발송 전 owner 결정이 필요합니다.",
            "action": "검수하기",
        }
    return {
        "label": "상태 확인 필요",
        "tone": "info",
        "impact": "최근 실행 근거를 확인하세요.",
        "action": "상태 보기",
    }


def run_projection(meta: Mapping[str, Any], *, current_recipient_count: Optional[int] = None) -> Dict[str, Any]:
    info = program_info(meta)
    validation = validation_projection(meta)
    delivery = delivery_projection(meta)
    state = owner_state(meta)
    recipient_count = delivery.get("total")
    if recipient_count is None:
        recipient_count = current_recipient_count
    raw_delivery_status = str(meta.get("customer_delivery_status") or meta.get("customer_email_delivery_status") or "").lower()
    already_sent = raw_delivery_status in {
        "smtp_accepted", "sent_after_approval", "approved", "submitted", "accepted_all",
        "partial_refusal", "refused_all", "outcome_unknown"
    } or str(meta.get("owner_review_status") or "").lower() == "approved"
    return {
        "run_id": str(meta.get("run_id") or ""),
        "program": info,
        "time": display_time(meta),
        "date": run_date(meta),
        "origin": run_origin(meta),
        "subject": subject(meta),
        "validation": validation,
        "delivery": delivery,
        "state": state,
        "recipient_count": recipient_count,
        "already_sent": already_sent,
        "parent_run_id": meta.get("parent_run_id") or "",
        "incident_id": meta.get("original_incident_id") or meta.get("incident_id") or "",
        "revision": meta.get("deployed_revision") or meta.get("revision") or meta.get("runtime_revision") or "",
    }


def latest_by_program(runs: Iterable[Mapping[str, Any]]) -> Dict[str, Mapping[str, Any]]:
    latest: Dict[str, Mapping[str, Any]] = {}
    for meta in runs:
        pid = program_id(meta)
        if pid in ACTIVE_PROGRAM_IDS and pid not in latest:
            latest[pid] = meta
    return latest


def needs_review(meta: Mapping[str, Any]) -> bool:
    if not is_active_program(meta) or validation_is_failed(meta):
        return False
    delivery = delivery_projection(meta)
    if delivery["label"] not in {"NOT SENT", "SEND FAILED"}:
        return False
    owner = str(meta.get("owner_review_status") or meta.get("workflow_status") or "").lower()
    return owner not in {"approved", "dismissed", "held"} and validation_is_pass(meta)


def incident_projection(meta: Mapping[str, Any]) -> Dict[str, Any]:
    pid = str(meta.get("program_id") or "")
    info = PROGRAM_BY_ID.get(pid, {"display": str(meta.get("program_display") or pid).upper(), "name": str(meta.get("program_display") or pid)})
    status = str(meta.get("status") or "open")
    outcomes = meta.get("outcomes") if isinstance(meta.get("outcomes"), dict) else {}
    raw_customer = outcomes.get("고객 메일") or meta.get("recovery_customer_send_count")
    sent = bool(raw_customer and str(raw_customer).strip() not in {"0", "발송되지 않음", "not_sent", "없음"})
    recovery_id = str(meta.get("recovery_run_id") or "")
    if status == "recovery_succeeded":
        current = "복구 완료"
        next_action = "복구본 검수하기" if recovery_id else "복구 결과 확인"
        tone = "good"
    elif status in {"reported", "open", "recovery_failed", "retry_blocked_pending_patch"}:
        current = "운영자 판단 필요"
        next_action = "안전한 다음 행동 확인"
        tone = "danger" if status == "recovery_failed" else "warn"
    elif status == "dismissed":
        current = "종료됨"
        next_action = "기록 보기"
        tone = "neutral"
    else:
        current = "상태 확인 필요"
        next_action = "상세 보기"
        tone = "warn"
    return {
        "incident_id": str(meta.get("incident_id") or ""),
        "program": info,
        "scheduled": f"{meta.get('kst_date') or ''} {meta.get('scheduled_slot') or ''}".strip(),
        "status": status,
        "current": current,
        "tone": tone,
        "customer_impact": "고객 발송 기록 있음 — 상세 확인 필요" if sent else "고객 발송 없음",
        "duplicate_risk": "기록 확인 필요" if sent else "중복 발송 위험 없음",
        "failed_stage": str(meta.get("first_failed_stage") or "실패 단계 미확정"),
        "system_action": [
            "장애 기록 완료",
            "고객 자동 발송 없음",
            *( ["복구 실행 기록 있음"] if recovery_id else [] ),
        ],
        "next_action": next_action,
        "recovery_run_id": recovery_id,
    }
