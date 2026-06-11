"""Kee-Suri Global/Korea service-level full run with generated images."""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from admin_store import artifact_email_path, artifact_json_path, generate_run_id, save_run_artifact
from admin_urls import build_owner_review_admin_url
from email_sender import send_genie_email
from keysuri_contract_preview_fixture import build_contract_preview_fixture_from_generated
from keysuri_contract_preview_renderer import (
    IMAGE_MODE_PREVIEW,
    prepare_contract_preview_fixture,
    render_keysuri_contract_preview_html,
)
from keysuri_briefing_content_enricher import enrich_generated_briefing_content
from keysuri_generation_prompt import parse_keysuri_generated_response
from keysuri_live_source_smoke import (
    PROGRAM_GLOBAL,
    PROGRAM_KOREA,
    LiveSourceSmokeResult,
    run_keysuri_live_source_smoke,
)
from keysuri_prompt_input import build_keysuri_prompt_input
from keysuri_renderer import PROGRAM_DISPLAY
from service_full_run_contract import (
    ERROR_IMAGE_GENERATION_FAILED,
    IMAGE_GEN_GENERATED,
    IMAGE_SOURCE_GENERATED,
    SERVICE_FULL_RUN_TRIGGER,
    ServiceImageOutcome,
    build_service_artifact_fields,
)
from service_image_api import invoke_vertex_image_generation

logger = logging.getLogger(__name__)

_REPO = Path(__file__).resolve().parent
_KEYSURI_PROGRAMS = frozenset({PROGRAM_GLOBAL, PROGRAM_KOREA})

_PROGRAM_EMAIL_SUBJECT = {
    PROGRAM_GLOBAL: "[운영자 검토] Kee-Suri Global Tech",
    PROGRAM_KOREA: "[운영자 검토] Kee-Suri Korea Tech",
}


def _validation_result_from_smoke(smoke: LiveSourceSmokeResult) -> str:
    if smoke.parse_status == "parsed_valid" and smoke.called_gemini and smoke.ok:
        return "pass"
    status = str(smoke.preview_overall_status or "").strip()
    if status in ("PASS_OWNER_REVIEW_READY", "PASS"):
        return "pass"
    if smoke.ok and smoke.validation_status in ("PASS", "pass"):
        return "pass"
    return "block"


def _build_service_keysuri_image_prompt(program_id: str) -> str:
    label = "Global Tech" if program_id == PROGRAM_GLOBAL else "Korea Tech"
    return (
        f"Kee-Suri private tech assistant hero image for {label} owner-review briefing. "
        "Premium Korean woman in her late 20s, same recognizable face identity, refined editorial portrait, "
        "trustworthy private tech assistant tone, not a public news anchor, not a weathercaster, "
        "smart business-casual wardrobe, natural Seoul morning light, high detail commercial realism, "
        "no text, no logo, no watermark, no split screen.\n\n"
        "NEGATIVE:\nnot a public news anchor\nnot a weathercaster\nno readable text overlay\nno collage\nno split screen"
    )


def _generate_keysuri_service_image(
    program_id: str,
    *,
    generate_fn: Optional[Callable[..., Path]] = None,
) -> ServiceImageOutcome:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from keysuri_image_api_canary_client import DEFAULT_LOCK_PATH, _gate_prompt_source
    from keysuri_image_provider_contract import OUTPUT_IMAGES_DIR, resolve_keysuri_reference_asset_path

    ref_path, ref_issues = resolve_keysuri_reference_asset_path(None)
    repo = _REPO
    ref_abs = repo / ref_path
    if ref_issues or not ref_abs.is_file():
        return ServiceImageOutcome(
            error_code=ERROR_IMAGE_GENERATION_FAILED,
            error_message=f"missing reference asset: {ref_path}",
        )

    prompt_source, gate_issues, gate_ready = _gate_prompt_source(
        DEFAULT_LOCK_PATH,
        program_id,
        manual_approval_for_gate=True,
    )
    if gate_ready and prompt_source:
        positive = str(prompt_source.get("positive_prompt") or "").strip()
        negative = str(prompt_source.get("negative_prompt") or "").strip()
        full_prompt = f"{positive}\n\nNEGATIVE:\n{negative}".strip()
    else:
        full_prompt = _build_service_keysuri_image_prompt(program_id)

    slug = "global" if program_id == PROGRAM_GLOBAL else "korea"
    stamp = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y%m%d_%H%M%S")
    out = repo / OUTPUT_IMAGES_DIR / f"keysuri_{slug}_service_{stamp}.jpg"
    return invoke_vertex_image_generation(
        prompt=full_prompt,
        output_path=out,
        reference_image_path=ref_abs,
        generate_fn=generate_fn,
    )


