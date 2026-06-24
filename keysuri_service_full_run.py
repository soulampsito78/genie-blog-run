"""Kee-Suri Global/Korea service-level full run with generated images."""
from __future__ import annotations

import json
import logging
import os
import hashlib
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from admin_store import admin_artifact_bucket_name, admin_artifact_gcs_prefix, artifact_email_path, artifact_json_path, generate_run_id, save_run_artifact
from admin_urls import build_owner_review_admin_url
import email_sender
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
from keysuri_bottom_shot_generation import generate_keysuri_korea_bottom_v6
from keysuri_generation_prompt import parse_keysuri_generated_response
from keysuri_email_identity import build_keysuri_subject_artifact_fields
from keysuri_visible_text_quality import (
    KEYSURI_KOREAN_CONNECTOR_ELLIPSIS_BLOCKED,
    merge_visible_text_quality_fields,
    validate_and_repair_keysuri_visible_text_quality,
    validate_keysuri_html_visible_text_quality,
)
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
    """Korea beta path defaults on; explicit false/off disables generation."""
    raw = os.getenv(KEYSURI_KOREA_BOTTOM_VARIATION_ENV)
    if raw is None or not raw.strip():
        return True
    return raw.strip().lower() not in ("0", "false", "no", "off")


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


def _upload_keysuri_image(bucket_name: str, object_name: str, source_path: Path) -> None:
    from google.cloud import storage

    storage.Client().bucket(bucket_name).blob(object_name).upload_from_filename(
        str(source_path), content_type="image/jpeg"
    )


def _persist_korea_generated_images(
    run_id: str,
    top_path: Path,
    bottom_path: Optional[Path],
    *,
    upload_fn=None,
) -> Dict[str, Any]:
    """Upload Korea generated Top + Bottom v6 images to GCS for cross-instance restore.

    Called only when bottom_shot_source == 'generated_v6_multi_ref'.
    Returns metadata fields to merge into the run artifact.
    """
    fields: Dict[str, Any] = {}
    bucket_name = admin_artifact_bucket_name()
    if not bucket_name:
        fields.update(
            top_image_persistence_status="local_only",
            top_image_persistence_reason="artifact_bucket_not_configured",
            bottom_shot_persistence_status="local_only",
            bottom_shot_persistence_reason="artifact_bucket_not_configured",
        )
        return fields

    prefix = admin_artifact_gcs_prefix()
    uploader = upload_fn or _upload_keysuri_image

    top_object = f"{prefix}/{run_id}.images/korea_top.jpg"
    try:
        uploader(bucket_name, top_object, top_path)
        fields.update(
            top_image_persistence_status="persisted",
            korea_generated_top_gcs_object=top_object,
            korea_generated_image_gcs_bucket=bucket_name,
        )
    except Exception as exc:
        logger.warning("keysuri Korea Top GCS upload failed: %s", type(exc).__name__)
        fields.update(
            top_image_persistence_status="failed",
            top_image_persistence_reason="gcs_upload_failed",
        )

    if bottom_path is not None:
        bottom_object = f"{prefix}/{run_id}.images/korea_bottom.jpg"
        try:
            uploader(bucket_name, bottom_object, bottom_path)
            fields.update(
                bottom_shot_persistence_status="persisted",
                korea_generated_bottom_gcs_object=bottom_object,
            )
            fields.setdefault("korea_generated_image_gcs_bucket", bucket_name)
        except Exception as exc:
            logger.warning("keysuri Korea Bottom v6 GCS upload failed: %s", type(exc).__name__)
            fields.update(
                bottom_shot_persistence_status="failed",
                bottom_shot_persistence_reason="gcs_upload_failed",
            )

    return fields


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


_EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_SENSITIVE_DIAGNOSTIC_RE = re.compile(
    r"(?i)\b(password|passwd|token|secret|authorization)\b(\s*[=:]\s*)([^\s,;]+)"
)


def _dedupe_preserve_order(values: List[str]) -> List[str]:
    seen: set[str] = set()
    out: List[str] = []
    for value in values:
        key = value.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(value.strip())
    return out


