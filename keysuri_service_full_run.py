"""Kee-Suri Global/Korea service-level full run with generated images."""
from __future__ import annotations

import copy
import json
import logging
import os
import hashlib
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple
from zoneinfo import ZoneInfo

from admin_store import (
    admin_artifact_bucket_name,
    admin_artifact_gcs_prefix,
    artifact_email_path,
    artifact_json_path,
    generate_run_id,
    load_run_artifact,
    load_run_email_html,
    now_kst_iso,
    save_run_artifact,
)
from admin_urls import build_owner_review_admin_url
import email_sender
from email_sender import send_genie_email
from keysuri_approved_image_assets import KOREA_BOTTOM_ROLE, list_approved_assets
from keysuri_image_overlay import apply_keysuri_mirai_on_watermark
from keysuri_contract_preview_fixture import build_contract_preview_fixture_from_generated
from keysuri_contract_preview_renderer import (
    IMAGE_MODE_EMAIL,
    IMAGE_MODE_PREVIEW,
    assemble_image_only_reissue_email_html,
    build_keysuri_global_gmail_owner_email_html,
    build_keysuri_korea_gmail_owner_email_html,
    build_keysuri_owner_review_email_html,
    image_only_reissue_email_has_body,
    prepare_contract_preview_fixture,
    render_keysuri_contract_preview_html,
)
from keysuri_briefing_content_enricher import enrich_generated_briefing_content
from keysuri_bottom_shot_generation import generate_keysuri_korea_bottom_v6
from keysuri_generation_prompt import parse_keysuri_generated_response
from keysuri_generation_prompt import build_keysuri_generation_prompt
from keysuri_gemini_client import call_keysuri_gemini_text
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


def _kst_dashed_date_from_run_id(run_id: str) -> str:
    """KST date as YYYY-MM-DD (top image variation seed format)."""
    stamp = _kst_date_from_run_id(run_id)
    if len(stamp) == 8 and stamp.isdigit():
        return f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:8]}"
    return stamp


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
        f"Kee-Suri private AI tech briefing secretary hero image for {label} owner-review briefing. "
        "Same recognizable Kee-Suri person as the reference: refined Korean visual impression, "
        "sleek short bob, thin metal glasses, calm attentive intelligent gaze. "
        "One-person private briefing mood, quietly competent and composed; "
        "not a public news anchor, not a weathercaster, not a CEO or chairwoman or senior executive, "
        "not a fashion model, not a generic office worker. "
        "Refined private tech secretary office styling, natural Seoul interior light, high detail commercial realism, "
        "no text, no logo, no watermark, no split screen.\n\n"
        "NEGATIVE:\nno age label\nnot a public news anchor\nnot a weathercaster\n"
        "no CEO or chairwoman or senior executive framing\nno fashion model styling\n"
        "no readable text overlay\nno collage\nno split screen"
    )


def _safe_keysuri_top_headline(smoke: LiveSourceSmokeResult, program_id: str) -> str:
    """Best-effort top headline for the top image diversity seed (never raises)."""
    try:
        from keysuri_email_identity import extract_keysuri_top_headline

        briefing = smoke.generated_briefing if isinstance(smoke.generated_briefing, dict) else None
        if not briefing:
            return ""
        return str(extract_keysuri_top_headline(generated_briefing=briefing) or "").strip()
    except Exception:  # noqa: BLE001 — headline is optional for the seed
        return ""


def _keysuri_top_image_variation_fields(
    program_id: str,
    run_id: str,
    subject_top_headline: str,
) -> Dict[str, Any]:
    """Resolve artifact-safe top image variation metadata (never raises)."""
    try:
        from keysuri_weather_visual_prompt_integration import (
            build_keysuri_production_top_image_prompt,
        )

        run_date_kst = _kst_dashed_date_from_run_id(run_id)
        built = build_keysuri_production_top_image_prompt(
            program_id,
            run_date_kst=run_date_kst,
            subject_top_headline=subject_top_headline,
        )
        # variation metadata already carries top_image_final_prompt_validation_* —
        # this is the SAME deterministic prompt validated inside the image gate.
        return dict(built["variation"])
    except Exception:  # noqa: BLE001 — metadata is best-effort, never blocks a run
        return {}


