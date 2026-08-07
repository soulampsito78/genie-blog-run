"""Natural-run SLA watchdog: diagnose → Korean report → wait.

NEVER auto-retries, NEVER posts production recovery, NEVER customer-sends.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence
from zoneinfo import ZoneInfo

from natural_run_incident_report import send_failure_report
from natural_run_incident_store import (
    NATURAL_SLOTS,
    PROGRAM_DISPLAY,
    RETRY_REQUIRES_PATCH,
    RETRY_SAFE_TO_RETRY,
    RETRY_STATUS_UNKNOWN,
    STATUS_REPORTED,
    empty_stage_map,
    kst_date_str,
    load_incident,
    make_incident_id,
    mark_report_sent,
    new_incident,
    normalize_slot,
    save_incident,
    upsert_incident,
)
from today_genie_execution_identity import (
    EXECUTION_CLASS_NATURAL_SCHEDULED,
    EXECUTION_CLASS_QA_MANUAL,
    natural_slot_completer_qualification,
)

logger = logging.getLogger(__name__)
KST = ZoneInfo("Asia/Seoul")

PAUSED_PROGRAMS = frozenset({"tomorrow_genie"})

# Minutes after scheduled slot before SLA miss is confirmable.
SLA_GRACE_MINUTES = 15


def _slot_hour_minute(slot: str) -> tuple[int, int]:
    norm = normalize_slot(slot)
    parts = norm.split(":")
    return int(parts[0]), int(parts[1])


def schedule_elapsed(
    *,
    program_id: str,
    now: Optional[datetime] = None,
    grace_minutes: int = SLA_GRACE_MINUTES,
) -> bool:
    """True when current KST time is past slot + grace on a weekday."""
    if now is None:
        now = datetime.now(KST)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=KST)
    else:
        now = now.astimezone(KST)
    if now.weekday() >= 5:
        return False
    slot = NATURAL_SLOTS.get(program_id)
    if not slot:
        return False
    hh, mm = _slot_hour_minute(slot)
    threshold = now.replace(hour=hh, minute=mm, second=0, microsecond=0) + timedelta(
        minutes=grace_minutes
    )
    return now >= threshold


def _artifacts_for_program(
    artifacts: Sequence[Mapping[str, Any]],
    program_id: str,
) -> List[Mapping[str, Any]]:
    out = []
    for raw in artifacts:
        mode = str(raw.get("mode") or raw.get("program_id") or "").strip()
        if mode == program_id:
            out.append(raw)
    return out


def _natural_completer_exists(
    artifacts: Sequence[Mapping[str, Any]],
    *,
    program_id: str,
    kst_date: str,
    scheduled_slot: str,
) -> Optional[Mapping[str, Any]]:
    date_prefix = kst_date.replace("-", "") + "_"
    for raw in artifacts:
        mode = str(raw.get("mode") or raw.get("program_id") or "").strip()
        if mode != program_id:
            continue
        run_id = str(raw.get("run_id") or "")
        if not run_id.startswith(date_prefix):
            continue
        if program_id == "today_genie":
            match = natural_slot_completer_qualification(
                raw,
                program_id=program_id,
                kst_date=kst_date,
                scheduled_slot=scheduled_slot,
            )
            if match.qualifies:
                return raw
        else:
            # KeeSuri: successful emailed non-reissue parent counts as natural completer
            # when execution_class is natural_scheduled OR legacy emailed scheduled trigger.
            if raw.get("parent_run_id"):
                continue
            cls = str(raw.get("execution_class") or "").strip()
            if cls and cls != EXECUTION_CLASS_NATURAL_SCHEDULED:
                continue
            if cls == EXECUTION_CLASS_QA_MANUAL:
                continue
            if bool(raw.get("email_sent")) and str(raw.get("validation_result") or "") != "block":
                if not cls:
                    # Legacy KeeSuri without class: treat emailed as completer for SLA
                    # (recovery still stamps recovery class separately).
                    return raw
                return raw
    return None


def diagnose_program_sla(
    *,
    program_id: str,
    artifacts: Sequence[Mapping[str, Any]],
    failure_events: Optional[Sequence[Mapping[str, Any]]] = None,
    request_evidence: Optional[Mapping[str, Any]] = None,
    now: Optional[datetime] = None,
    scheduler_paused: bool = False,
) -> Optional[Dict[str, Any]]:
    """Return a new incident dict if SLA failed; None if OK / not yet due / paused."""
    if program_id in PAUSED_PROGRAMS or scheduler_paused:
        return None
    if program_id not in NATURAL_SLOTS:
        return None
    if not schedule_elapsed(program_id=program_id, now=now):
        return None

    kst_date = kst_date_str(now)
    slot = NATURAL_SLOTS[program_id]
    completer = _natural_completer_exists(
        artifacts, program_id=program_id, kst_date=kst_date, scheduled_slot=slot
    )
    if completer is not None:
        return None

    stage = empty_stage_map()
    facts: List[str] = []
    hypotheses: List[str] = []
    unknowns: List[str] = [
        "Cloud Logging 원문 전체",
        "Scheduler HTTP 응답 본문",
    ]
    confirmed_cause: Optional[str] = None
    detection_note = "Watchdog가 예정 슬롯 이후 자연실행 완료 artifact를 찾지 못했습니다."
    summary = (
        f"오늘 {slot} {PROGRAM_DISPLAY.get(program_id, program_id)} 자연실행이 "
        "완료된 것으로 확인되지 않았습니다. 운영자 검수 메일 발송 여부도 확인되지 않았습니다."
    )
    retry_verdict = RETRY_STATUS_UNKNOWN
    retry_ko = "재실행 가능 여부를 확정하지 못했습니다. 추가 조사가 필요합니다."
    recommendation = "추가 조사 필요"
    first_failed = "unknown"
    error_code = "natural_sla_miss"
    outcomes = {
        "자연실행 artifact": "생성되지 않음",
        "운영자 검수 메일": "발송되지 않음",
        "이미지 생성": "미실행 또는 확인불가",
        "SMTP 시도": "확인되지 않음",
        "고객 메일": "발송되지 않음",
        "데이터/Artifact 손상": "확인되지 않음",
        "중복 발송": "없음",
    }

    prog_artifacts = _artifacts_for_program(artifacts, program_id)
    same_day = [
        a
        for a in prog_artifacts
        if str(a.get("run_id") or "").startswith(kst_date.replace("-", "") + "_")
    ]
    qa_same_day = [
        a
        for a in same_day
        if str(a.get("execution_class") or "") == EXECUTION_CLASS_QA_MANUAL
        or (
            not str(a.get("execution_class") or "")
            and bool(a.get("email_sent"))
            and program_id == "today_genie"
            and not str(a.get("run_id") or "").split("_")[1].startswith("06")
        )
    ]

    ev = request_evidence or {}
    if ev.get("scheduler_fired") is True:
        stage["Scheduler"] = "정상"
        facts.append("Scheduler가 예정 시각에 HTTP 요청을 전달한 기록이 있습니다.")
    elif ev.get("scheduler_fired") is False:
        stage["Scheduler"] = "실패"
        facts.append("Scheduler 실행 기록이 없습니다.")
        confirmed_cause = "Scheduler가 예정 시각에 실행되지 않았습니다."
        first_failed = "scheduler"
        error_code = "scheduler_not_triggered"
        retry_verdict = RETRY_SAFE_TO_RETRY
        retry_ko = (
            "현재 장애는 종료됐으며 동일 실행을 다시 시도해도 "
            "고객에게 중복 메일이 발송될 위험은 확인되지 않았습니다."
        )
        recommendation = "즉시 재실행 가능"
        summary = (
            f"오늘 {slot} {PROGRAM_DISPLAY.get(program_id, program_id)} 자연실행이 "
            "Scheduler에서 트리거되지 않은 것으로 확인됩니다. 브리핑 생성과 운영자 메일은 실행되지 않았습니다."
        )
    else:
        stage["Scheduler"] = "확인불가"
        unknowns.append("Scheduler 발화 여부")

    if ev.get("cloud_run_status") == 200:
        stage["Cloud Run"] = "정상"
        facts.append(f"Cloud Run이 HTTP {ev.get('cloud_run_status')}을 반환했습니다.")
        if ev.get("latency_seconds") is not None and float(ev.get("latency_seconds") or 0) < 30:
            stage["실행 게이트"] = "실패"
            hypotheses.append(
                "짧은 응답 시간으로 미루어 생성 파이프라인 전에 게이트에서 중단됐을 가능성이 있습니다."
            )
            if qa_same_day and confirmed_cause is None:
                confirmed_cause = (
                    "QA/수동 실행을 동일 날짜의 자연실행 완료로 잘못 판단했습니다."
                )
                facts.append(
                    f"동일 KST 날짜 QA/수동 artifact가 존재합니다 "
                    f"(예: {qa_same_day[0].get('run_id')})."
                )
                hypotheses.append("기존 중복 판정 키가 실행 종류를 구분하지 않았을 수 있습니다.")
                detection_note = (
                    "기존에는 HTTP 200으로 처리돼 장애가 자동 보고되지 않았을 수 있습니다."
                )
                first_failed = "natural_slot_duplicate_gate"
                error_code = "qa_consumed_natural_slot"
                retry_verdict = RETRY_REQUIRES_PATCH
                retry_ko = (
                    "동일 원인이 아직 남아 있어 지금 재실행하면 같은 실패가 반복될 "
                    "가능성이 높습니다. 수정 완료 전에는 재실행하지 않는 것이 안전합니다."
                )
                recommendation = "수정 후 재실행 권고"
                summary = (
                    f"오늘 {slot} {PROGRAM_DISPLAY.get(program_id, program_id)} 자연실행 요청은 "
                    "Scheduler에서 전달됐지만, 실행 중복 판정 단계에서 중단된 것으로 보입니다. "
                    "브리핑 생성, 이미지 생성, 운영자 검수 메일 발송은 실행되지 않았습니다."
                )
                for key in ("데이터 수집", "콘텐츠 생성", "검증", "이미지", "Artifact", "운영자 메일"):
                    stage[key] = "미실행"
    elif ev.get("cloud_run_status"):
        stage["Cloud Run"] = "실패"
        facts.append(f"Cloud Run HTTP 상태: {ev.get('cloud_run_status')}")
        first_failed = "cloud_run"
        error_code = f"cloud_run_http_{ev.get('cloud_run_status')}"
    else:
        stage["Cloud Run"] = "확인불가"

    # Failure events enrichment
    for fe in failure_events or []:
        if str(fe.get("program_id") or "") != program_id:
            continue
        facts.append(
            f"구조화 실패 이벤트: error_code={fe.get('error_code')} "
            f"stage={fe.get('first_failed_stage')}"
        )
        stage["실행 게이트"] = stage.get("실행 게이트") if stage.get("실행 게이트") != "확인불가" else "실패"
        if confirmed_cause is None and fe.get("error_code"):
            # Do not promote event code to confirmed cause without mapping.
            hypotheses.append(f"실패 이벤트 코드 {fe.get('error_code')}와 관련됐을 수 있습니다.")
        first_failed = str(fe.get("first_failed_stage") or first_failed)
        error_code = str(fe.get("error_code") or error_code)
        code = str(fe.get("error_code") or "")
        if "smtp" in code or fe.get("first_failed_stage") == "email_delivery":
            stage["운영자 메일"] = "실패"
            stage["콘텐츠 생성"] = "정상"
            stage["Artifact"] = "정상" if fe.get("artifact_saved") else "실패"
            outcomes["SMTP 시도"] = "실패"
            outcomes["자연실행 artifact"] = (
                "생성됨" if fe.get("artifact_saved") else "생성 실패"
            )
            outcomes["운영자 검수 메일"] = "발송 실패"
            if confirmed_cause is None:
                confirmed_cause = "운영자 검수 메일 SMTP 전송에 실패했습니다."
            retry_verdict = RETRY_SAFE_TO_RETRY
            recommendation = "즉시 재실행 가능"
        elif "validation" in code or fe.get("first_failed_stage") in {
            "generation_validation",
            "validation_hold",
        }:
            stage["검증"] = "실패"
            stage["콘텐츠 생성"] = "정상"
            if confirmed_cause is None:
                confirmed_cause = "생성 결과 검증에서 차단되었습니다."
            retry_verdict = RETRY_REQUIRES_PATCH
            recommendation = "수정 후 재실행 권고"
        elif fe.get("first_failed_stage") in {"image_generation", "service_full_run"}:
            stage["이미지"] = "실패"
            if confirmed_cause is None and "image" in code:
                confirmed_cause = "이미지 생성 단계에서 실패했습니다."
        elif "generation" in code or fe.get("first_failed_stage") == "generation_validation":
            stage["콘텐츠 생성"] = "실패"
            if confirmed_cause is None:
                confirmed_cause = "모델 콘텐츠 생성에 실패했습니다."

    if same_day and not completer:
        facts.append(f"동일 KST 날짜 관련 artifact {len(same_day)}건이 있으나 자연실행 완료로 인정되지 않습니다.")

    system_status = {
        "서비스 상태": "확인불가",
        "Cloud Run": stage.get("Cloud Run", "확인불가"),
        "Scheduler": stage.get("Scheduler", "확인불가"),
        "장애 실행": "종료",
        "다음 정규 실행": "영향 없음",
    }
    if ev.get("service_ready") is True and ev.get("health_ok") is True:
        system_status["서비스 상태"] = "정상(Ready+헬스+게이트 증거 기준)"
    elif ev.get("health_ok") is True and ev.get("service_ready") is not True:
        system_status["서비스 상태"] = "부분 확인(health만 확인, Ready 미확인)"

    incident = new_incident(
        program_id=program_id,
        kst_date=kst_date,
        scheduled_slot=slot,
        facts=facts,
        confirmed_cause=confirmed_cause,
        hypotheses=hypotheses,
        unknowns=unknowns,
        stage_map=stage,
        retry_verdict=retry_verdict,
        retry_verdict_ko=retry_ko,
        recommendation_ko=recommendation,
        first_failed_stage=first_failed,
        error_code=error_code,
        system_status=system_status,
        outcomes=outcomes,
        summary_ko=summary,
    )
    incident["detection_note_ko"] = detection_note
    return incident


def report_incident_once(
    incident: Dict[str, Any],
    *,
    send_fn: Optional[Callable[..., bool]] = None,
) -> Dict[str, Any]:
    """Persist + send Korean failure report at most once. Never recovers."""
    incident_id = str(incident.get("incident_id") or "")
    existing = load_incident(incident_id)
    if existing and existing.get("report_sent_at"):
        return {
            "ok": True,
            "incident_id": incident_id,
            "report_sent": False,
            "deduped": True,
            "auto_retry": 0,
        }
    if existing:
        merged = upsert_incident(incident)
    else:
        save_incident(incident)
        merged = incident

    ok, subject = send_failure_report(merged, send_fn=send_fn)
    if ok:
        mark_report_sent(incident_id)
    return {
        "ok": ok,
        "incident_id": incident_id,
        "report_sent": ok,
        "deduped": False,
        "subject": subject,
        "auto_retry": 0,
        "status": STATUS_REPORTED if ok else merged.get("status"),
    }


def notify_natural_run_incident_from_failure(
    *,
    program_id: str,
    run_id: str = "",
    trigger_source: str = "",
    first_failed_stage: str = "",
    error_code: str = "",
    issue_codes: Optional[Sequence[Any]] = None,
    email_sent: bool = False,
    artifact_saved: bool = False,
    extra_fields: Optional[Mapping[str, Any]] = None,
    artifacts: Optional[Sequence[Mapping[str, Any]]] = None,
    send_fn: Optional[Callable[..., bool]] = None,
    now: Optional[datetime] = None,
    dry_run: bool = False,
) -> Optional[Dict[str, Any]]:
    """Hook from failure emitters. Idempotent. Never auto-retries."""
    if dry_run:
        return None
    if program_id in PAUSED_PROGRAMS:
        return None
    if program_id not in NATURAL_SLOTS:
        # Gate synthetic run_ids may still map to today_genie via extra fields.
        if str((extra_fields or {}).get("program_id") or "") in NATURAL_SLOTS:
            program_id = str(extra_fields.get("program_id"))
        elif program_id != "today_genie":
            return None

    slot = normalize_slot(
        str((extra_fields or {}).get("scheduled_slot") or NATURAL_SLOTS.get(program_id, ""))
    )
    kst_date = str((extra_fields or {}).get("kst_schedule_date") or kst_date_str(now))
    fe = {
        "program_id": program_id,
        "run_id": run_id,
        "trigger_source": trigger_source,
        "first_failed_stage": first_failed_stage,
        "error_code": error_code,
        "issue_codes": list(issue_codes or []),
        "email_sent": email_sent,
        "artifact_saved": artifact_saved,
    }
    request_evidence = {
        "scheduler_fired": True,
        "cloud_run_status": 200 if error_code != "scheduler_not_triggered" else None,
        "latency_seconds": (extra_fields or {}).get("latency_seconds"),
    }
    # Build targeted diagnosis from the failure event itself.
    incident = diagnose_program_sla(
        program_id=program_id,
        artifacts=artifacts or [],
        failure_events=[fe],
        request_evidence=request_evidence,
        now=now,
    )
    if incident is None:
        # Force an incident for explicit gate/runtime failures even before grace.
        incident = new_incident(
            program_id=program_id,
            kst_date=kst_date,
            scheduled_slot=slot,
            confirmed_cause=None,
            facts=[
                f"실패 이벤트 수신: stage={first_failed_stage} code={error_code}",
            ],
            hypotheses=[],
            unknowns=["전체 파이프라인 단계 증거"],
            first_failed_stage=first_failed_stage or "unknown",
            error_code=error_code or "unknown",
            issue_codes=[str(x) for x in (issue_codes or [])],
            failure_event=fe,
            summary_ko=(
                f"{PROGRAM_DISPLAY.get(program_id, program_id)} 자연실행 경로에서 "
                f"장애가 감지되었습니다. 자동 재실행은 하지 않습니다."
            ),
            retry_verdict=RETRY_STATUS_UNKNOWN,
            recommendation_ko="추가 조사 필요",
        )
        # Map known codes to confirmed causes carefully.
        code = str(error_code or "")
        if code in {"qa_consumed_natural_slot", "invalid_natural_slot_duplicate_match"}:
            incident["confirmed_cause"] = (
                "QA/수동 실행을 동일 날짜의 자연실행 완료로 잘못 판단했습니다."
            )
            incident["retry_verdict"] = RETRY_REQUIRES_PATCH
            incident["recommendation_ko"] = "수정 후 재실행 권고"
            incident["detection_note_ko"] = (
                "기존에는 HTTP 200으로 처리돼 장애가 자동 보고되지 않았을 수 있습니다."
            )
        elif code == "execution_class_required":
            incident["confirmed_cause"] = (
                "자연실행 요청에 실행 분류(execution_class)가 없어 안전하게 거부되었습니다."
            )
            incident["retry_verdict"] = RETRY_REQUIRES_PATCH
            incident["recommendation_ko"] = "수정 후 재실행 권고"
        elif "smtp" in code:
            incident["confirmed_cause"] = "운영자 검수 메일 SMTP 전송에 실패했습니다."
            incident["retry_verdict"] = RETRY_SAFE_TO_RETRY
            incident["recommendation_ko"] = "즉시 재실행 가능"
        # else leave 원인 미확정
        incident["incident_id"] = make_incident_id(program_id, kst_date, slot)
        incident["original_run_id"] = run_id or None
        stage = empty_stage_map()
        stage["Scheduler"] = "정상"
        stage["Cloud Run"] = "정상"
        stage["실행 게이트"] = "실패"
        incident["stage_map"] = stage

    incident["original_run_id"] = run_id or incident.get("original_run_id")
    incident["failure_event"] = fe
    return report_incident_once(incident, send_fn=send_fn)


def run_watchdog_poll(
    *,
    artifacts: Sequence[Mapping[str, Any]],
    failure_events: Optional[Sequence[Mapping[str, Any]]] = None,
    request_evidence_by_program: Optional[Mapping[str, Mapping[str, Any]]] = None,
    paused_programs: Optional[Sequence[str]] = None,
    now: Optional[datetime] = None,
    send_fn: Optional[Callable[..., bool]] = None,
    programs: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """Periodic SLA poll. Reports only; auto_retry always 0."""
    paused = set(paused_programs or []) | set(PAUSED_PROGRAMS)
    targets = list(programs or NATURAL_SLOTS.keys())
    results = []
    for program_id in targets:
        if program_id in paused:
            results.append(
                {
                    "program_id": program_id,
                    "skipped": True,
                    "reason": "paused",
                    "report_sent": False,
                    "auto_retry": 0,
                }
            )
            continue
        evidence = (request_evidence_by_program or {}).get(program_id)
        incident = diagnose_program_sla(
            program_id=program_id,
            artifacts=artifacts,
            failure_events=failure_events,
            request_evidence=evidence,
            now=now,
            scheduler_paused=program_id in paused,
        )
        if incident is None:
            results.append(
                {
                    "program_id": program_id,
                    "sla_ok_or_pending": True,
                    "report_sent": False,
                    "auto_retry": 0,
                }
            )
            continue
        report = report_incident_once(incident, send_fn=send_fn)
        results.append({"program_id": program_id, **report})
    return {
        "ok": True,
        "auto_retry": 0,
        "customer_send": 0,
        "results": results,
    }