def _mask_email_address(address: str) -> str:
    raw = str(address or "").strip()
    if "@" not in raw:
        return ""
    local, domain = raw.rsplit("@", 1)
    local = local.strip()
    domain = domain.strip().lower()
    if not local or not domain:
        return ""
    if len(local) <= 4:
        masked_local = f"{local[:1]}***"
    else:
        masked_local = f"{local[:2]}***{local[-2:]}"
    return f"{masked_local}@{domain}"


def _mask_email_addresses(addresses: List[str]) -> List[str]:
    masked = [_mask_email_address(addr) for addr in _dedupe_preserve_order(addresses)]
    return [addr for addr in masked if addr]


def _recipient_domains(addresses: List[str]) -> List[str]:
    domains: List[str] = []
    for address in _dedupe_preserve_order(addresses):
        raw = str(address or "").strip()
        if "@" not in raw:
            continue
        domain = raw.rsplit("@", 1)[1].strip().lower()
        if domain:
            domains.append(domain)
    return _dedupe_preserve_order(domains)


def _safe_trace_path(path_value: Any) -> str:
    raw = str(path_value or "").strip()
    if not raw:
        return ""
    path = Path(raw)
    try:
        return path.resolve().relative_to(_REPO.resolve()).as_posix()
    except (OSError, ValueError):
        return path.name


def _owner_email_inline_image_hashes(trace: Dict[str, Any]) -> List[Dict[str, str]]:
    hashes: List[Dict[str, str]] = []
    for row in trace.get("inline_input_hashes") or []:
        if not isinstance(row, dict):
            continue
        hashes.append(
            {
                "path": _safe_trace_path(row.get("path")),
                "cid": str(row.get("cid") or ""),
                "filename": Path(str(row.get("filename") or "")).name,
                "sha256": str(row.get("sha256") or ""),
            }
        )
    return hashes


def _sanitize_owner_email_diagnostic(diagnostic: str) -> str:
    clean = str(diagnostic or "")
    if not clean:
        return ""
    clean = _EMAIL_RE.sub(lambda match: _mask_email_address(match.group(0)), clean)
    clean = _SENSITIVE_DIAGNOSTIC_RE.sub(r"\1\2[redacted]", clean)
    for env_key in ("SMTP_PASSWORD", "SMTP_APP_PASSWORD", "GENIE_INTERNAL_JOB_TOKEN"):
        secret_value = os.getenv(env_key, "").strip()
        if secret_value:
            clean = clean.replace(secret_value, "[redacted]")
    return clean[:500]


def _owner_review_delivery_status(smtp_attempted: bool, email_sent: bool) -> str:
    if email_sent:
        return "smtp_accepted"
    if smtp_attempted:
        return "failed"
    return "not_sent"


def _owner_email_delivery_fields(
    *,
    smtp_attempted: bool,
    email_sent: bool,
    subject: str,
) -> Dict[str, Any]:
    status = _owner_review_delivery_status(smtp_attempted, email_sent)
    trace = email_sender.last_send_trace() if smtp_attempted else {}
    diagnostic = email_sender.last_send_diagnostic() if smtp_attempted else ""
    recipients = [
        str(addr or "").strip()
        for addr in (trace.get("envelope_to") or [])
        if str(addr or "").strip()
    ]
    recipients = _dedupe_preserve_order(recipients)
    return {
        "owner_email_delivery_status": status,
        "owner_email_smtp_attempted": bool(smtp_attempted),
        "owner_email_sent_at_kst": (
            datetime.now(ZoneInfo("Asia/Seoul")).isoformat() if email_sent else None
        ),
        "owner_email_recipient_count": len(recipients),
        "owner_email_recipient_domains": _recipient_domains(recipients),
        "owner_email_recipients_masked": _mask_email_addresses(recipients),
        "owner_email_subject": str(subject or ""),
        "owner_email_mime_html_sha256": str(trace.get("mime_html_sha256") or ""),
        "owner_email_mime_html_bytes_len": int(trace.get("mime_html_bytes_len") or 0),
        "owner_email_inline_image_hashes": _owner_email_inline_image_hashes(trace),
        "owner_email_send_trace_available": bool(trace),
        "owner_email_send_diagnostic": _sanitize_owner_email_diagnostic(diagnostic),
    }