def _generate_keysuri_service_image(
    program_id: str,
    *,
    generate_fn: Optional[Callable[..., Path]] = None,
    run_id: Optional[str] = None,
    subject_top_headline: str = "",
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

    run_date_kst = _kst_dashed_date_from_run_id(run_id) if run_id else None
    prompt_source, gate_issues, gate_ready = _gate_prompt_source(
        DEFAULT_LOCK_PATH,
        program_id,
        manual_approval_for_gate=True,
        run_date_kst=run_date_kst,
        subject_top_headline=subject_top_headline,
    )
    # The FINAL diversified prompt must pass safety validation before it can reach
    # the image API. If it blocks, fail closed — do NOT silently fall back to a
    # generic prompt and do NOT call the image API.
    if (
        isinstance(prompt_source, dict)
        and prompt_source.get("final_prompt_validation_status") == "block"
    ):
        codes = prompt_source.get("final_prompt_validation_issues") or []
        if codes and isinstance(codes[0], dict):
            codes = [c.get("code") for c in codes]
        return ServiceImageOutcome(
            error_code=ERROR_IMAGE_GENERATION_FAILED,
            error_message="final_prompt_validation_failed: " + ", ".join(str(c) for c in codes),
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


def _image_only_regen_cid_tokens(program_id: str, run_id: str) -> Tuple[str, Optional[str]]:
    stamp = _kst_date_from_run_id(run_id)
    suffix = str(run_id or "").rsplit("_", 1)[-1]
    if program_id == PROGRAM_GLOBAL:
        return f"{KEYSURI_GLOBAL_SERVICE_EMAIL_CID_PREFIX}_{stamp}_regen_{suffix}", None
    return (
        f"{KEYSURI_KOREA_SERVICE_EMAIL_CID_PREFIX}_{stamp}_regen_{suffix}",
        f"{KEYSURI_KOREA_BOTTOM_SERVICE_EMAIL_CID_PREFIX}_{stamp}_regen_{suffix}",
    )


def _replace_keysuri_image_cids(
    html_body: str,
    *,
    program_id: str,
    top_cid: str,
    bottom_cid: Optional[str] = None,
) -> str:
    body = str(html_body or "")
    if program_id == PROGRAM_GLOBAL:
        return re.sub(
            r"cid:keysuri_topshot_global_[0-9]{8}(?:_regen_[a-f0-9]+)?",
            f"cid:{top_cid}",
            body,
        )
    body = re.sub(
        r"cid:keysuri_topshot_korea_[0-9]{8}(?:_regen_[a-f0-9]+)?",
        f"cid:{top_cid}",
        body,
    )
    if bottom_cid:
        body = re.sub(
            r"cid:keysuri_bottomshot_korea_[0-9]{8}(?:_regen_[a-f0-9]+)?",
            f"cid:{bottom_cid}",
            body,
        )
    return body


def _subject_headline_from_artifact(meta: Dict[str, Any]) -> str:
    for key in ("subject_top_headline", "top_image_subject_headline", "top_headline"):
        text = str(meta.get(key) or "").strip()
        if text:
            return text
    for key in ("editorial_subject", "email_subject", "owner_email_subject"):
        text = str(meta.get(key) or "").strip()
        if not text:
            continue
        text = re.sub(r"^\s*(?:\[[^\]]+\]\s*)+", "", text).strip()
        if ": " in text:
            text = text.split(": ", 1)[0].strip()
        if text:
            return text
    return "centered on the preserved briefing content"


def _korea_bottom_weather_inputs_from_artifact(meta: Dict[str, Any]) -> Dict[str, Any]:
    prompt_meta = meta.get("bottom_shot_prompt_metadata")
    if not isinstance(prompt_meta, dict):
        return {"weather_condition": "cloudy", "temperature_c": None, "season": None}
    weather = prompt_meta.get("weather_input")
    if not isinstance(weather, dict):
        weather = {}
    temperature = weather.get("temperature_c")
    if not isinstance(temperature, (int, float)):
        temperature = None
    return {
        "weather_condition": str(
            weather.get("weather_condition_input")
            or weather.get("weather_condition")
            or "cloudy"
        ).strip().lower(),
        "temperature_c": temperature,
        "season": str(weather.get("season_input") or weather.get("season") or "").strip() or None,
    }


def _copy_subject_identity_fields(parent: Dict[str, Any], child: Dict[str, Any]) -> None:
    for key in (
        "email_subject",
        "email_preheader",
        "editorial_subject",
        "subject_top_headline",
        "subject_source",
        "subject_kst_date",
        "subject_kst_time",
        "subject_kst_label",
        "subject_program_label",
        "subject_trigger_label",
    ):
        if key in parent and parent.get(key) is not None:
            child[key] = parent.get(key)


def _regen_source_pack_snapshot(parent: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    for key in ("regen_source_pack_snapshot", "source_pack_snapshot"):
        value = parent.get(key)
        if isinstance(value, dict):
            return copy.deepcopy(value)
    prompt_snapshot = parent.get("regen_prompt_input_snapshot")
    if isinstance(prompt_snapshot, dict) and isinstance(prompt_snapshot.get("source_pack"), dict):
        return copy.deepcopy(prompt_snapshot["source_pack"])
    return None


def _regen_prompt_input_from_parent(parent: Dict[str, Any], program_id: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    source_pack = _regen_source_pack_snapshot(parent)
    if not isinstance(source_pack, dict):
        return None, "regen_missing_source_pack_snapshot"
    prompt_input = build_keysuri_prompt_input(program_id, source_pack)
    prompt_input["source_pack"] = source_pack
    return prompt_input, None


def _regenerate_keysuri_text_from_snapshot(
    parent: Dict[str, Any],
    program_id: str,
    *,
    text_caller: Optional[Callable[..., str]] = None,
) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]], Optional[str]]:
    prompt_input, err = _regen_prompt_input_from_parent(parent, program_id)
    if err:
        return None, None, err
    prompt_text = build_keysuri_generation_prompt(prompt_input)
    caller = text_caller or call_keysuri_gemini_text
    raw_text = caller(prompt_text)
    parse_result = parse_keysuri_generated_response(raw_text, program_id, prompt_input)
    if str(parse_result.get("parse_status") or "") != "parsed_valid":
        return None, None, "generated_briefing_regen_parse_failed"
    generated_briefing = parse_result.get("generated_briefing")
    if not isinstance(generated_briefing, dict):
        return None, None, "generated_briefing_regen_missing"
    generated_briefing = enrich_generated_briefing_content(generated_briefing, program_id, prompt_input)
    generated_briefing, visible_text_quality_fields = validate_and_repair_keysuri_visible_text_quality(
        generated_briefing,
        root_path="generated_briefing",
    )
    if visible_text_quality_fields.get("visible_text_ellipsis_blocked"):
        return None, None, KEYSURI_KOREAN_CONNECTOR_ELLIPSIS_BLOCKED
    return prompt_input, generated_briefing, None


# ---------------------------------------------------------------------------
# text_only reselect helpers
# ---------------------------------------------------------------------------

def _text_only_title_fingerprint(headline: str) -> str:
    """Normalized headline fingerprint for text_only duplicate exclusion."""
    t = re.sub(r"[^\w\s]", " ", str(headline or "").lower())
    t = re.sub(r"\s+", " ", t).strip()[:80]
    words = [w for w in t.split() if len(w) > 2]
    return " ".join(words[:10])


def _build_text_only_exclude_identifiers(
    parent: Dict[str, Any],
) -> Tuple[Set[str], Set[str], List[str]]:
    """Extract previously selected signal identifiers from parent for duplicate exclusion.

    Returns:
        (source_id_set, url_set, title_fingerprint_list)
    """
    source_ids: Set[str] = set()
    urls: Set[str] = set()
    fps: List[str] = []
    prompt_input = parent.get("regen_prompt_input_snapshot")
    if not isinstance(prompt_input, dict):
        return source_ids, urls, fps
    top_5 = prompt_input.get("top_5_news")
    if not isinstance(top_5, dict):
        return source_ids, urls, fps
    items = top_5.get("items")
    if not isinstance(items, list):
        return source_ids, urls, fps
    for item in items:
        if not isinstance(item, dict):
            continue
        news_id = str(item.get("news_id") or "").strip()
        if news_id:
            source_ids.add(news_id)
        for sid in (item.get("source_ids") or []):
            if sid:
                source_ids.add(str(sid))
        headline = str(item.get("headline") or "").strip()
        if headline:
            fps.append(_text_only_title_fingerprint(headline))
    return source_ids, urls, fps


def _filter_source_pack_for_reselect(
    source_pack: Dict[str, Any],
    exclude_source_ids: Set[str],
    exclude_urls: Set[str],
    exclude_fps: List[str],
) -> Tuple[Dict[str, Any], List[str], List[str]]:
    """Return (filtered_source_pack, excluded_claim_ids, excluded_fps) with previously selected claims removed."""
    filtered = copy.deepcopy(source_pack)
    claims = filtered.get("claims")
    if not isinstance(claims, list):
        return filtered, [], []
    excluded_ids: List[str] = []
    excluded_fps_out: List[str] = []
    remaining: List[Any] = []
    exclude_fps_set = set(exclude_fps)
    for claim in claims:
        if not isinstance(claim, dict):
            remaining.append(claim)
            continue
        cid = str(claim.get("claim_id") or "").strip()
        url = str(claim.get("url") or "").strip()
        headline = str(claim.get("headline") or claim.get("title") or "").strip()
        claim_sids = [str(s) for s in (claim.get("source_ids") or []) if s]
        is_excluded = (
            (cid and cid in exclude_source_ids)
            or any(sid in exclude_source_ids for sid in claim_sids)
            or (url and url in exclude_urls)
            or (headline and _text_only_title_fingerprint(headline) in exclude_fps_set)
        )
        if is_excluded:
            if cid:
                excluded_ids.append(cid)
            if headline:
                excluded_fps_out.append(_text_only_title_fingerprint(headline))
        else:
            remaining.append(claim)
    filtered["claims"] = remaining
    # For global program: also filter global_top5_selection.selected_source_ids
    global_sel = filtered.get("global_top5_selection")
    if isinstance(global_sel, dict):
        sel_ids = global_sel.get("selected_source_ids")
        if isinstance(sel_ids, list):
            global_sel["selected_source_ids"] = [
                sid for sid in sel_ids if sid not in exclude_source_ids
            ]
    return filtered, excluded_ids, excluded_fps_out


def _regenerate_keysuri_text_from_source_pack(
    program_id: str,
    source_pack: Dict[str, Any],
    *,
    text_caller: Optional[Callable[..., str]] = None,
) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]], Optional[str]]:
    """Build prompt_input from a given source_pack and regenerate text via Gemini.

    Like _regenerate_keysuri_text_from_snapshot but takes source_pack directly,
    used for text_only reselect (candidate pool filtering already applied).
    """
    try:
        prompt_input = build_keysuri_prompt_input(program_id, source_pack)
    except (ValueError, KeyError) as exc:
        return None, None, f"text_only_reselect_candidate_pool_exhausted: {exc}"
    prompt_input["source_pack"] = source_pack
    prompt_text = build_keysuri_generation_prompt(prompt_input)
    caller = text_caller or call_keysuri_gemini_text
    raw_text = caller(prompt_text)
    parse_result = parse_keysuri_generated_response(raw_text, program_id, prompt_input)
    if str(parse_result.get("parse_status") or "") != "parsed_valid":
        return None, None, "generated_briefing_regen_parse_failed"
    generated_briefing = parse_result.get("generated_briefing")
    if not isinstance(generated_briefing, dict):
        return None, None, "generated_briefing_regen_missing"
    generated_briefing = enrich_generated_briefing_content(generated_briefing, program_id, prompt_input)
    generated_briefing, visible_text_quality_fields = validate_and_repair_keysuri_visible_text_quality(
        generated_briefing,
        root_path="generated_briefing",
    )
    if visible_text_quality_fields.get("visible_text_ellipsis_blocked"):
        return None, None, KEYSURI_KOREAN_CONNECTOR_ELLIPSIS_BLOCKED
    return prompt_input, generated_briefing, None


