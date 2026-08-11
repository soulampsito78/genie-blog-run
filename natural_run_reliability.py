"""Weekend reliability canary + weekday pre-natural preflight.

Hard invariants:
- execution_class in {reliability_canary, preflight_canary}
- never satisfies natural_scheduled
- never customer send / owner-review SMTP
- never paid image API
- never auto-recovery
- never creates natural-run incidents
"""
from __future__ import annotations

import json
import hashlib
import logging
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional
from zoneinfo import ZoneInfo

from keysuri_generation_prompt import PROGRAM_GLOBAL, PROGRAM_KOREA
from keysuri_visible_text_quality import validate_and_repair_keysuri_visible_text_quality
from today_genie_execution_identity import (
    EXECUTION_CLASS_PREFLIGHT_CANARY,
    EXECUTION_CLASS_RELIABILITY_CANARY,
    NON_NATURAL_PROBE_CLASSES,
)

logger = logging.getLogger(__name__)
KST = ZoneInfo("Asia/Seoul")

REPO_ROOT = Path(__file__).resolve().parent
RELIABILITY_PACK_DIR = REPO_ROOT / "ops" / "feeds" / "reliability_packs"
PREFLIGHT_PREFIX = "admin_preflight"
RELIABILITY_PREFIX = "admin_reliability"

PROGRAM_TODAY = "today_genie"

NATURAL_SLOTS = {
    PROGRAM_TODAY: "06:30",
    PROGRAM_GLOBAL: "12:30",
    PROGRAM_KOREA: "18:30",
}

FROZEN_PACKS = {
    PROGRAM_GLOBAL: RELIABILITY_PACK_DIR / "20260807_global_frozen_source_pack.json",
    PROGRAM_KOREA: RELIABILITY_PACK_DIR / "20260807_korea_frozen_source_pack.json",
}


def _now_kst_iso() -> str:
    return datetime.now(KST).isoformat(timespec="seconds")


def _artifact_bucket() -> str:
    return (
        os.getenv("GENIE_ADMIN_ARTIFACT_BUCKET")
        or os.getenv("GENIE_ARTIFACT_BUCKET")
        or ""
    ).strip()


def _uses_gcs() -> bool:
    return bool(_artifact_bucket())


def _local_dir(prefix: str) -> Path:
    base = Path(tempfile.gettempdir()) / "genie_blog_run" / prefix
    base.mkdir(parents=True, exist_ok=True)
    return base


def _keysuri_probe_output_dir(program_id: str, execution_class: str) -> Path:
    """Return an isolated path that still satisfies owner-review validation."""
    scope = (
        "preflight"
        if execution_class == EXECUTION_CLASS_PREFLIGHT_CANARY
        else "reliability"
    )
    path = REPO_ROOT / "output" / "keysuri_preview" / scope / program_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def _save_json(prefix: str, name: str, payload: Mapping[str, Any]) -> str:
    body = json.dumps(dict(payload), ensure_ascii=False, indent=2) + "\n"
    if _uses_gcs():
        from google.cloud import storage  # type: ignore

        client = storage.Client()
        bucket = client.bucket(_artifact_bucket())
        blob = bucket.blob(f"{prefix}/{name}.json")
        blob.upload_from_string(body, content_type="application/json; charset=utf-8")
        return f"gs://{_artifact_bucket()}/{prefix}/{name}.json"
    path = _local_dir(prefix) / f"{name}.json"
    path.write_text(body, encoding="utf-8")
    return str(path)


def load_readiness(program_id: str, kst_date: Optional[str] = None) -> Optional[Dict[str, Any]]:
    date = kst_date or datetime.now(KST).strftime("%Y-%m-%d")
    name = f"{date}_{program_id}"
    if _uses_gcs():
        from google.cloud import storage  # type: ignore

        client = storage.Client()
        bucket = client.bucket(_artifact_bucket())
        blob = bucket.blob(f"{PREFLIGHT_PREFIX}/{name}.json")
        if not blob.exists():
            return None
        return json.loads(blob.download_as_text(encoding="utf-8"))
    path = _local_dir(PREFLIGHT_PREFIX) / f"{name}.json"
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _revision_meta() -> Dict[str, str]:
    return {
        "deployed_revision": (
            os.getenv("K_REVISION")
            or os.getenv("CLOUD_RUN_REVISION")
            or os.getenv("GENIE_REVISION")
            or ""
        ),
        "deployed_commit_sha": (
            os.getenv("COMMIT_SHA")
            or os.getenv("SOURCE_COMMIT")
            or os.getenv("GIT_COMMIT")
            or ""
        ),
    }