def _log_owner_email_delivery_event(
    *,
    program_id: str,
    run_id: str,
    fields: Dict[str, Any],
) -> None:
    event = {
        "event": "keysuri_owner_review_email_delivery",
        "program_id": program_id,
        "run_id": run_id,
        "smtp_attempted": bool(fields.get("owner_email_smtp_attempted")),
        "email_sent": fields.get("owner_email_delivery_status") == "smtp_accepted",
        "owner_email_delivery_status": fields.get("owner_email_delivery_status"),
        "recipient_count": int(fields.get("owner_email_recipient_count") or 0),
        "recipient_domains": list(fields.get("owner_email_recipient_domains") or []),
        "subject": str(fields.get("owner_email_subject") or ""),
        "inline_image_count": len(fields.get("owner_email_inline_image_hashes") or []),
    }
    logger.info(json.dumps(event, ensure_ascii=False, sort_keys=True))


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


def resolve_korea_bottom_email_image_path(
    run_id: str,
    *,
    weather_condition: str = "cloudy",
    temperature_c: Optional[float] = None,
    season: Optional[str] = None,
    generate_fn: Optional[Callable[..., Path]] = None,
    watermark_fn: Optional[Callable[[Path, Path], Path]] = None,
) -> Tuple[Optional[Path], List[str], Dict[str, Any]]:
    """Generate Korea Bottom v6 first and use fixed 105936 only as fallback."""
    variation_enabled = korea_bottom_variation_enabled()
    generation_error = ""
    anchor_path, anchor_issues = resolve_korea_bottom_email_asset_path(run_id)
    if variation_enabled and anchor_path is not None:
        seed = int(hashlib.sha256(run_id.encode("utf-8")).hexdigest()[:8], 16)
        raw_output = (
            _REPO
            / "output"
            / "admin_runs"
            / "keysuri_service_assets"
            / f"{run_id}_korea_bottom_v6.jpg"
        )
        generated = generate_keysuri_korea_bottom_v6(
            repo_root=_REPO,
            output_path=raw_output,
            weather_condition=weather_condition,
            primary_reference_path=anchor_path,
            temperature_c=temperature_c,
            season=season,
            wardrobe_variant=seed,
            pose_variant=seed >> 8,
            apply_watermark=True,
            watermark_fn=watermark_fn,
            generate_fn=generate_fn,
        )
        if generated.ok and generated.image_path is not None:
            metadata = dict(generated.metadata)
            metadata.update(
                {
                    "bottom_shot_variation_enabled": True,
                    "bottom_shot_reference_direction": KEYSURI_KOREA_BOTTOM_REFERENCE_DIRECTION,
                    "bottom_shot_asset_id": f"keysuri_korea_bottom_generated_{run_id}",
                    "bottom_shot_image_path": _repo_rel(generated.image_path),
                    "bottom_shot_raw_image_path": _repo_rel(generated.raw_image_path or generated.image_path),
                }
            )
            return generated.image_path, [], metadata
        generation_error = generated.error_code or "bottom_v6_generation_failed"
        if generated.error_message:
            generation_error = f"{generation_error}: {generated.error_message}"
    elif variation_enabled:
        generation_error = "bottom_anchor_unavailable"
    else:
        generation_error = "variation_explicitly_disabled"

    path, issues = anchor_path, anchor_issues
    metadata = {
        "bottom_shot_variation_enabled": variation_enabled,
        "bottom_shot_reference_direction": KEYSURI_KOREA_BOTTOM_REFERENCE_DIRECTION,
        "bottom_shot_asset_id": KEYSURI_KOREA_BOTTOM_ASSET_ID,
        "bottom_shot_source": "fixed_105936_fallback",
        "bottom_shot_generated": False,
        "bottom_shot_generation_attempted": variation_enabled,
        "bottom_shot_generation_status": "failed" if variation_enabled else "disabled",
        "bottom_shot_fallback_reason": generation_error,
        "bottom_shot_watermark_status": "applied" if path is not None else "unavailable",
        "bottom_anchor_asset_id": KEYSURI_KOREA_BOTTOM_ASSET_ID,
        "korea_bottom_anchor_asset_id": KEYSURI_KOREA_BOTTOM_ASSET_ID,
        "bottom_anchor_role": "primary_bottom_visual_anchor",
        "bottom_anchor_slot": 0,
        "secondary_reference_asset_id": "Asset01",
        "secondary_reference_role": "secondary_same_person_continuity_reference",
        "secondary_reference_slot": 1,
    }
    if path is not None:
        metadata["bottom_shot_image_path"] = _repo_rel(path)
    return path, issues, metadata