def _resolve_saved_artifact_path(parent: Dict[str, Any], *keys: str) -> Optional[Path]:
    for key in keys:
        raw = str(parent.get(key) or "").strip()
        if not raw:
            continue
        path = Path(raw)
        if not path.is_absolute():
            path = _REPO / path
        if path.is_file():
            return path
    return None


def _saved_top_image_path(parent: Dict[str, Any]) -> Optional[Path]:
    return _resolve_saved_artifact_path(
        parent,
        "generated_image_path_watermarked",
        "generated_image_path",
        "top_image_path",
        "top_shot_image_path",
    )


def _saved_korea_bottom_image_path(parent: Dict[str, Any]) -> Optional[Path]:
    return _resolve_saved_artifact_path(
        parent,
        "korea_bottom_shot_path",
        "bottom_shot_image_path",
        "bottom_image_path",
    )


def _text_regen_subject_prefix(regen_type: str) -> str:
    if regen_type == "body_only":
        return "[본문 재발행]"
    if regen_type == "body_and_image":
        return "[본문·이미지 재발행]"
    if regen_type == "image_only":
        return "[이미지 재발행]"
    return ""


def _scope_delivery_reason_fields(regen_type: str) -> Dict[str, bool]:
    return {
        "regen_preserved_images": regen_type == "body_only",
        "regen_regenerated_text": regen_type in ("body_only", "body_and_image"),
        "regen_preserved_text": regen_type == "image_only",
        "regen_regenerated_images": regen_type in ("image_only", "body_and_image"),
        "text_generation_called": regen_type in ("body_only", "body_and_image"),
        "image_generation_called": regen_type in ("image_only", "body_and_image"),
    }


def _dedup_artifact_fields_from_prompt_input(prompt_input: Dict[str, Any]) -> Dict[str, Any]:
    if not prompt_input.get("used_dedup_gate"):
        return {}
    selected = prompt_input.get("selected_items")
    rejected = prompt_input.get("rejected_items")
    summary = prompt_input.get("dedup_summary")
    return {
        "used_dedup_gate": True,
        "selected_items": selected if isinstance(selected, list) else [],
        "rejected_items": rejected if isinstance(rejected, list) else [],
        "dedup_summary": summary if isinstance(summary, dict) else {},
        "required_count": int(prompt_input.get("required_count") or 0),
        "selected_count": int(prompt_input.get("selected_count") or 0),
    }


def _selection_item_key(item: Dict[str, Any]) -> str:
    if not isinstance(item, dict):
        return ""
    canonical_url = str(item.get("canonical_url") or "").strip()
    if canonical_url:
        return canonical_url
    norm_source = str(item.get("normalized_source") or item.get("source") or "").strip().lower()
    norm_title = str(item.get("normalized_title") or item.get("title") or item.get("headline") or "").strip().lower()
    if norm_source or norm_title:
        return f"{norm_source}|{norm_title}"
    return str(item.get("news_id") or item.get("claim_id") or "").strip()


def _selection_key_set(items: Any) -> Set[str]:
    if not isinstance(items, list):
        return set()
    return {k for k in (_selection_item_key(it) for it in items if isinstance(it, dict)) if k}


def _write_owner_review_exposure_log(meta: Dict[str, Any], *, exposure_kind: str) -> None:
    """Append owner-review exposure rows for cross-day dedup memory.

    Separate from sent_news_log (customer-send-only). Gated by the caller on
    artifact_status == "emailed" so previews/no-send/smoke never write. A write
    failure here must never roll back or fail the already-sent owner-review
    email — mirrors the sent_news_log write-failure handling in
    admin_store._update_sent_news_log_after_customer_success.
    """
    pid = str(meta.get("program_id") or meta.get("mode") or "").strip()
    run_id = str(meta.get("run_id") or "").strip()
    selected_items = meta.get("selected_items")
    if not isinstance(selected_items, list) or not selected_items:
        meta["exposure_log_updated"] = False
        meta["exposure_log_update_error"] = "selected_items_missing"
        return
    if not run_id or not pid:
        meta["exposure_log_updated"] = False
        meta["exposure_log_update_error"] = "run_id_or_program_id_missing"
        return
    try:
        from owner_review_exposure_log_store import append_owner_review_exposure

        result = append_owner_review_exposure(
            run_id=run_id,
            program_id=pid,
            exposure_kind=exposure_kind,
            selected_items=[it for it in selected_items if isinstance(it, dict)],
        )
    except Exception as exc:  # noqa: BLE001 - exposure log write must never block owner-review send
        meta["exposure_log_updated"] = False
        meta["exposure_log_update_error"] = f"{type(exc).__name__}"
        return
    meta["exposure_log_updated"] = bool(result.get("ok"))
    meta["exposure_log_written_count"] = int(result.get("appended_count") or 0) + int(result.get("updated_count") or 0)
    meta["exposure_log_path"] = result.get("logical_path") or ""
    meta["exposure_log_update_error"] = None