def _reload_generated_briefing(
    smoke: LiveSourceSmokeResult,
    program_id: str,
    prompt_input: dict,
) -> Optional[dict]:
    raw_path = str(smoke.raw_response_path or "").strip()
    if not raw_path:
        return None
    raw = Path(raw_path).read_text(encoding="utf-8")
    parsed = parse_keysuri_generated_response(raw, program_id, prompt_input)
    if str(parsed.get("parse_status") or "") != "parsed_valid":
        return None
    briefing = parsed.get("generated_briefing")
    if not isinstance(briefing, dict):
        return None
    return enrich_generated_briefing_content(briefing, program_id, prompt_input)


def _render_service_html(
    program_id: str,
    *,
    prompt_input: dict,
    generated_briefing: dict,
    generated_image_path: Path,
    run_id: str,
) -> tuple[str, str]:
    out_dir = _REPO / "output" / "admin_runs" / "keysuri_service"
    out_dir.mkdir(parents=True, exist_ok=True)
    html_path = out_dir / f"{run_id}.html"
    contract_fixture = build_contract_preview_fixture_from_generated(
        program_id=program_id,
        prompt_input=prompt_input,
        generated_briefing=generated_briefing,
        source_pack=prompt_input.get("source_pack") or {},
        top_shot_image_path=generated_image_path,
    )
    contract_fixture["fixture_mode"] = "service_full_run_generated"
    prepare_contract_preview_fixture(
        contract_fixture,
        repo_root=_REPO,
        image_mode=IMAGE_MODE_PREVIEW,
    )
    html = render_keysuri_contract_preview_html(
        contract_fixture,
        repo_root=_REPO,
        image_mode=IMAGE_MODE_PREVIEW,
        auto_prepare=False,
    )
    html_path.write_text(html, encoding="utf-8")
    try:
        rel = html_path.resolve().relative_to(_REPO.resolve()).as_posix()
    except ValueError:
        rel = str(html_path.resolve())
    return html, rel


def _owner_review_email_html(html: str, *, program_id: str, run_id: str) -> str:
    label = PROGRAM_DISPLAY.get(program_id, program_id)
    admin_url = build_owner_review_admin_url(run_id) or ""
    admin_block = ""
    if admin_url:
        admin_block = (
            f'<div style="margin:24px 0;text-align:center;">'
            f'<a href="{admin_url}" style="display:inline-block;padding:12px 20px;background:#0f172a;color:#fff;text-decoration:none;border-radius:8px;font-weight:700;">'
            f"운영자 검수 화면 열기</a>"
            f'<p style="margin:12px 0 0;font-size:12px;word-break:break-all;"><a href="{admin_url}">{admin_url}</a></p>'
            f'<p style="font-size:11px;color:#64748b;">run_id: {run_id}</p></div>'
        )
    header = (
        f'<div style="margin:0 0 16px;padding:12px 16px;background:#f1f5f9;border:1px solid #cbd5e1;border-radius:8px;">'
        f'<p style="margin:0;font-size:13px;"><strong>서비스 full-run</strong> · {label} · run_id: {run_id}</p>'
        f'<p style="margin:6px 0 0;font-size:12px;color:#475569;">image_source=generated · service_full_run=true</p></div>'
    )
    return f"<!DOCTYPE html><html><head><meta charset=\"utf-8\"><title>{label} owner review</title></head><body>{header}{html}{admin_block}</body></html>"