def _stable_fingerprint(value: Any) -> str:
    body = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def keysuri_input_fingerprint_fields(
    source_pack: Mapping[str, Any],
    generation_contract: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Bounded identity for comparing preflight input with a natural run."""
    pid = str(source_pack.get("program_id") or "")
    selection_key = "korea_top5_selection" if pid == PROGRAM_KOREA else "global_top5_selection"
    selection = source_pack.get(selection_key)
    if not isinstance(selection, Mapping):
        selection = {}
    selected_ids = [str(value) for value in selection.get("selected_source_ids") or [] if value]
    source_rows = source_pack.get("sources") if isinstance(source_pack.get("sources"), list) else []
    by_id = {
        str(row.get("source_id") or ""): row
        for row in source_rows
        if isinstance(row, Mapping)
    }
    selected_headlines = [
        str((by_id.get(source_id) or {}).get("title") or "") for source_id in selected_ids
    ]
    source_snapshot = [
        {
            "source_id": row.get("source_id"),
            "source_url": row.get("source_url"),
            "published_at": row.get("published_at"),
            "title": row.get("title"),
            "snippet": row.get("snippet"),
        }
        for row in source_rows
        if isinstance(row, Mapping)
    ]
    contract = dict(generation_contract or {})
    contract_identity = {
        "schema_fingerprint": contract.get("schema_fingerprint"),
        "prompt_template_fingerprint": contract.get("prompt_template_fingerprint"),
        "model_identifier": contract.get("model_identifier"),
    }
    return {
        "source_fetch_timestamp": source_pack.get("generated_at"),
        "source_count": len(source_rows),
        "selected_news_ids": selected_ids,
        "selected_headlines": selected_headlines,
        "source_snapshot_hash": _stable_fingerprint(source_snapshot),
        "selection_fingerprint": _stable_fingerprint(
            {"selected_news_ids": selected_ids, "selected_headlines": selected_headlines}
        ),
        "contract_fingerprint": _stable_fingerprint(contract_identity),
        "model": contract.get("model_identifier"),
    }


def compare_natural_input_to_preflight(
    natural_fields: Mapping[str, Any],
    readiness: Optional[Mapping[str, Any]],
) -> Dict[str, Any]:
    preflight = dict(readiness or {})
    current_selection = natural_fields.get("selection_fingerprint")
    preflight_selection = preflight.get("preflight_selection_fingerprint")
    current_source = natural_fields.get("source_snapshot_hash")
    preflight_source = preflight.get("preflight_source_snapshot_hash")
    comparable = bool(preflight_selection and current_selection)
    drift = bool(
        comparable
        and (
            current_selection != preflight_selection
            or (preflight_source and current_source != preflight_source)
        )
    )
    return {
        "preflight_comparison_available": comparable,
        "preflight_input_drift": drift,
        "preflight_input_diagnostic": "PREFLIGHT_INPUT_DRIFT" if drift else (
            "PREFLIGHT_INPUT_MATCH" if comparable else "PREFLIGHT_INPUT_NOT_COMPARABLE"
        ),
        "preflight_source_snapshot_hash": preflight_source,
        "preflight_selection_fingerprint": preflight_selection,
        "natural_source_snapshot_hash": current_source,
        "natural_selection_fingerprint": current_selection,
        "preflight_revision": preflight.get("preflight_revision") or preflight.get("deployed_revision"),
        "preflight_model": preflight.get("preflight_model"),
    }


def run_keysuri_reliability_generation(
    program_id: str,
    *,
    execution_class: str = EXECUTION_CLASS_RELIABILITY_CANARY,
    frozen_pack_path: Optional[Path] = None,
    send_owner_email: bool = False,
    send_fn=None,
) -> Dict[str, Any]:
    """No-send model generation: frozen for burn-in, live feeds for preflight."""
    if execution_class not in NON_NATURAL_PROBE_CLASSES:
        raise ValueError(f"forbidden_execution_class:{execution_class}")
    if send_owner_email:
        raise ValueError("reliability_canary_forbids_owner_email")

    from keysuri_live_source_smoke import run_keysuri_live_source_smoke

    pid = str(program_id or "").strip()
    live_preflight = (
        execution_class == EXECUTION_CLASS_PREFLIGHT_CANARY
        and frozen_pack_path is None
    )
    pack = None if live_preflight else (
        Path(frozen_pack_path) if frozen_pack_path else FROZEN_PACKS.get(pid)
    )
    if not live_preflight and (pack is None or not pack.is_file()):
        return {
            "ok": False,
            "program_id": pid,
            "execution_class": execution_class,
            "error": "frozen_pack_missing",
            "called_gemini": False,
            "called_image_api": 0,
            "smtp": 0,
            "customer": 0,
            "natural_slot_mutation": 0,
        }

    started = _now_kst_iso()
    output_prefix = PREFLIGHT_PREFIX if live_preflight else RELIABILITY_PREFIX
    probe_output_dir = _keysuri_probe_output_dir(pid, execution_class)
    normalized_pack_out = probe_output_dir / (
        f"{datetime.now(KST).strftime('%Y%m%d_%H%M%S')}_{pid}_normalized_source_pack.json"
    )
    generation_usage: Dict[str, Any] = {}
    smoke = run_keysuri_live_source_smoke(
        program_id=pid,
        use_gemini=True,
        send=False,
        frozen_source_pack_path=pack,
        trigger_source=execution_class,
        allow_network=live_preflight,
        out_dir=probe_output_dir,
        source_pack_out=normalized_pack_out,
        usage_sink=generation_usage,
    )

    source_pack: Dict[str, Any] = {}
    try:
        source_pack = json.loads(Path(smoke.source_pack_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        source_pack = {}
    generation_contract = (
        dict(smoke.generation_contract)
        if isinstance(smoke.generation_contract, dict)
        else {}
    )
    # The Gemini caller writes the resolved model after a real response. Do not
    # substitute the configured contract value for actual invocation evidence.
    actual_model = str(generation_usage.get("model") or "").strip()
    if actual_model:
        generation_contract["model_identifier"] = actual_model
    input_fields = keysuri_input_fingerprint_fields(
        source_pack,
        generation_contract,
    ) if source_pack else {}
    input_fields["model"] = actual_model or None

    briefing = smoke.generated_briefing if isinstance(smoke.generated_briefing, dict) else {}
    repaired = briefing
    vt_fields: Dict[str, Any] = {}
    if briefing:
        repaired, vt_fields = validate_and_repair_keysuri_visible_text_quality(
            briefing, root_path="generated_briefing"
        )

    validation_pass = bool(
        smoke.ok
        and smoke.called_gemini
        and actual_model
        and smoke.parse_status == "parsed_valid"
        and vt_fields.get("visible_text_quality_status", "pass") == "pass"
        and not vt_fields.get("visible_text_ellipsis_blocked")
    )

    issue_codes = list(smoke.validation_issues or [])
    if smoke.error:
        issue_codes.append(str(smoke.error)[:160])
    if smoke.called_gemini and not actual_model:
        issue_codes.append("keysuri_preflight_model_identity_missing")
    for code in vt_fields.get("visible_text_quality_issue_codes") or []:
        if code not in issue_codes:
            issue_codes.append(code)

    result = {
        "ok": bool(validation_pass),
        "program_id": pid,
        "execution_class": execution_class,
        "reliability_canary": execution_class == EXECUTION_CLASS_RELIABILITY_CANARY,
        "preflight_canary": execution_class == EXECUTION_CLASS_PREFLIGHT_CANARY,
        "started_at": started,
        "finished_at": _now_kst_iso(),
        "input_mode": "live_current_feed" if live_preflight else "frozen_reliability_pack",
        "frozen_pack_path": str(pack) if pack is not None else None,
        "called_gemini": bool(smoke.called_gemini),
        "called_image_api": 0,
        "smtp": 0,
        "customer": 0,
        "natural_slot_mutation": 0,
        "incident_created": 0,
        "parse_status": smoke.parse_status,
        "smoke_ok": bool(smoke.ok),
        "validation_pass": bool(validation_pass),
        "issue_codes": issue_codes,
        "visible_text_quality_status": vt_fields.get("visible_text_quality_status"),
        "visible_text_quality_samples": (vt_fields.get("visible_text_quality_samples") or [])[:4],
        "generation_diagnostics": dict(smoke.generation_diagnostics or {}),
        "generation_attempt_count": getattr(smoke, "generation_attempt_count", None),
        "error": None if validation_pass else (smoke.error or "validation_failed"),
        **input_fields,
        **_revision_meta(),
    }
    stamp = datetime.now(KST).strftime("%Y%m%d_%H%M%S")
    result["artifact_uri"] = _save_json(
        RELIABILITY_PREFIX if execution_class == EXECUTION_CLASS_RELIABILITY_CANARY else PREFLIGHT_PREFIX,
        f"{stamp}_{pid}_{execution_class}",
        result,
    )
    return result


def run_today_reliability_generation(
    *,
    execution_class: str = EXECUTION_CLASS_RELIABILITY_CANARY,
    genie_api_url: Optional[str] = None,
    prefer_inprocess: bool = True,
) -> Dict[str, Any]:
    """Live Today text generation only — no image / SMTP / natural completion.

    Default path uses in-process FastAPI TestClient against local HEAD so weekend
    burn-in / preflight patches are exercised before deploy. Optional remote
    GENIE_API_URL remains available for deployed-revision proofs.
    """
    if execution_class not in NON_NATURAL_PROBE_CLASSES:
        raise ValueError(f"forbidden_execution_class:{execution_class}")

    started = _now_kst_iso()
    response_status = None
    validation_result = ""
    issue_codes: List[str] = []
    called_gemini = False
    api_url = "inprocess"
    error = None

    if prefer_inprocess and not genie_api_url:
        from fastapi.testclient import TestClient
        from main import app

        client = TestClient(app)
        resp = client.post("/", json={"type": "today_genie"})
        response_status = resp.status_code
        payload: Dict[str, Any] = {}
        try:
            payload = resp.json()
        except Exception:
            payload = {}
        called_gemini = True
        if isinstance(payload, dict):
            validation_result = str(payload.get("validation_result") or "")
            detail = payload.get("detail") if isinstance(payload.get("detail"), dict) else {}
            if not validation_result and detail:
                validation_result = str(
                    detail.get("runtime_validation_check", {}).get("validation_result")
                    or detail.get("reason")
                    or ""
                )
                if validation_result == "validation_block":
                    validation_result = "block"
            for item in payload.get("validation_issues") or detail.get("issues") or []:
                if isinstance(item, dict) and item.get("code"):
                    issue_codes.append(str(item["code"]))
            for code in detail.get("issue_codes") or []:
                if str(code) not in issue_codes:
                    issue_codes.append(str(code))
            nested = (
                detail.get("runtime_validation_check")
                if isinstance(detail.get("runtime_validation_check"), dict)
                else {}
            )
            if not validation_result and nested.get("validation_result"):
                validation_result = str(nested.get("validation_result"))
            for code in nested.get("issue_codes") or []:
                if str(code) not in issue_codes:
                    issue_codes.append(str(code))
        ok = response_status == 200 and validation_result == "pass"
        if not ok:
            error = "validation_blocked"
    else:
        import orchestrator as orch

        default_prod = "https://genie-blog-run-1055014091206.asia-northeast3.run.app"
        configured = (genie_api_url or os.getenv("GENIE_API_URL") or "").strip()
        if not configured or "localhost" in configured or "127.0.0.1" in configured:
            orch.GENIE_API_URL = default_prod
        else:
            orch.GENIE_API_URL = configured
        api_url = orch.GENIE_API_URL
        result_job = orch.run_genie_job("today_genie")
        payload = result_job.response_data if isinstance(result_job.response_data, dict) else {}
        response_status = result_job.response_status
        validation_result = str(payload.get("validation_result") or "")
        called_gemini = response_status == 200
        for item in payload.get("validation_issues") or []:
            if isinstance(item, dict) and item.get("code"):
                issue_codes.append(str(item["code"]))
            elif isinstance(item, str):
                issue_codes.append(item)
        ok = response_status == 200 and validation_result == "pass"
        error = None if ok else (result_job.reason_summary or "validation_blocked")
        if response_status is None:
            issue_codes.append("genie_api_unreachable")

    out = {
        "ok": bool(ok),
        "program_id": PROGRAM_TODAY,
        "execution_class": execution_class,
        "reliability_canary": execution_class == EXECUTION_CLASS_RELIABILITY_CANARY,
        "preflight_canary": execution_class == EXECUTION_CLASS_PREFLIGHT_CANARY,
        "started_at": started,
        "finished_at": _now_kst_iso(),
        "called_gemini": bool(called_gemini),
        "called_image_api": 0,
        "smtp": 0,
        "customer": 0,
        "natural_slot_mutation": 0,
        "incident_created": 0,
        "validation_result": validation_result,
        "validation_pass": bool(ok),
        "response_status": response_status,
        "issue_codes": issue_codes,
        "genie_api_url": api_url,
        "error": error,
        **_revision_meta(),
    }
    stamp = datetime.now(KST).strftime("%Y%m%d_%H%M%S")
    out["artifact_uri"] = _save_json(
        RELIABILITY_PREFIX if execution_class == EXECUTION_CLASS_RELIABILITY_CANARY else PREFLIGHT_PREFIX,
        f"{stamp}_{PROGRAM_TODAY}_{execution_class}",
        out,
    )
    return out


def run_program_canary(program_id: str, *, execution_class: str) -> Dict[str, Any]:
    pid = str(program_id or "").strip()
    if pid == PROGRAM_TODAY:
        return run_today_reliability_generation(execution_class=execution_class)
    if pid in {PROGRAM_GLOBAL, PROGRAM_KOREA}:
        return run_keysuri_reliability_generation(pid, execution_class=execution_class)
    return {"ok": False, "error": "unknown_program", "program_id": pid}


def build_preflight_failure_email_html(result: Mapping[str, Any]) -> str:
    program = str(result.get("program_id") or "")
    slot = NATURAL_SLOTS.get(program, "?")
    sample = ""
    samples = result.get("visible_text_quality_samples") or []
    if samples and isinstance(samples[0], dict):
        sample = str(samples[0].get("sample") or samples[0].get("repaired_sample") or "")[:160]
    codes = ", ".join(str(c) for c in (result.get("issue_codes") or [])[:8]) or "(없음)"
    sample_disp = sample or "(없음)"
    finished = result.get("finished_at")
    rev = result.get("deployed_revision") or "(unknown)"
    sha = result.get("deployed_commit_sha") or "(unknown)"
    return (
        "<!DOCTYPE html>\n"
        '<html lang="ko"><head><meta charset="utf-8"><title>GENIE 사전점검 실패</title></head>\n'
        '<body style="font-family:sans-serif;line-height:1.55;color:#111;max-width:720px;">\n'
        "<h1>[GENIE 사전점검 실패]</h1>\n"
        "<p><strong>아직 정규 자연실행은 시작되지 않았습니다.</strong></p>\n"
        f"<p>대상: {program} {slot} KST<br>\n"
        f"실패 시각: {finished}<br>\n"
        f"revision: {rev}<br>\n"
        f"commit: {sha}</p>\n"
        f"<p>issue_codes: <code>{codes}</code></p>\n"
        f"<p>bounded sample: {sample_disp}</p>\n"
        "<p>권고: 자연 Scheduler는 그대로 유지됩니다. 사전점검 실패만으로 정규 실행을 취소하지 않습니다.\n"
        "정규 실행이 실패하면 기존 Watchdog이 장애를 보고합니다.</p>\n"
        "</body></html>\n"
    )


def run_natural_preflight(
    program_id: str,
    *,
    scheduled_service_date: Optional[str] = None,
    scheduled_slot: Optional[str] = None,
    send_fn=None,
    alert_on_fail: bool = True,
) -> Dict[str, Any]:
    """Weekday pre-natural preflight. PASS silent; FAIL may email early warning."""
    pid = str(program_id or "").strip()
    slot = scheduled_slot or NATURAL_SLOTS.get(pid, "")
    date = scheduled_service_date or datetime.now(KST).strftime("%Y-%m-%d")
    result = run_program_canary(pid, execution_class=EXECUTION_CLASS_PREFLIGHT_CANARY)
    if (
        pid in {PROGRAM_GLOBAL, PROGRAM_KOREA}
        and result.get("called_gemini")
        and not str(result.get("model") or "").strip()
    ):
        result = dict(result)
        result["ok"] = False
        issue_codes = list(result.get("issue_codes") or [])
        if "keysuri_preflight_model_identity_missing" not in issue_codes:
            issue_codes.append("keysuri_preflight_model_identity_missing")
        result["issue_codes"] = issue_codes
        result["error"] = result.get("error") or "model_identity_missing"
    readiness = {
        "program_id": pid,
        "kst_date": date,
        "scheduled_slot": slot,
        "status": "PRECHECK_PASS" if result.get("ok") else "PRECHECK_FAIL",
        "checked_at": result.get("finished_at") or _now_kst_iso(),
        "validation_pass": bool(result.get("ok")),
        "issue_codes": list(result.get("issue_codes") or []),
        "deployed_revision": result.get("deployed_revision"),
        "deployed_commit_sha": result.get("deployed_commit_sha"),
        "model_called": bool(result.get("called_gemini")),
        "called_image_api": 0,
        "smtp": 0,
        "customer": 0,
        "natural_slot_mutation": 0,
        "incident_created": 0,
        "canary_artifact_uri": result.get("artifact_uri"),
        "error": result.get("error"),
    }
    readiness["artifact_uri"] = _save_json(PREFLIGHT_PREFIX, f"{date}_{pid}", readiness)

    alert_sent = False
    if alert_on_fail and not result.get("ok"):
        html = build_preflight_failure_email_html({**result, **readiness})
        subject = f"[GENIE 사전점검 실패] {pid} {slot} 자연실행 사전점검 실패"
        try:
            if send_fn is not None:
                alert_sent = bool(send_fn(subject=subject, html_body=html))
            else:
                from email_sender import send_genie_email

                # Owner-only; never customer. Best-effort.
                alert_sent = bool(
                    send_genie_email(
                        subject=subject,
                        html_body=html,
                        to_addrs_override=None,
                    )
                )
        except Exception:
            logger.exception("preflight alert send failed program=%s", pid)
            alert_sent = False
    readiness["alert_sent"] = alert_sent
    readiness["alert_on_fail"] = bool(alert_on_fail)
    readiness["preflight_source_snapshot_hash"] = result.get("source_snapshot_hash")
    readiness["preflight_selection_fingerprint"] = result.get("selection_fingerprint")
    readiness["preflight_contract_fingerprint"] = result.get("contract_fingerprint")
    readiness["preflight_revision"] = result.get("deployed_revision")
    readiness["preflight_model"] = result.get("model")
    readiness["selected_news_ids"] = list(result.get("selected_news_ids") or [])
    readiness["selected_headlines"] = list(result.get("selected_headlines") or [])
    readiness["source_fetch_timestamp"] = result.get("source_fetch_timestamp")
    readiness["source_count"] = result.get("source_count")
    readiness["input_mode"] = result.get("input_mode")
    readiness["canary_result"] = {
        k: result.get(k)
        for k in (
            "ok",
            "parse_status",
            "validation_pass",
            "issue_codes",
            "generation_attempt_count",
            "error",
        )
    }
    # Persist the alert outcome and representative-input identity, not only the
    # preliminary status written before alert dispatch.
    readiness["artifact_uri"] = _save_json(PREFLIGHT_PREFIX, f"{date}_{pid}", readiness)
    return readiness


def burn_in_program(
    program_id: str,
    *,
    target_consecutive: int = 10,
    max_attempts: int = 40,
) -> Dict[str, Any]:
    """Run until target consecutive PASS or attempts exhausted. Resets streak on fail."""
    streak = 0
    attempts: List[Dict[str, Any]] = []
    terminal_failures = 0
    while streak < target_consecutive and len(attempts) < max_attempts:
        one = run_program_canary(program_id, execution_class=EXECUTION_CLASS_RELIABILITY_CANARY)
        attempts.append(
            {
                "attempt": len(attempts) + 1,
                "ok": bool(one.get("ok")),
                "issue_codes": list(one.get("issue_codes") or []),
                "error": one.get("error"),
                "artifact_uri": one.get("artifact_uri"),
                "finished_at": one.get("finished_at"),
            }
        )
        if one.get("ok"):
            streak += 1
        else:
            terminal_failures += 1
            streak = 0
            # Persist sanitized failure for fixture harvesting
            _save_json(
                RELIABILITY_PREFIX,
                f"burnin_fail_{program_id}_{len(attempts)}_{datetime.now(KST).strftime('%H%M%S')}",
                {
                    k: one.get(k)
                    for k in one.keys()
                    if k
                    not in {
                        "generated_briefing",
                        "raw_text",
                        "prompt",
                    }
                },
            )
    return {
        "program_id": program_id,
        "target_consecutive": target_consecutive,
        "consecutive_final_pass": streak,
        "attempts_total": len(attempts),
        "terminal_failures": terminal_failures,
        "passed": streak >= target_consecutive,
        "attempts": attempts,
        "called_image_api_total": 0,
        "smtp_total": 0,
        "customer_total": 0,
    }