def _maybe_write_owner_review_exposure_log(
    meta: Dict[str, Any],
    *,
    email_sent: bool,
    exposure_kind: str,
    parent: Optional[Dict[str, Any]] = None,
) -> None:
    """Gate exposure-log writes by delivery + (for reissues) selection-change.

    image_only reissue must never call this (parent body/selection reused
    verbatim — would double-count). body_only/body_and_image reissue writes
    only when the regenerated selection differs from the parent run's
    recorded selection, so a same-selection reissue is not counted twice.
    """
    if not email_sent:
        meta["exposure_log_updated"] = False
        meta["exposure_log_update_error"] = "email_not_sent"
        return
    if exposure_kind != "owner_review_email":
        parent_selected = parent.get("selected_items") if isinstance(parent, dict) else None
        if not isinstance(parent_selected, list) or not parent_selected:
            meta["exposure_log_reissue_compare_status"] = "parent_selection_unavailable"
            meta["exposure_log_updated"] = False
            meta["exposure_log_update_error"] = "parent_selection_unavailable"
            return
        parent_keys = _selection_key_set(parent_selected)
        child_keys = _selection_key_set(meta.get("selected_items"))
        if not child_keys:
            meta["exposure_log_reissue_compare_status"] = "child_selection_unavailable"
            meta["exposure_log_updated"] = False
            meta["exposure_log_update_error"] = "child_selection_unavailable"
            return
        if child_keys == parent_keys:
            meta["exposure_log_reissue_compare_status"] = "same_selection_skipped"
            meta["exposure_log_updated"] = False
            meta["exposure_log_update_error"] = None
            return
        meta["exposure_log_reissue_compare_status"] = "selection_changed_written"
    _write_owner_review_exposure_log(meta, exposure_kind=exposure_kind)


def _owner_subject_for_regen(parent: Dict[str, Any], regenerated_subject: str, regen_type: str) -> str:
    prefix = _text_regen_subject_prefix(regen_type)
    if regen_type == "image_only":
        old_subject = str(
            parent.get("owner_email_subject")
            or parent.get("email_subject")
            or regenerated_subject
        ).strip()
        return old_subject if old_subject.startswith(prefix) else f"{prefix}{old_subject}"
    new_subject = str(regenerated_subject or "").strip()
    if not prefix:
        return new_subject
    return new_subject if new_subject.startswith(prefix) else f"{prefix}{new_subject}"