def run_keysuri_service_full_run(
    program_id: str,
    *,
    trigger_source: str = SERVICE_FULL_RUN_TRIGGER,
    send_owner_email: bool = True,
    dry_run: bool = False,
    smoke_runner=None,
    image_canary_runner=None,
    send_fn: Optional[Callable[..., bool]] = None,
) -> Dict[str, Any]:
    """Service-level Kee-Suri full run for keysuri_global_tech or keysuri_korea_tech."""
    pid = str(program_id or "").strip()
    if pid not in _KEYSURI_PROGRAMS:
        return {"ok": False, "error": "unknown_program_id", "program_id": pid}

    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "program_id": pid,
            "service_full_run": True,
            "would_run": True,
            "trigger_source": trigger_source,
        }

    run_id = generate_run_id(pid)
    runner = smoke_runner or run_keysuri_live_source_smoke
    smoke: LiveSourceSmokeResult = runner(
        program_id=pid,
        use_gemini=True,
        contract_preview=False,
        send=False,
    )
    validation_result = _validation_result_from_smoke(smoke)
    if smoke.called_gemini and smoke.parse_status == "parsed_valid" and smoke.ok:
        validation_result = "pass"
    issue_codes: List[str] = list(smoke.validation_issues or [])
    if smoke.error:
        issue_codes.append(str(smoke.error)[:120])

    if not smoke.called_gemini or validation_result != "pass" or not smoke.ok:
        meta = build_service_artifact_fields(
            run_id=run_id,
            mode=pid,
            program_id=pid,
            trigger_source=trigger_source,
            validation_result=validation_result,
            issue_codes=issue_codes,
            called_gemini=bool(smoke.called_gemini),
            html_path=str(smoke.html_path or ""),
            email_sent=False,
            error_code="validation_blocked" if validation_result != "pass" else "gemini_or_smoke_failed",
        )
        save_run_artifact(meta, email_html="")
        return {
            "ok": False,
            "run_id": run_id,
            "program_id": pid,
            "service_full_run": True,
            "validation_result": validation_result,
            "called_gemini": bool(smoke.called_gemini),
            "called_image_api": False,
            "email_sent": False,
            "error": meta.get("error_code"),
            "issue_codes": issue_codes,
        }

    canary_fn = image_canary_runner or _generate_keysuri_service_image
    image_outcome = canary_fn(pid)
    if not image_outcome.ok:
        meta = build_service_artifact_fields(
            run_id=run_id,
            mode=pid,
            program_id=pid,
            trigger_source=trigger_source,
            validation_result=validation_result,
            issue_codes=issue_codes + [image_outcome.error_code or ERROR_IMAGE_GENERATION_FAILED],
            called_gemini=True,
            image_outcome=image_outcome,
            html_path=str(smoke.html_path or ""),
            email_sent=False,
            error_code=image_outcome.error_code or ERROR_IMAGE_GENERATION_FAILED,
        )
        save_run_artifact(meta, email_html="")
        return {
            "ok": False,
            "run_id": run_id,
            "program_id": pid,
            "service_full_run": True,
            "validation_result": validation_result,
            "called_gemini": True,
            "called_image_api": image_outcome.called_image_api,
            "image_generation_status": image_outcome.image_generation_status,
            "image_source": image_outcome.image_source,
            "generated_image_path": image_outcome.generated_image_path,
            "email_sent": False,
            "error": image_outcome.error_code or ERROR_IMAGE_GENERATION_FAILED,
        }

    source_pack = json.loads(Path(smoke.source_pack_path).read_text(encoding="utf-8"))
    prompt_input = build_keysuri_prompt_input(pid, source_pack)
    prompt_input["source_pack"] = source_pack
    generated_briefing = _reload_generated_briefing(smoke, pid, prompt_input)
    if not generated_briefing:
        meta = build_service_artifact_fields(
            run_id=run_id,
            mode=pid,
            program_id=pid,
            trigger_source=trigger_source,
            validation_result="block",
            issue_codes=issue_codes + ["generated_briefing_reload_failed"],
            called_gemini=True,
            image_outcome=image_outcome,
            email_sent=False,
            error_code="generated_briefing_reload_failed",
        )
        save_run_artifact(meta, email_html="")
        return {"ok": False, "run_id": run_id, "program_id": pid, "service_full_run": True, "email_sent": False, "error": "generated_briefing_reload_failed"}

    gen_image_abs = _REPO / str(image_outcome.generated_image_path or "")
    html_body, html_rel = _render_service_html(
        pid,
        prompt_input=prompt_input,
        generated_briefing=generated_briefing,
        generated_image_path=gen_image_abs,
        run_id=run_id,
    )
    email_html = _owner_review_email_html(html_body, program_id=pid, run_id=run_id)

    email_sent = False
    smtp_attempted = False
    if send_owner_email:
        if os.getenv("GENIE_OWNER_REVIEW_SEND", "").strip() not in ("1", "true", "yes"):
            issue_codes.append("owner_review_send_gate_off")
        else:
            subject = _PROGRAM_EMAIL_SUBJECT.get(pid, f"[운영자 검토] {PROGRAM_DISPLAY.get(pid, pid)}")
            smtp_attempted = True
            sender = send_fn or send_genie_email
            email_sent = bool(sender(email_html, subject))

    meta = build_service_artifact_fields(
        run_id=run_id,
        mode=pid,
        program_id=pid,
        trigger_source=trigger_source,
        validation_result=validation_result,
        issue_codes=issue_codes,
        called_gemini=True,
        image_outcome=image_outcome,
        html_path=html_rel,
        owner_review_html_path=str(artifact_email_path(run_id)),
        smtp_attempted=smtp_attempted,
        email_sent=email_sent,
        workflow_status=smoke.preview_overall_status,
    )
    meta["artifact_status"] = "emailed" if email_sent else "stored"
    save_run_artifact(meta, email_html=email_html)

    ok = image_outcome.ok and (not send_owner_email or email_sent)
    return {
        "ok": ok,
        "run_id": run_id,
        "program_id": pid,
        "service_full_run": True,
        "trigger_source": trigger_source,
        "validation_result": validation_result,
        "called_gemini": True,
        "called_image_api": image_outcome.called_image_api,
        "image_generation_status": image_outcome.image_generation_status,
        "image_source": image_outcome.image_source,
        "generated_image_path": image_outcome.generated_image_path,
        "html_path": html_rel,
        "owner_review_html_path": meta.get("owner_review_html_path"),
        "artifact_status": meta.get("artifact_status"),
        "smtp_attempted": smtp_attempted,
        "email_sent": email_sent,
    }