def _korea_bottom_weather_inputs(prompt_input: Dict[str, Any]) -> Dict[str, Any]:
    """Read normalized weather when present, retaining a conservative beta default."""
    source_pack = prompt_input.get("source_pack") if isinstance(prompt_input.get("source_pack"), dict) else {}
    candidates = (
        prompt_input.get("weather_context"),
        prompt_input.get("normalized_weather_context"),
        source_pack.get("weather_context"),
        source_pack.get("normalized_weather_context"),
    )
    weather = next((item for item in candidates if isinstance(item, dict)), {})
    temperature = weather.get("temperature_c")
    if not isinstance(temperature, (int, float)):
        temperature = None
    return {
        "weather_condition": str(weather.get("weather_condition") or "cloudy").strip().lower(),
        "temperature_c": temperature,
        "season": str(weather.get("season") or "").strip() or None,
    }


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


def _extend_unique(values: List[str], extras: List[str]) -> List[str]:
    out = list(values)
    for extra in extras:
        text = str(extra or "").strip()
        if text and text not in out:
            out.append(text)
    return out


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
    bottom_shot_image_path: Optional[Path] = None,
) -> dict:
    contract_fixture = build_contract_preview_fixture_from_generated(
        program_id=program_id,
        prompt_input=prompt_input,
        generated_briefing=generated_briefing,
        source_pack=prompt_input.get("source_pack") or {},
        top_shot_image_path=generated_image_path,
    )
    contract_fixture["fixture_mode"] = "service_full_run_generated"
    if bottom_shot_image_path is not None:
        contract_fixture["bottom_shot_image_path"] = str(bottom_shot_image_path)
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
    preheader: str | None = None,
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
        preheader=preheader,
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
    bottom_generate_fn: Optional[Callable[..., Path]] = None,
    bottom_watermark_fn: Optional[Callable[[Path, Path], Path]] = None,
    send_fn: Optional[Callable[..., bool]] = None,
    image_upload_fn=None,
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

    generated_briefing, visible_text_quality_fields = validate_and_repair_keysuri_visible_text_quality(
        generated_briefing,
        root_path="generated_briefing",
    )
    if visible_text_quality_fields.get("visible_text_ellipsis_blocked"):
        block_issue_codes = _extend_unique(
            issue_codes,
            list(visible_text_quality_fields.get("visible_text_quality_issue_codes") or []),
        )
        meta = build_service_artifact_fields(
            run_id=run_id,
            mode=pid,
            program_id=pid,
            trigger_source=trigger_source,
            validation_result="block",
            issue_codes=block_issue_codes,
            called_gemini=True,
            image_outcome=image_outcome,
            email_sent=False,
            error_code=KEYSURI_KOREAN_CONNECTOR_ELLIPSIS_BLOCKED,
        )
        meta.update(visible_text_quality_fields)
        save_run_artifact(meta, email_html="")
        return {
            "ok": False,
            "run_id": run_id,
            "program_id": pid,
            "service_full_run": True,
            "validation_result": "block",
            "called_gemini": True,
            "called_image_api": image_outcome.called_image_api,
            "email_sent": False,
            "error": KEYSURI_KOREAN_CONNECTOR_ELLIPSIS_BLOCKED,
            "issue_codes": block_issue_codes,
        }

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

    # Resolve Korea bottom shot BEFORE building preview so the preview HTML
    # can embed the actual bottom image (data-URI) instead of the placeholder.
    owner_review_url = build_owner_review_admin_url(run_id) or ""
    storage_durable = _service_artifact_storage_durable()
    bottom_image_path: Optional[Path] = None
    bottom_image_status = "not_applicable"
    bottom_image_source = ""
    bottom_image_meta: Dict[str, Any] = {}
    if pid == PROGRAM_KOREA:
        bottom_image_path, bottom_issues, bottom_image_meta = resolve_korea_bottom_email_image_path(
            run_id,
            **_korea_bottom_weather_inputs(prompt_input),
            generate_fn=bottom_generate_fn,
            watermark_fn=bottom_watermark_fn,
        )
        if bottom_image_path is not None:
            bottom_image_status = "available"
            bottom_image_source = str(bottom_image_meta.get("bottom_shot_source") or "fixed_105936_fallback")
            if bottom_image_source == "generated_v6_multi_ref":
                persist_fields = _persist_korea_generated_images(
                    run_id,
                    gen_image_abs,
                    bottom_image_path,
                    upload_fn=image_upload_fn,
                )
                bottom_image_meta.update(persist_fields)
        else:
            bottom_image_status = "placeholder"
            issue_codes.extend(bottom_issues)

    contract_fixture_preview = _build_service_contract_fixture(
        pid,
        prompt_input=prompt_input,
        generated_briefing=generated_briefing,
        generated_image_path=gen_image_abs,
        run_id=run_id,
        image_mode=IMAGE_MODE_PREVIEW,
        bottom_shot_image_path=bottom_image_path,
    )
    subject_fields = build_keysuri_subject_artifact_fields(
        pid,
        generated_briefing=generated_briefing,
        prompt_input=prompt_input,
        run_id=run_id,
        trigger_source=trigger_source,
        contract_fixture=contract_fixture_preview,
    )
    subject_fields, subject_quality_fields = validate_and_repair_keysuri_visible_text_quality(
        subject_fields,
        root_path="subject_fields",
    )
    visible_text_quality_fields = merge_visible_text_quality_fields(
        visible_text_quality_fields,
        subject_quality_fields,
    )
    if visible_text_quality_fields.get("visible_text_ellipsis_blocked"):
        block_issue_codes = _extend_unique(
            issue_codes,
            list(visible_text_quality_fields.get("visible_text_quality_issue_codes") or []),
        )
        meta = build_service_artifact_fields(
            run_id=run_id,
            mode=pid,
            program_id=pid,
            trigger_source=trigger_source,
            validation_result="block",
            issue_codes=block_issue_codes,
            called_gemini=True,
            image_outcome=image_outcome,
            email_sent=False,
            error_code=KEYSURI_KOREAN_CONNECTOR_ELLIPSIS_BLOCKED,
        )
        meta.update(visible_text_quality_fields)
        meta.update(subject_fields)
        save_run_artifact(meta, email_html="")
        return {
            "ok": False,
            "run_id": run_id,
            "program_id": pid,
            "service_full_run": True,
            "validation_result": "block",
            "called_gemini": True,
            "called_image_api": image_outcome.called_image_api,
            "email_sent": False,
            "error": KEYSURI_KOREAN_CONNECTOR_ELLIPSIS_BLOCKED,
            "issue_codes": block_issue_codes,
        }
    editorial_subject = subject_fields["editorial_subject"]
    owner_subject = subject_fields["owner_email_subject"]
    owner_preheader = subject_fields["owner_email_preheader"]
    contract_fixture_preview["selected_subject"] = editorial_subject
    contract_fixture_preview["preheader"] = owner_preheader
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

    if pid == PROGRAM_GLOBAL:
        contract_fixture_email = dict(contract_fixture_preview)
        contract_fixture_email["top_shot_image_src"] = keysuri_global_service_email_cid_src(run_id)
        email_html = build_keysuri_global_gmail_owner_email_html(
            contract_fixture_email,
            subject=owner_subject,
            preheader=owner_preheader,
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
            subject=owner_subject,
            preheader=owner_preheader,
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
            subject=owner_subject,
            preheader=owner_preheader,
        )

    html_quality_fields = merge_visible_text_quality_fields(
        validate_keysuri_html_visible_text_quality(html, path="owner_preview_html.visible_text"),
        validate_keysuri_html_visible_text_quality(email_html, path="owner_email_html.visible_text"),
    )
    visible_text_quality_fields = merge_visible_text_quality_fields(
        visible_text_quality_fields,
        html_quality_fields,
    )
    if visible_text_quality_fields.get("visible_text_ellipsis_blocked"):
        block_issue_codes = _extend_unique(
            issue_codes,
            list(visible_text_quality_fields.get("visible_text_quality_issue_codes") or []),
        )
        meta = build_service_artifact_fields(
            run_id=run_id,
            mode=pid,
            program_id=pid,
            trigger_source=trigger_source,
            validation_result="block",
            issue_codes=block_issue_codes,
            called_gemini=True,
            image_outcome=image_outcome,
            html_path=html_rel,
            owner_review_html_path=str(artifact_email_path(run_id)),
            smtp_attempted=False,
            email_sent=False,
            workflow_status=smoke.preview_overall_status,
            owner_review_url=owner_review_url or None,
            artifact_storage_durable=storage_durable,
            error_code=KEYSURI_KOREAN_CONNECTOR_ELLIPSIS_BLOCKED,
        )
        meta.update(subject_fields)
        meta.update(visible_text_quality_fields)
        save_run_artifact(meta, email_html="")
        return {
            "ok": False,
            "run_id": run_id,
            "program_id": pid,
            "service_full_run": True,
            "validation_result": "block",
            "called_gemini": True,
            "called_image_api": image_outcome.called_image_api,
            "email_sent": False,
            "error": KEYSURI_KOREAN_CONNECTOR_ELLIPSIS_BLOCKED,
            "issue_codes": block_issue_codes,
            "html_path": html_rel,
        }

    email_sent = False
    smtp_attempted = False
    subject = owner_subject
    if send_owner_email:
        if os.getenv("GENIE_OWNER_REVIEW_SEND", "").strip() not in ("1", "true", "yes"):
            issue_codes.append("owner_review_send_gate_off")
        else:
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
    owner_email_fields = _owner_email_delivery_fields(
        smtp_attempted=smtp_attempted,
        email_sent=email_sent,
        subject=subject,
    )
    meta.update(owner_email_fields)
    meta.update(subject_fields)
    meta.update(visible_text_quality_fields)
    meta["owner_email_subject"] = subject
    _log_owner_email_delivery_event(program_id=pid, run_id=run_id, fields=owner_email_fields)
    meta["artifact_status"] = "emailed" if email_sent else "stored"
    meta["generated_image_path_raw"] = raw_generated_image_path
    meta["generated_image_path_watermarked"] = watermarked_generated_image_path
    meta["top_shot_watermark_status"] = "applied"
    meta["top_shot_watermark_text"] = "MirAI:ON"
    # Image CID tracking for owner/customer email alignment validation.
    # NOTE: CIDs are date-scoped (keysuri_{top,bottom}shot_korea_YYYYMMDD).
    # TODO: migrate to run_id-scoped CIDs to eliminate same-day cache collision risk.
    top_cid = (
        keysuri_global_service_email_cid_token(run_id)
        if pid == PROGRAM_GLOBAL
        else keysuri_korea_service_email_cid_token(run_id)
    )
    meta["top_image_cid"] = top_cid
    meta["owner_email_image_cids"] = [top_cid]
    if pid == PROGRAM_KOREA:
        meta.update(bottom_image_meta)
        meta.setdefault("bottom_shot_variation_enabled", korea_bottom_variation_enabled())
        meta.setdefault("bottom_shot_source", bottom_image_source or "fixed_105936_fallback_unavailable")
        meta.setdefault("bottom_shot_asset_id", KEYSURI_KOREA_BOTTOM_ASSET_ID)
        meta.setdefault("bottom_shot_watermark_status", "applied" if bottom_image_path is not None else "unavailable")
        meta["korea_bottom_shot_asset_id"] = str(
            meta.get("bottom_shot_asset_id") or KEYSURI_KOREA_BOTTOM_ASSET_ID
        )
        meta["korea_bottom_shot_status"] = bottom_image_status
        if bottom_image_source:
            meta["korea_bottom_shot_source"] = bottom_image_source
        if bottom_image_path is not None:
            try:
                meta["korea_bottom_shot_path"] = bottom_image_path.resolve().relative_to(_REPO.resolve()).as_posix()
            except ValueError:
                meta["korea_bottom_shot_path"] = str(bottom_image_path.resolve())
            bottom_cid = keysuri_korea_bottom_service_email_cid_token(run_id)
            meta["korea_bottom_shot_cid"] = bottom_cid
            meta["bottom_image_cid"] = bottom_cid
            meta.setdefault("bottom_shot_image_path", meta["korea_bottom_shot_path"])
            meta["owner_email_image_cids"] = [top_cid, bottom_cid]
            meta["customer_email_image_cids"] = [top_cid, bottom_cid]
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