def run_keysuri_image_only_reissue(
    parent_run_id: str,
    *,
    parent_meta: Optional[Dict[str, Any]] = None,
    parent_email_html: Optional[str] = None,
    trigger_source: str = "admin_image_only_reissue",
    reissue_reason_code: str = "",
    reissue_reason_note: str = "",
    send_owner_email: bool = True,
    image_canary_runner=None,
    bottom_generate_fn: Optional[Callable[..., Path]] = None,
    bottom_watermark_fn: Optional[Callable[[Path, Path], Path]] = None,
    send_fn: Optional[Callable[..., bool]] = None,
    image_upload_fn=None,
) -> Dict[str, Any]:
    """Regenerate Kee-Suri owner-review images without touching briefing text.

    This path intentionally does not call Gemini text generation, news/source
    fetch, customer approval, or customer-final SMTP. It reads the parent
    artifact and saved owner-review email HTML, swaps image CIDs, sends a new
    owner-review email, and stores a new artifact.
    """
    parent = dict(parent_meta or load_run_artifact(parent_run_id, normalize=False) or {})
    pid = str(parent.get("program_id") or parent.get("mode") or "").strip()
    if pid not in _KEYSURI_PROGRAMS:
        return {"ok": False, "error": "image_only_reissue_unsupported_mode", "program_id": pid}

    preserved_email_html = str(parent_email_html if parent_email_html is not None else load_run_email_html(parent_run_id) or "")
    if not preserved_email_html.strip():
        return {
            "ok": False,
            "error": "image_only_reissue_missing_parent_email_html",
            "program_id": pid,
        }

    child_run_id = generate_run_id(pid)
    top_image_headline = _subject_headline_from_artifact(parent)
    top_variation_fields = _keysuri_top_image_variation_fields(
        pid,
        parent_run_id,
        top_image_headline,
    )

    canary_fn = image_canary_runner or _generate_keysuri_service_image
    try:
        image_outcome = canary_fn(
            pid,
            run_id=parent_run_id,
            subject_top_headline=top_image_headline,
        )
    except TypeError:
        image_outcome = canary_fn(pid)
    if not image_outcome.ok:
        return {
            "ok": False,
            "run_id": child_run_id,
            "program_id": pid,
            "error": image_outcome.error_code or ERROR_IMAGE_GENERATION_FAILED,
            "called_gemini": False,
            "called_image_api": bool(image_outcome.called_image_api),
            "text_generation_called": False,
            "image_generation_called": bool(image_outcome.called_image_api),
        }

    raw_generated_image_path = str(image_outcome.generated_image_path or "")
    gen_image_raw_abs = _REPO / raw_generated_image_path
    gen_image_abs = _watermarked_top_shot_path(gen_image_raw_abs)
    watermarked_generated_image_path = _repo_rel(gen_image_abs)
    image_outcome.generated_image_path = watermarked_generated_image_path

    issue_codes: List[str] = []
    bottom_image_path: Optional[Path] = None
    bottom_image_status = "not_applicable"
    bottom_image_source = ""
    bottom_image_meta: Dict[str, Any] = {}
    if pid == PROGRAM_KOREA:
        bottom_image_path, bottom_issues, bottom_image_meta = resolve_korea_bottom_email_image_path(
            child_run_id,
            **_korea_bottom_weather_inputs_from_artifact(parent),
            generate_fn=bottom_generate_fn,
            watermark_fn=bottom_watermark_fn,
        )
        if bottom_image_path is not None:
            bottom_image_status = "available"
            bottom_image_source = str(bottom_image_meta.get("bottom_shot_source") or "fixed_105936_fallback")
            if bottom_image_source == "generated_v6_multi_ref":
                bottom_image_meta.update(
                    _persist_korea_generated_images(
                        child_run_id,
                        gen_image_abs,
                        bottom_image_path,
                        upload_fn=image_upload_fn,
                    )
                )
        else:
            bottom_image_status = "placeholder"
            issue_codes.extend(bottom_issues)

    top_cid, bottom_cid = _image_only_regen_cid_tokens(pid, child_run_id)
    email_html = _replace_keysuri_image_cids(
        preserved_email_html,
        program_id=pid,
        top_cid=top_cid,
        bottom_cid=bottom_cid,
    )
    email_html = email_html.replace(parent_run_id, child_run_id)
    # Reuse the preserved body verbatim, but rebuild the full email so mobile
    # Gmail shows the briefing instead of folding the (intentionally unchanged)
    # body behind "…" as duplicate threaded content. This swaps in only the new
    # images + a run-unique marker/preheader — it never regenerates body text.
    reissued_at_kst = now_kst_iso()
    email_html = assemble_image_only_reissue_email_html(
        email_html,
        child_run_id=child_run_id,
        reissued_at_kst=reissued_at_kst,
        program_id=pid,
    )
    body_content_present = image_only_reissue_email_has_body(email_html)

    old_subject = str(
        parent.get("owner_email_subject")
        or parent.get("email_subject")
        or _PROGRAM_EMAIL_SUBJECT.get(pid, "")
        or PROGRAM_DISPLAY.get(pid, pid)
    ).strip()
    subject = old_subject if old_subject.startswith("[이미지 재발행]") else f"[이미지 재발행]{old_subject}"
    preheader = str(parent.get("owner_email_preheader") or parent.get("email_preheader") or "").strip()

    email_sent = False
    smtp_attempted = False
    if send_owner_email:
        if os.getenv("GENIE_OWNER_REVIEW_SEND", "").strip() not in ("1", "true", "yes"):
            issue_codes.append("owner_review_send_gate_off")
        else:
            smtp_attempted = True
            os.environ.setdefault("GENIE_EMAIL_RICH_MODE", "1")
            inline_parts: List[Tuple[str, str, str]] = [
                (str(gen_image_abs.resolve()), top_cid, gen_image_abs.name or "keysuri_top_regen.jpg")
            ]
            if bottom_image_path is not None and bottom_cid:
                inline_parts.append(
                    (
                        str(bottom_image_path.resolve()),
                        bottom_cid,
                        bottom_image_path.name or "keysuri_korea_bottom_regen.jpg",
                    )
                )
            sender = send_fn or send_genie_email
            email_sent = bool(
                sender(
                    email_html,
                    subject,
                    inline_jpeg_parts=inline_parts,
                    attachment_jpeg_parts=[],
                )
            )

    meta = build_service_artifact_fields(
        run_id=child_run_id,
        mode=pid,
        program_id=pid,
        trigger_source=trigger_source,
        validation_result=str(parent.get("validation_result") or "pass"),
        issue_codes=issue_codes,
        called_gemini=False,
        image_outcome=image_outcome,
        html_path=str(parent.get("html_path") or ""),
        owner_review_html_path=str(artifact_email_path(child_run_id)),
        smtp_attempted=smtp_attempted,
        email_sent=email_sent,
        customer_delivery_status="not_sent",
        response_status=200,
        workflow_status=str(parent.get("workflow_status") or "review_required"),
        owner_review_url=build_owner_review_admin_url(child_run_id) or None,
        artifact_storage_durable=_service_artifact_storage_durable(),
    )
    _copy_subject_identity_fields(parent, meta)
    meta.update(
        {
            "regen_type": "image_only",
            "regen_parent_run_id": parent_run_id,
            "regen_requested_at_kst": reissued_at_kst,
            "regen_requested_by": "admin",
            "reissue_scope": "image_only",
            "reissue_scope_supported": True,
            "reissue_scope_status": "executed",
            "email_rebuilt_after_image_reissue": True,
            "reused_body_from_run_id": parent_run_id,
            "rebuilt_email_html_path": str(artifact_email_path(child_run_id)),
            "body_content_present": bool(body_content_present),
            "mobile_gmail_safe_layout": True,
            "reissue_reason_code": reissue_reason_code or None,
            "reissue_reason_note": reissue_reason_note or None,
            "regen_preserved_text": True,
            "regen_regenerated_images": True,
            "text_generation_called": False,
            "image_generation_called": True,
            "source_fetch_called": False,
            "news_fetch_called": False,
            "customer_approve_called": False,
            "customer_final_email_called": False,
            "image_only_regen_source_run_id": parent_run_id,
            "generated_image_path_raw": raw_generated_image_path,
            "generated_image_path_watermarked": watermarked_generated_image_path,
            "top_shot_watermark_status": "applied",
            "top_shot_watermark_text": "MirAI:ON",
            "top_image_cid": top_cid,
            "owner_email_image_cids": [top_cid],
            "owner_email_subject": subject,
            "owner_email_preheader": preheader,
            "email_preheader": meta.get("email_preheader") or preheader,
        }
    )
    if top_variation_fields:
        meta.update(top_variation_fields)
    if pid == PROGRAM_KOREA:
        meta.update(bottom_image_meta)
        meta.setdefault("bottom_shot_variation_enabled", korea_bottom_variation_enabled())
        meta.setdefault("bottom_shot_source", bottom_image_source or "fixed_105936_fallback_unavailable")
        meta.setdefault("bottom_shot_watermark_status", "applied" if bottom_image_path is not None else "unavailable")
        meta["korea_bottom_shot_status"] = bottom_image_status
        if bottom_image_source:
            meta["korea_bottom_shot_source"] = bottom_image_source
        if bottom_image_path is not None and bottom_cid:
            meta["korea_bottom_shot_path"] = _repo_rel(bottom_image_path)
            meta["korea_bottom_shot_cid"] = bottom_cid
            meta["bottom_image_cid"] = bottom_cid
            meta["bottom_shot_image_path"] = meta["korea_bottom_shot_path"]
            meta["owner_email_image_cids"] = [top_cid, bottom_cid]

    owner_email_fields = _owner_email_delivery_fields(
        smtp_attempted=smtp_attempted,
        email_sent=email_sent,
        subject=subject,
    )
    meta.update(owner_email_fields)
    meta["owner_email_subject"] = subject
    _log_owner_email_delivery_event(program_id=pid, run_id=child_run_id, fields=owner_email_fields)
    saved_run_id = save_run_artifact(meta, email_html=email_html)

    return {
        "ok": image_outcome.ok and (not send_owner_email or email_sent),
        "run_id": saved_run_id,
        "program_id": pid,
        "regen_type": "image_only",
        "regen_parent_run_id": parent_run_id,
        "called_gemini": False,
        "called_image_api": image_outcome.called_image_api,
        "text_generation_called": False,
        "image_generation_called": True,
        "email_sent": email_sent,
        "owner_email_subject": subject,
        "customer_delivery_status": "not_sent",
        "top_image_cid": top_cid,
        "bottom_image_cid": bottom_cid,
    }


