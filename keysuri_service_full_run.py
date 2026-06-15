"""Kee-Suri Global/Korea service-level full run with generated images."""
from __future__ import annotations

import json
import logging
import os
import hashlib
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from admin_store import admin_artifact_bucket_name, artifact_email_path, artifact_json_path, generate_run_id, save_run_artifact
from admin_urls import build_owner_review_admin_url
from email_sender import send_genie_email
from keysuri_approved_image_assets import KOREA_BOTTOM_ROLE, list_approved_assets
from keysuri_image_overlay import apply_keysuri_mirai_on_watermark
from keysuri_contract_preview_fixture import build_contract_preview_fixture_from_generated
from keysuri_contract_preview_renderer import (
    IMAGE_MODE_EMAIL,
    IMAGE_MODE_PREVIEW,
    build_keysuri_global_gmail_owner_email_html,
    build_keysuri_korea_gmail_owner_email_html,
    build_keysuri_owner_review_email_html,
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

# MIME Content-ID token (no angle brackets); HTML uses cid:{token}.
KEYSURI_GLOBAL_SERVICE_EMAIL_CID_PREFIX = "keysuri_topshot_global"
KEYSURI_KOREA_SERVICE_EMAIL_CID_PREFIX = "keysuri_topshot_korea"
KEYSURI_KOREA_BOTTOM_SERVICE_EMAIL_CID_PREFIX = "keysuri_bottomshot_korea"
KEYSURI_KOREA_BOTTOM_ASSET_ID = "keysuri_korea_bottom_20260605_105936"
KEYSURI_KOREA_BOTTOM_GCS_OBJECT = (
    "assets/keysuri/korea_bottom/"
    "keysuri_global_canary_20260605_105936_mirai_on_watermarked.jpg"
)
KEYSURI_KOREA_BOTTOM_WATERMARKED_SHA256 = (
    "c6209f406717aa68ef8be70fbfd9dbc30b882e9fae800633d570111bb1b3faf9"
)
KEYSURI_KOREA_BOTTOM_VARIATION_ENV = "KEYSURI_KOREA_BOTTOM_VARIATION_ENABLED"
KEYSURI_KOREA_BOTTOM_REFERENCE_DIRECTION = "offduty_02C"


def _kst_date_from_run_id(run_id: str) -> str:
    rid = str(run_id or "").strip()
    if len(rid) >= 8 and rid[:8].isdigit():
        return rid[:8]
    from datetime import datetime
    from zoneinfo import ZoneInfo

    return datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y%m%d")


def keysuri_global_service_email_cid_token(run_id: str) -> str:
    """Content-ID token for Global service_full_run owner-review email hero image."""
    stamp = _kst_date_from_run_id(run_id)
    return f"{KEYSURI_GLOBAL_SERVICE_EMAIL_CID_PREFIX}_{stamp}"


def keysuri_global_service_email_cid_src(run_id: str) -> str:
    return f"cid:{keysuri_global_service_email_cid_token(run_id)}"


def keysuri_korea_service_email_cid_token(run_id: str) -> str:
    """Content-ID token for Korea service_full_run owner-review email hero image."""
    stamp = _kst_date_from_run_id(run_id)
    return f"{KEYSURI_KOREA_SERVICE_EMAIL_CID_PREFIX}_{stamp}"


def keysuri_korea_service_email_cid_src(run_id: str) -> str:
    return f"cid:{keysuri_korea_service_email_cid_token(run_id)}"


def keysuri_korea_bottom_service_email_cid_token(run_id: str) -> str:
    """Content-ID token for Korea service_full_run bottom-shot image."""
    stamp = _kst_date_from_run_id(run_id)
    return f"{KEYSURI_KOREA_BOTTOM_SERVICE_EMAIL_CID_PREFIX}_{stamp}"


def keysuri_korea_bottom_service_email_cid_src(run_id: str) -> str:
    return f"cid:{keysuri_korea_bottom_service_email_cid_token(run_id)}"


def korea_bottom_variation_enabled() -> bool:
    """Future Korea bottom-shot variation gate; default is fixed 105936 fallback."""
    return os.getenv(KEYSURI_KOREA_BOTTOM_VARIATION_ENV, "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def inline_jpeg_parts_for_global_service_email(
    generated_image_path: Path,
    run_id: str,
) -> List[Tuple[str, str, str]]:
    """Single hero inline JPEG for Global service_full_run SMTP (Gmail-safe CID)."""
    cid_token = keysuri_global_service_email_cid_token(run_id)
    fname = generated_image_path.name if generated_image_path.name else "keysuri_global_service.jpg"
    return [(str(generated_image_path.resolve()), cid_token, fname)]


def inline_jpeg_parts_for_korea_service_email(
    generated_image_path: Path,
    run_id: str,
    *,
    bottom_image_path: Optional[Path] = None,
) -> List[Tuple[str, str, str]]:
    """Hero plus optional Korea-only bottom-shot inline JPEGs for Gmail-safe SMTP."""
    cid_token = keysuri_korea_service_email_cid_token(run_id)
    fname = generated_image_path.name if generated_image_path.name else "keysuri_korea_service.jpg"
    parts = [(str(generated_image_path.resolve()), cid_token, fname)]
    if bottom_image_path is not None:
        bottom_cid = keysuri_korea_bottom_service_email_cid_token(run_id)
        bottom_name = bottom_image_path.name if bottom_image_path.name else "keysuri_korea_bottom_105936.jpg"
        parts.append((str(bottom_image_path.resolve()), bottom_cid, bottom_name))
    return parts


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _repo_rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(_REPO.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def _watermarked_top_shot_path(source_path: Path) -> Path:
    source = Path(source_path)
    if not source.is_file():
        raise FileNotFoundError(f"Kee-Suri generated top-shot missing: {source}")
    if source.stem.endswith("_mirai_on_watermarked"):
        return source.resolve()
    target = source.with_name(f"{source.stem}_mirai_on_watermarked{source.suffix}")
    return apply_keysuri_mirai_on_watermark(source, target)


def _korea_bottom_registry_asset() -> Any:
    for asset in list_approved_assets(_REPO):
        if asset.asset_id == KEYSURI_KOREA_BOTTOM_ASSET_ID:
            return asset
    return None


def _validate_korea_bottom_asset_record(asset: Any) -> Optional[str]:
    if asset is None:
        return "korea_bottom_asset_registry_missing"
    if asset.program != PROGRAM_KOREA:
        return "korea_bottom_asset_program_mismatch"
    if asset.role != KOREA_BOTTOM_ROLE or asset.image_role != "bottom_shot":
        return "korea_bottom_asset_role_mismatch"
    if asset.status != "approved_direction_locked":
        return "korea_bottom_asset_status_not_direction_locked"
    if "korea_bottom_preview" not in asset.approved_for:
        return "korea_bottom_asset_not_approved_for_preview"
    if asset.watermarked_sha256 != KEYSURI_KOREA_BOTTOM_WATERMARKED_SHA256:
        return "korea_bottom_asset_sha_mismatch"
    gcs_object = str(getattr(asset, "gcs_object", "") or "")
    if gcs_object and not gcs_object.startswith("assets/keysuri/korea_bottom/"):
        return "korea_bottom_asset_gcs_object_role_mismatch"
    return None


def _download_korea_bottom_asset_from_gcs(dest: Path, gcs_object: str) -> Optional[str]:
    bucket_name = admin_artifact_bucket_name()
    if not bucket_name:
        return "korea_bottom_asset_gcs_bucket_not_configured"
    object_name = str(gcs_object or KEYSURI_KOREA_BOTTOM_GCS_OBJECT).strip()
    if not object_name:
        return "korea_bottom_asset_gcs_object_not_configured"
    try:
        from google.cloud import storage

        blob = storage.Client().bucket(bucket_name).blob(object_name)
        if not blob.exists():
            return "korea_bottom_asset_gcs_missing"
        dest.parent.mkdir(parents=True, exist_ok=True)
        blob.download_to_filename(str(dest))
    except Exception as exc:
        logger.warning("korea bottom asset GCS download failed: %s", type(exc).__name__)
        return "korea_bottom_asset_gcs_download_failed"
    return None


def resolve_korea_bottom_email_asset_path(run_id: str) -> Tuple[Optional[Path], List[str]]:
    """Resolve the locked 105936 bottom shot for Korea owner-review CID email only."""
    asset = _korea_bottom_registry_asset()
    issue = _validate_korea_bottom_asset_record(asset)
    if issue:
        return None, [issue]

    local = asset.resolved_watermarked_path(_REPO) if asset is not None else None
    if local is not None and local.is_file():
        if _sha256_file(local) == KEYSURI_KOREA_BOTTOM_WATERMARKED_SHA256:
            return local, []
        return None, ["korea_bottom_asset_local_sha_mismatch"]

    dest = _REPO / "output" / "admin_runs" / "keysuri_service_assets" / f"{run_id}_korea_bottom_105936.jpg"
    gcs_object = getattr(asset, "gcs_object", "") or KEYSURI_KOREA_BOTTOM_GCS_OBJECT
    issue = _download_korea_bottom_asset_from_gcs(dest, gcs_object)
    if issue:
        return None, [issue]
    if not dest.is_file():
        return None, ["korea_bottom_asset_download_missing"]
    if _sha256_file(dest) != KEYSURI_KOREA_BOTTOM_WATERMARKED_SHA256:
        return None, ["korea_bottom_asset_download_sha_mismatch"]
    return dest, []


def resolve_korea_bottom_email_image_path(run_id: str) -> Tuple[Optional[Path], List[str], Dict[str, Any]]:
    """
    Resolve Korea bottom-shot email image through the disabled-by-default variation gate.

    Generation is intentionally not implemented in this patch. When the gate is enabled,
    the runtime still falls back to fixed watermarked 105936 and records not_implemented
    metadata instead of calling any bottom image API.
    """
    variation_enabled = korea_bottom_variation_enabled()
    path, issues = resolve_korea_bottom_email_asset_path(run_id)
    metadata: Dict[str, Any] = {
        "bottom_shot_variation_enabled": variation_enabled,
        "bottom_shot_reference_direction": KEYSURI_KOREA_BOTTOM_REFERENCE_DIRECTION,
        "bottom_shot_asset_id": KEYSURI_KOREA_BOTTOM_ASSET_ID,
        "bottom_shot_watermark_status": "applied" if path is not None else "unavailable",
    }
    if variation_enabled:
        metadata.update(
            {
                "bottom_shot_source": "fixed_105936_fallback_variation_not_implemented",
                "bottom_shot_variation_status": "not_implemented",
            }
        )
    else:
        metadata["bottom_shot_source"] = "fixed_105936_fallback"
    if path is not None:
        metadata["bottom_shot_image_path"] = _repo_rel(path)
    return path, issues, metadata


def _service_artifact_storage_durable() -> bool:
    from admin_store import artifact_storage_backend_name, check_artifact_store_ready

    if artifact_storage_backend_name() != "gcs":
        return False
    err, _desc = check_artifact_store_ready()
    return err is None


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


def _build_service_contract_fixture(
    program_id: str,
    *,
    prompt_input: dict,
    generated_briefing: dict,
    generated_image_path: Path,
    run_id: str,
    image_mode: str = IMAGE_MODE_PREVIEW,
) -> dict:
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
        image_mode=image_mode,
    )
    if image_mode == IMAGE_MODE_EMAIL:
        if program_id == PROGRAM_GLOBAL:
            contract_fixture["top_shot_image_src"] = keysuri_global_service_email_cid_src(run_id)
        elif program_id == PROGRAM_KOREA:
            contract_fixture["top_shot_image_src"] = keysuri_korea_service_email_cid_src(run_id)
    return contract_fixture


def _render_service_html(
    program_id: str,
    *,
    prompt_input: dict,
    generated_briefing: dict,
    generated_image_path: Path,
    run_id: str,
    image_mode: str = IMAGE_MODE_PREVIEW,
) -> tuple[str, str]:
    out_dir = _REPO / "output" / "admin_runs" / "keysuri_service"
    out_dir.mkdir(parents=True, exist_ok=True)
    html_path = out_dir / f"{run_id}.html"
    contract_fixture = _build_service_contract_fixture(
        program_id,
        prompt_input=prompt_input,
        generated_briefing=generated_briefing,
        generated_image_path=generated_image_path,
        run_id=run_id,
        image_mode=image_mode,
    )
    html = render_keysuri_contract_preview_html(
        contract_fixture,
        repo_root=_REPO,
        image_mode=image_mode,
        auto_prepare=False,
    )
    if image_mode == IMAGE_MODE_PREVIEW:
        html_path.write_text(html, encoding="utf-8")
    try:
        rel = html_path.resolve().relative_to(_REPO.resolve()).as_posix()
    except ValueError:
        rel = str(html_path.resolve())
    return html, rel


def _owner_review_email_html(
    preview_html: str,
    *,
    program_id: str,
    run_id: str,
    subject: str | None = None,
) -> str:
    """Wrap contract-preview premium briefing HTML for SMTP without nesting or debug headers."""
    admin_url = build_owner_review_admin_url(run_id) or ""
    email_subject = (
        str(subject or "").strip()
        or _PROGRAM_EMAIL_SUBJECT.get(program_id, "")
        or PROGRAM_DISPLAY.get(program_id, program_id)
    )
    return build_keysuri_owner_review_email_html(
        preview_html,
        subject=email_subject,
        admin_url=admin_url,
        run_id=run_id,
    )


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
    generated_briefing = smoke.generated_briefing if isinstance(smoke.generated_briefing, dict) else None
    if not generated_briefing:
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

    raw_generated_image_path = str(image_outcome.generated_image_path or "")
    gen_image_raw_abs = _REPO / raw_generated_image_path
    try:
        gen_image_abs = _watermarked_top_shot_path(gen_image_raw_abs)
    except Exception as exc:
        issue_codes.append("keysuri_top_shot_watermark_failed")
        meta = build_service_artifact_fields(
            run_id=run_id,
            mode=pid,
            program_id=pid,
            trigger_source=trigger_source,
            validation_result=validation_result,
            issue_codes=issue_codes,
            called_gemini=True,
            image_outcome=image_outcome,
            email_sent=False,
            error_code="keysuri_top_shot_watermark_failed",
        )
        meta["generated_image_path_raw"] = raw_generated_image_path
        meta["top_shot_watermark_status"] = "failed"
        meta["top_shot_watermark_error_type"] = type(exc).__name__
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
            "generated_image_path": raw_generated_image_path,
            "email_sent": False,
            "error": "keysuri_top_shot_watermark_failed",
        }
    watermarked_generated_image_path = _repo_rel(gen_image_abs)
    image_outcome.generated_image_path = watermarked_generated_image_path
    contract_fixture_preview = _build_service_contract_fixture(
        pid,
        prompt_input=prompt_input,
        generated_briefing=generated_briefing,
        generated_image_path=gen_image_abs,
        run_id=run_id,
        image_mode=IMAGE_MODE_PREVIEW,
    )
    html = render_keysuri_contract_preview_html(
        contract_fixture_preview,
        repo_root=_REPO,
        image_mode=IMAGE_MODE_PREVIEW,
        auto_prepare=False,
    )
    out_dir = _REPO / "output" / "admin_runs" / "keysuri_service"
    out_dir.mkdir(parents=True, exist_ok=True)
    html_path = out_dir / f"{run_id}.html"
    html_path.write_text(html, encoding="utf-8")
    try:
        html_rel = html_path.resolve().relative_to(_REPO.resolve()).as_posix()
    except ValueError:
        html_rel = str(html_path.resolve())
    html_body = html
    owner_review_url = build_owner_review_admin_url(run_id) or ""
    storage_durable = _service_artifact_storage_durable()
    bottom_image_path: Optional[Path] = None
    bottom_image_status = "not_applicable"
    bottom_image_source = ""
    bottom_image_meta: Dict[str, Any] = {}
    if pid == PROGRAM_KOREA:
        bottom_image_path, bottom_issues, bottom_image_meta = resolve_korea_bottom_email_image_path(run_id)
        if bottom_image_path is not None:
            bottom_image_status = "available"
            bottom_image_source = str(bottom_image_meta.get("bottom_shot_source") or "fixed_105936_fallback")
        else:
            bottom_image_status = "placeholder"
            issue_codes.extend(bottom_issues)

    if pid == PROGRAM_GLOBAL:
        contract_fixture_email = dict(contract_fixture_preview)
        contract_fixture_email["top_shot_image_src"] = keysuri_global_service_email_cid_src(run_id)
        email_html = build_keysuri_global_gmail_owner_email_html(
            contract_fixture_email,
            subject=_PROGRAM_EMAIL_SUBJECT.get(pid, ""),
            admin_url=owner_review_url,
            run_id=run_id,
        )
    elif pid == PROGRAM_KOREA:
        contract_fixture_email = dict(contract_fixture_preview)
        contract_fixture_email["top_shot_image_src"] = keysuri_korea_service_email_cid_src(run_id)
        if bottom_image_path is not None:
            contract_fixture_email["bottom_shot_image_src"] = keysuri_korea_bottom_service_email_cid_src(run_id)
        email_html = build_keysuri_korea_gmail_owner_email_html(
            contract_fixture_email,
            subject=_PROGRAM_EMAIL_SUBJECT.get(pid, ""),
            admin_url=owner_review_url,
            run_id=run_id,
        )
    else:
        email_preview_html, _ = _render_service_html(
            pid,
            prompt_input=prompt_input,
            generated_briefing=generated_briefing,
            generated_image_path=gen_image_abs,
            run_id=run_id,
            image_mode=IMAGE_MODE_EMAIL,
        )
        email_html = _owner_review_email_html(
            email_preview_html,
            program_id=pid,
            run_id=run_id,
            subject=_PROGRAM_EMAIL_SUBJECT.get(pid),
        )

    email_sent = False
    smtp_attempted = False
    if send_owner_email:
        if os.getenv("GENIE_OWNER_REVIEW_SEND", "").strip() not in ("1", "true", "yes"):
            issue_codes.append("owner_review_send_gate_off")
        else:
            subject = _PROGRAM_EMAIL_SUBJECT.get(pid, f"[운영자 검토] {PROGRAM_DISPLAY.get(pid, pid)}")
            smtp_attempted = True
            sender = send_fn or send_genie_email
            if pid == PROGRAM_GLOBAL:
                if not gen_image_abs.is_file():
                    issue_codes.append("generated_image_missing_for_cid_email")
                else:
                    os.environ.setdefault("GENIE_EMAIL_RICH_MODE", "1")
                    inline_parts = inline_jpeg_parts_for_global_service_email(gen_image_abs, run_id)
                    email_sent = bool(
                        sender(
                            email_html,
                            subject,
                            inline_jpeg_parts=inline_parts,
                            attachment_jpeg_parts=[],
                        )
                    )
            elif pid == PROGRAM_KOREA:
                if not gen_image_abs.is_file():
                    issue_codes.append("generated_image_missing_for_cid_email")
                else:
                    os.environ.setdefault("GENIE_EMAIL_RICH_MODE", "1")
                    inline_parts = inline_jpeg_parts_for_korea_service_email(
                        gen_image_abs,
                        run_id,
                        bottom_image_path=bottom_image_path,
                    )
                    email_sent = bool(
                        sender(
                            email_html,
                            subject,
                            inline_jpeg_parts=inline_parts,
                            attachment_jpeg_parts=[],
                        )
                    )
            else:
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
        owner_review_url=owner_review_url or None,
        artifact_storage_durable=storage_durable,
    )
    meta["artifact_status"] = "emailed" if email_sent else "stored"
    meta["generated_image_path_raw"] = raw_generated_image_path
    meta["generated_image_path_watermarked"] = watermarked_generated_image_path
    meta["top_shot_watermark_status"] = "applied"
    meta["top_shot_watermark_text"] = "MirAI:ON"
    if pid == PROGRAM_KOREA:
        meta.update(bottom_image_meta)
        meta.setdefault("bottom_shot_variation_enabled", korea_bottom_variation_enabled())
        meta.setdefault("bottom_shot_source", bottom_image_source or "fixed_105936_fallback_unavailable")
        meta.setdefault("bottom_shot_asset_id", KEYSURI_KOREA_BOTTOM_ASSET_ID)
        meta.setdefault("bottom_shot_watermark_status", "applied" if bottom_image_path is not None else "unavailable")
        meta["korea_bottom_shot_asset_id"] = KEYSURI_KOREA_BOTTOM_ASSET_ID
        meta["korea_bottom_shot_status"] = bottom_image_status
        if bottom_image_source:
            meta["korea_bottom_shot_source"] = bottom_image_source
        if bottom_image_path is not None:
            try:
                meta["korea_bottom_shot_path"] = bottom_image_path.resolve().relative_to(_REPO.resolve()).as_posix()
            except ValueError:
                meta["korea_bottom_shot_path"] = str(bottom_image_path.resolve())
            meta["korea_bottom_shot_cid"] = keysuri_korea_bottom_service_email_cid_token(run_id)
            meta.setdefault("bottom_shot_image_path", meta["korea_bottom_shot_path"])
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
        "generated_image_path_raw": raw_generated_image_path,
        "generated_image_path_watermarked": watermarked_generated_image_path,
        "top_shot_watermark_status": meta.get("top_shot_watermark_status"),
        "html_path": html_rel,
        "owner_review_html_path": meta.get("owner_review_html_path"),
        "owner_review_url": owner_review_url,
        "artifact_storage_durable": storage_durable,
        "artifact_status": meta.get("artifact_status"),
        "smtp_attempted": smtp_attempted,
        "email_sent": email_sent,
        "korea_bottom_shot_status": meta.get("korea_bottom_shot_status"),
    }