def run_keysuri_text_only_reissue(
    parent_run_id: str,
    *,
    parent_meta: Optional[Dict[str, Any]] = None,
    trigger_source: str = "admin_text_only_reissue",
    reissue_reason_code: str = "",
    reissue_reason_note: str = "",
    send_owner_email: bool = True,
    text_caller: Optional[Callable[..., str]] = None,
    send_fn: Optional[Callable[..., bool]] = None,
) -> Dict[str, Any]:
    parent = dict(parent_meta or load_run_artifact(parent_run_id, normalize=False) or {})
    pid = str(parent.get("program_id") or parent.get("mode") or "").strip()
    if pid not in _KEYSURI_PROGRAMS:
        return {"ok": False, "error": "text_only_reissue_unsupported_mode", "program_id": pid}

    # text_only: must use parent candidate pool — never start fresh
    source_pack = _regen_source_pack_snapshot(parent)
    if not isinstance(source_pack, dict):
        return {
            "ok": False,
            "error": "text_only_reselect_failed_missing_candidate_pool",
            "program_id": pid,
            "reissue_blocked_reason": (
                "후보군 snapshot이 없어 본문만 재발행 불가. "
                "본문·이미지 모두 재발행(body_and_image)을 사용하십시오."
            ),
        }

    exclude_source_ids, exclude_urls, exclude_fps = _build_text_only_exclude_identifiers(parent)
    selected_count_before = len(exclude_source_ids)

    filtered_source_pack, excluded_ids, excluded_fps_applied = _filter_source_pack_for_reselect(
        source_pack, exclude_source_ids, exclude_urls, exclude_fps
    )

    prompt_input, generated_briefing, regen_error = _regenerate_keysuri_text_from_source_pack(
        pid, filtered_source_pack, text_caller=text_caller,
    )
    if regen_error or prompt_input is None or generated_briefing is None:
        return {"ok": False, "error": regen_error or "text_regeneration_failed", "program_id": pid}

    _new_top_5 = prompt_input.get("top_5_news") if isinstance(prompt_input.get("top_5_news"), dict) else {}
    _new_items = _new_top_5.get("items") if isinstance(_new_top_5.get("items"), list) else []
    replacement_signal_ids = [str(it.get("news_id") or "") for it in _new_items if isinstance(it, dict)]
    replacement_signal_titles = [str(it.get("headline") or "") for it in _new_items if isinstance(it, dict)]
    selected_count_after = len(replacement_signal_ids)

    child_run_id = generate_run_id(pid)
    top_image_path = _saved_top_image_path(parent)
    if top_image_path is None:
        return {"ok": False, "error": "text_only_reissue_missing_saved_top_image", "program_id": pid}
    bottom_image_path = _saved_korea_bottom_image_path(parent) if pid == PROGRAM_KOREA else None

    contract_fixture_preview = _build_service_contract_fixture(
        pid,
        prompt_input=prompt_input,
        generated_briefing=generated_briefing,
        generated_image_path=top_image_path,
        run_id=child_run_id,
        image_mode=IMAGE_MODE_PREVIEW,
        bottom_shot_image_path=bottom_image_path,
    )
    subject_fields = build_keysuri_subject_artifact_fields(
        pid,
        generated_briefing=generated_briefing,
        prompt_input=prompt_input,
        run_id=child_run_id,
        trigger_source=trigger_source,
        contract_fixture=contract_fixture_preview,
    )
    owner_preheader = subject_fields["owner_email_preheader"]
    contract_fixture_preview["selected_subject"] = subject_fields["editorial_subject"]
    contract_fixture_preview["preheader"] = owner_preheader
    preview_html = render_keysuri_contract_preview_html(
        contract_fixture_preview,
        repo_root=_REPO,
        image_mode=IMAGE_MODE_PREVIEW,
        auto_prepare=False,
    )
    out_dir = _REPO / "output" / "admin_runs" / "keysuri_service"
    out_dir.mkdir(parents=True, exist_ok=True)
    html_path = out_dir / f"{child_run_id}.html"
    html_path.write_text(preview_html, encoding="utf-8")
    html_rel = _repo_rel(html_path)

    top_cid = str(parent.get("top_image_cid") or (
        keysuri_global_service_email_cid_token(parent_run_id)
        if pid == PROGRAM_GLOBAL
        else keysuri_korea_service_email_cid_token(parent_run_id)
    ))
    bottom_cid = str(parent.get("bottom_image_cid") or parent.get("korea_bottom_shot_cid") or "").strip()
    contract_fixture_email = dict(contract_fixture_preview)
    contract_fixture_email["top_shot_image_src"] = f"cid:{top_cid}"
    if pid == PROGRAM_KOREA and bottom_image_path is not None:
        contract_fixture_email["bottom_shot_image_src"] = f"cid:{bottom_cid}" if bottom_cid else keysuri_korea_bottom_service_email_cid_src(parent_run_id)
    owner_subject = _owner_subject_for_regen(parent, subject_fields["owner_email_subject"], "body_only")
    owner_review_url = build_owner_review_admin_url(child_run_id) or ""
    if pid == PROGRAM_GLOBAL:
        email_html = build_keysuri_global_gmail_owner_email_html(
            contract_fixture_email,
            subject=owner_subject,
            preheader=owner_preheader,
            admin_url=owner_review_url,
            run_id=child_run_id,
        )
    else:
        email_html = build_keysuri_korea_gmail_owner_email_html(
            contract_fixture_email,
            subject=owner_subject,
            preheader=owner_preheader,
            admin_url=owner_review_url,
            run_id=child_run_id,
        )

    visible_text_quality_fields = merge_visible_text_quality_fields(
        validate_keysuri_html_visible_text_quality(preview_html, path="owner_preview_html.visible_text"),
        validate_keysuri_html_visible_text_quality(email_html, path="owner_email_html.visible_text"),
    )
    if visible_text_quality_fields.get("visible_text_ellipsis_blocked"):
        return {
            "ok": False,
            "error": KEYSURI_KOREAN_CONNECTOR_ELLIPSIS_BLOCKED,
            "program_id": pid,
        }

    smtp_attempted = False
    email_sent = False
    if send_owner_email:
        if os.getenv("GENIE_OWNER_REVIEW_SEND", "").strip() not in ("1", "true", "yes"):
            pass
        else:
            smtp_attempted = True
            os.environ.setdefault("GENIE_EMAIL_RICH_MODE", "1")
            inline_parts = [(str(top_image_path.resolve()), top_cid, top_image_path.name)]
            if pid == PROGRAM_KOREA and bottom_image_path is not None:
                inline_parts.append(
                    (
                        str(bottom_image_path.resolve()),
                        bottom_cid or keysuri_korea_bottom_service_email_cid_token(parent_run_id),
                        bottom_image_path.name,
                    )
                )
            sender = send_fn or send_genie_email
            email_sent = bool(
                sender(
                    email_html,
                    owner_subject,
                    inline_jpeg_parts=inline_parts,
                    attachment_jpeg_parts=[],
                )
            )

    meta = build_service_artifact_fields(
        run_id=child_run_id,
        mode=pid,
        program_id=pid,
        trigger_source=trigger_source,
        validation_result="pass",
        issue_codes=[],
        called_gemini=True,
        html_path=html_rel,
        owner_review_html_path=str(artifact_email_path(child_run_id)),
        smtp_attempted=smtp_attempted,
        email_sent=email_sent,
        customer_delivery_status="not_sent",
        response_status=200,
        workflow_status=str(parent.get("workflow_status") or "review_required"),
        owner_review_url=owner_review_url or None,
        artifact_storage_durable=_service_artifact_storage_durable(),
    )
    meta.update(subject_fields)
    meta.update(_dedup_artifact_fields_from_prompt_input(prompt_input))
    meta.update(visible_text_quality_fields)
    meta.update(_scope_delivery_reason_fields("body_only"))
    meta.update(
        {
            "regen_type": "body_only",
            "regen_parent_run_id": parent_run_id,
            "regen_requested_at_kst": now_kst_iso(),
            "regen_requested_by": "admin",
            "reissue_scope": "body_only",
            "reissue_scope_supported": True,
            "reissue_scope_status": "executed",
            "reissue_reason_code": reissue_reason_code or None,
            "reissue_reason_note": reissue_reason_note or None,
            "customer_approve_called": False,
            "customer_final_email_called": False,
            "source_fetch_called": False,
            "news_fetch_called": False,
            "duplicate_reselect_called": True,
            "candidate_pool_reused": True,
            "excluded_signal_ids": excluded_ids,
            "excluded_signal_fingerprints": excluded_fps_applied,
            "replacement_signal_ids": replacement_signal_ids,
            "replacement_signal_titles": replacement_signal_titles,
            "selected_signal_count_before": selected_count_before,
            "selected_signal_count_after": selected_count_after,
            "regen_source_pack_snapshot": _regen_source_pack_snapshot(parent),
            "regen_prompt_input_snapshot": prompt_input,
            "regen_generated_briefing_snapshot": generated_briefing,
            "generated_image_path": _repo_rel(top_image_path),
            "generated_image_path_watermarked": _repo_rel(top_image_path),
            "top_image_cid": top_cid,
            "owner_email_image_cids": [top_cid],
            "owner_email_subject": owner_subject,
            "owner_email_preheader": owner_preheader,
            "email_preheader": subject_fields.get("email_preheader") or owner_preheader,
        }
    )
    if pid == PROGRAM_KOREA and bottom_image_path is not None:
        bottom_token = bottom_cid or keysuri_korea_bottom_service_email_cid_token(parent_run_id)
        meta["bottom_image_cid"] = bottom_token
        meta["korea_bottom_shot_cid"] = bottom_token
        meta["korea_bottom_shot_path"] = _repo_rel(bottom_image_path)
        meta["bottom_shot_image_path"] = _repo_rel(bottom_image_path)
        meta["owner_email_image_cids"] = [top_cid, bottom_token]
    owner_email_fields = _owner_email_delivery_fields(
        smtp_attempted=smtp_attempted,
        email_sent=email_sent,
        subject=owner_subject,
    )
    meta.update(owner_email_fields)
    meta["owner_email_subject"] = owner_subject
    _maybe_write_owner_review_exposure_log(
        meta, email_sent=email_sent, exposure_kind="owner_review_reissue_body", parent=parent
    )
    save_run_artifact(meta, email_html=email_html)
    return {
        "ok": not send_owner_email or email_sent,
        "run_id": child_run_id,
        "program_id": pid,
        "regen_type": "body_only",
        "email_sent": email_sent,
        "customer_delivery_status": "not_sent",
    }


def run_keysuri_text_and_image_reissue(
    parent_run_id: str,
    *,
    parent_meta: Optional[Dict[str, Any]] = None,
    trigger_source: str = "admin_text_and_image_reissue",
    reissue_reason_code: str = "",
    reissue_reason_note: str = "",
    send_owner_email: bool = True,
    smoke_runner=None,
    image_canary_runner=None,
    bottom_generate_fn: Optional[Callable[..., Path]] = None,
    bottom_watermark_fn: Optional[Callable[[Path, Path], Path]] = None,
    send_fn: Optional[Callable[..., bool]] = None,
    image_upload_fn=None,
) -> Dict[str, Any]:
    parent = dict(parent_meta or load_run_artifact(parent_run_id, normalize=False) or {})
    pid = str(parent.get("program_id") or parent.get("mode") or "").strip()
    if pid not in _KEYSURI_PROGRAMS:
        return {"ok": False, "error": "text_and_image_reissue_unsupported_mode", "program_id": pid}

    # text_and_image: fresh source/news collection from scratch — NOT from parent snapshot
    _smoke_runner = smoke_runner or run_keysuri_live_source_smoke
    smoke: LiveSourceSmokeResult = _smoke_runner(
        program_id=pid,
        use_gemini=True,
        contract_preview=False,
        send=False,
    )
    if not smoke.ok or not smoke.called_gemini or str(smoke.parse_status or "") != "parsed_valid":
        return {
            "ok": False,
            "error": getattr(smoke, "error", None) or "text_and_image_reissue_source_collection_failed",
            "program_id": pid,
        }
    generated_briefing = smoke.generated_briefing
    if not isinstance(generated_briefing, dict):
        return {
            "ok": False,
            "error": "text_and_image_reissue_generated_briefing_missing",
            "program_id": pid,
        }
    fresh_source_pack = json.loads(Path(smoke.source_pack_path).read_text(encoding="utf-8"))
    prompt_input = build_keysuri_prompt_input(pid, fresh_source_pack)
    prompt_input["source_pack"] = fresh_source_pack
    generated_briefing = enrich_generated_briefing_content(generated_briefing, pid, prompt_input)
    generated_briefing, _visible_fresh = validate_and_repair_keysuri_visible_text_quality(
        generated_briefing,
        root_path="generated_briefing",
    )
    if _visible_fresh.get("visible_text_ellipsis_blocked"):
        return {"ok": False, "error": KEYSURI_KOREAN_CONNECTOR_ELLIPSIS_BLOCKED, "program_id": pid}

    child_run_id = generate_run_id(pid)
    subject_fields = build_keysuri_subject_artifact_fields(
        pid,
        generated_briefing=generated_briefing,
        prompt_input=prompt_input,
        run_id=child_run_id,
        trigger_source=trigger_source,
    )
    top_image_headline = str(subject_fields.get("subject_top_headline") or "")
    top_variation_fields = _keysuri_top_image_variation_fields(pid, child_run_id, top_image_headline)
    canary_fn = image_canary_runner or _generate_keysuri_service_image
    image_outcome = canary_fn(pid, run_id=child_run_id, subject_top_headline=top_image_headline)
    if not image_outcome.ok:
        return {
            "ok": False,
            "error": image_outcome.error_code or ERROR_IMAGE_GENERATION_FAILED,
            "program_id": pid,
        }
    gen_image_raw_abs = _REPO / str(image_outcome.generated_image_path or "")
    gen_image_abs = _watermarked_top_shot_path(gen_image_raw_abs)
    image_outcome.generated_image_path = _repo_rel(gen_image_abs)

    bottom_image_path: Optional[Path] = None
    bottom_image_meta: Dict[str, Any] = {}
    bottom_image_status = "not_applicable"
    bottom_image_source = ""
    issue_codes: List[str] = []
    if pid == PROGRAM_KOREA:
        bottom_image_path, bottom_issues, bottom_image_meta = resolve_korea_bottom_email_image_path(
            child_run_id,
            **_korea_bottom_weather_inputs(prompt_input),
            generate_fn=bottom_generate_fn,
            watermark_fn=bottom_watermark_fn,
        )
        if bottom_image_path is not None:
            bottom_image_status = "available"
            bottom_image_source = str(bottom_image_meta.get("bottom_shot_source") or "fixed_105936_fallback")
            if bottom_image_source == "generated_v6_multi_ref":
                bottom_image_meta.update(
                    _persist_korea_generated_images(
                        child_run_id,
                        gen_image_abs,
                        bottom_image_path,
                        upload_fn=image_upload_fn,
                    )
                )
        else:
            bottom_image_status = "placeholder"
            issue_codes.extend(bottom_issues)

    contract_fixture_preview = _build_service_contract_fixture(
        pid,
        prompt_input=prompt_input,
        generated_briefing=generated_briefing,
        generated_image_path=gen_image_abs,
        run_id=child_run_id,
        image_mode=IMAGE_MODE_PREVIEW,
        bottom_shot_image_path=bottom_image_path,
    )
    owner_preheader = subject_fields["owner_email_preheader"]
    contract_fixture_preview["selected_subject"] = subject_fields["editorial_subject"]
    contract_fixture_preview["preheader"] = owner_preheader
    preview_html = render_keysuri_contract_preview_html(
        contract_fixture_preview,
        repo_root=_REPO,
        image_mode=IMAGE_MODE_PREVIEW,
        auto_prepare=False,
    )
    out_dir = _REPO / "output" / "admin_runs" / "keysuri_service"
    out_dir.mkdir(parents=True, exist_ok=True)
    html_path = out_dir / f"{child_run_id}.html"
    html_path.write_text(preview_html, encoding="utf-8")
    html_rel = _repo_rel(html_path)

    owner_subject = _owner_subject_for_regen(parent, subject_fields["owner_email_subject"], "body_and_image")
    owner_review_url = build_owner_review_admin_url(child_run_id) or ""
    if pid == PROGRAM_GLOBAL:
        contract_fixture_email = dict(contract_fixture_preview)
        contract_fixture_email["top_shot_image_src"] = keysuri_global_service_email_cid_src(child_run_id)
        email_html = build_keysuri_global_gmail_owner_email_html(
            contract_fixture_email,
            subject=owner_subject,
            preheader=owner_preheader,
            admin_url=owner_review_url,
            run_id=child_run_id,
        )
    else:
        contract_fixture_email = dict(contract_fixture_preview)
        contract_fixture_email["top_shot_image_src"] = keysuri_korea_service_email_cid_src(child_run_id)
        if bottom_image_path is not None:
            contract_fixture_email["bottom_shot_image_src"] = keysuri_korea_bottom_service_email_cid_src(child_run_id)
        email_html = build_keysuri_korea_gmail_owner_email_html(
            contract_fixture_email,
            subject=owner_subject,
            preheader=owner_preheader,
            admin_url=owner_review_url,
            run_id=child_run_id,
        )

    visible_text_quality_fields = merge_visible_text_quality_fields(
        validate_keysuri_html_visible_text_quality(preview_html, path="owner_preview_html.visible_text"),
        validate_keysuri_html_visible_text_quality(email_html, path="owner_email_html.visible_text"),
    )
    if visible_text_quality_fields.get("visible_text_ellipsis_blocked"):
        return {"ok": False, "error": KEYSURI_KOREAN_CONNECTOR_ELLIPSIS_BLOCKED, "program_id": pid}

    smtp_attempted = False
    email_sent = False
    if send_owner_email:
        if os.getenv("GENIE_OWNER_REVIEW_SEND", "").strip() not in ("1", "true", "yes"):
            pass
        else:
            smtp_attempted = True
            sender = send_fn or send_genie_email
            os.environ.setdefault("GENIE_EMAIL_RICH_MODE", "1")
            if pid == PROGRAM_GLOBAL:
                inline_parts = inline_jpeg_parts_for_global_service_email(gen_image_abs, child_run_id)
            else:
                inline_parts = inline_jpeg_parts_for_korea_service_email(
                    gen_image_abs,
                    child_run_id,
                    bottom_image_path=bottom_image_path,
                )
            email_sent = bool(
                sender(
                    email_html,
                    owner_subject,
                    inline_jpeg_parts=inline_parts,
                    attachment_jpeg_parts=[],
                )
            )

    meta = build_service_artifact_fields(
        run_id=child_run_id,
        mode=pid,
        program_id=pid,
        trigger_source=trigger_source,
        validation_result="pass",
        issue_codes=issue_codes,
        called_gemini=True,
        image_outcome=image_outcome,
        html_path=html_rel,
        owner_review_html_path=str(artifact_email_path(child_run_id)),
        smtp_attempted=smtp_attempted,
        email_sent=email_sent,
        customer_delivery_status="not_sent",
        response_status=200,
        workflow_status=str(parent.get("workflow_status") or "review_required"),
        owner_review_url=owner_review_url or None,
        artifact_storage_durable=_service_artifact_storage_durable(),
    )
    meta.update(subject_fields)
    meta.update(_dedup_artifact_fields_from_prompt_input(prompt_input))
    meta.update(visible_text_quality_fields)
    meta.update(_scope_delivery_reason_fields("body_and_image"))
    meta.update(
        {
            "regen_type": "body_and_image",
            "regen_parent_run_id": parent_run_id,
            "regen_requested_at_kst": now_kst_iso(),
            "regen_requested_by": "admin",
            "reissue_scope": "body_and_image",
            "reissue_scope_supported": True,
            "reissue_scope_status": "executed",
            "reissue_reason_code": reissue_reason_code or None,
            "reissue_reason_note": reissue_reason_note or None,
            "customer_approve_called": False,
            "customer_final_email_called": False,
            "source_fetch_called": True,
            "news_fetch_called": True,
            "candidate_pool_refreshed": True,
            "selected_signals_refreshed": True,
            "regen_source_pack_snapshot": fresh_source_pack,
            "regen_prompt_input_snapshot": prompt_input,
            "regen_generated_briefing_snapshot": generated_briefing,
            "generated_image_path_raw": str(gen_image_raw_abs.relative_to(_REPO)),
            "generated_image_path_watermarked": _repo_rel(gen_image_abs),
            "top_shot_watermark_status": "applied",
            "top_shot_watermark_text": "MirAI:ON",
            "owner_email_subject": owner_subject,
            "owner_email_preheader": owner_preheader,
            "email_preheader": subject_fields.get("email_preheader") or owner_preheader,
        }
    )
    if top_variation_fields:
        meta.update(top_variation_fields)
    if pid == PROGRAM_KOREA:
        meta.update(bottom_image_meta)
        meta["korea_bottom_shot_status"] = bottom_image_status
        if bottom_image_source:
            meta["korea_bottom_shot_source"] = bottom_image_source
    owner_email_fields = _owner_email_delivery_fields(
        smtp_attempted=smtp_attempted,
        email_sent=email_sent,
        subject=owner_subject,
    )
    meta.update(owner_email_fields)
    meta["owner_email_subject"] = owner_subject
    _maybe_write_owner_review_exposure_log(
        meta, email_sent=email_sent, exposure_kind="owner_review_reissue_body_and_image", parent=parent
    )
    save_run_artifact(meta, email_html=email_html)
    return {
        "ok": image_outcome.ok and (not send_owner_email or email_sent),
        "run_id": child_run_id,
        "program_id": pid,
        "regen_type": "body_and_image",
        "email_sent": email_sent,
        "customer_delivery_status": "not_sent",
    }


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

    top_image_headline = _safe_keysuri_top_headline(smoke, pid)
    top_image_variation_fields = _keysuri_top_image_variation_fields(
        pid, run_id, top_image_headline
    )
    canary_fn = image_canary_runner or _generate_keysuri_service_image
    try:
        image_outcome = canary_fn(
            pid, run_id=run_id, subject_top_headline=top_image_headline
        )
    except TypeError:
        # Backward-compatible with a pid-only injected image_canary_runner.
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
        if top_image_variation_fields:
            meta.update(top_image_variation_fields)
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
    meta.update(_dedup_artifact_fields_from_prompt_input(prompt_input))
    meta.update(visible_text_quality_fields)
    meta["owner_email_subject"] = subject
    _log_owner_email_delivery_event(program_id=pid, run_id=run_id, fields=owner_email_fields)
    meta["artifact_status"] = "emailed" if email_sent else "stored"
    _maybe_write_owner_review_exposure_log(meta, email_sent=email_sent, exposure_kind="owner_review_email")
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
    if top_image_variation_fields:
        meta.update(top_image_variation_fields)
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
    meta["regen_source_pack_snapshot"] = copy.deepcopy(source_pack)
    meta["regen_prompt_input_snapshot"] = copy.deepcopy(prompt_input)
    meta["regen_generated_briefing_snapshot"] = copy.deepcopy(generated_briefing)
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
