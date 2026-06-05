"""Kee-Suri image asset manifest writer v0 (internal QA sidecar JSON only).

Records overlay proof, integrity hashes, and review status for watermarked raster
assets. Not file-copy tracking, invisible watermarking, or Content Shield.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Union

from PIL import Image

SCHEMA_VERSION = "keysuri_image_asset_manifest_v0"
WATERMARK_TEXT = "MirAI:ON"

REVIEW_STATUS_PENDING = "pending"
REVIEW_STATUS_PASS_DIRECTION = "pass_direction"
REVIEW_STATUS_APPROVED_FOR_PREVIEW = "approved_for_preview"
REVIEW_STATUS_REJECTED = "rejected"

VALID_REVIEW_STATUSES = (
    REVIEW_STATUS_PENDING,
    REVIEW_STATUS_PASS_DIRECTION,
    REVIEW_STATUS_APPROVED_FOR_PREVIEW,
    REVIEW_STATUS_REJECTED,
)
VALID_IMAGE_ROLES = ("top_shot", "bottom_shot")
VALID_WATERMARK_POSITIONS = ("bottom_right", "bottom_left")

FORBIDDEN_LEGACY_TEXTS = (
    "Heemang",
    "Today_Geenee",
    "Tomorrow_Geenee",
)

DEFAULT_TOOL = "scripts/apply_keysuri_image_watermark.py"
DEFAULT_CREATED_BY = "local_cli"

REQUIRED_FIELDS = (
    "schema_version",
    "asset_id",
    "program_id",
    "slot",
    "image_role",
    "source_image_path",
    "watermarked_image_path",
    "generated_at",
    "watermarked_at",
    "overlay_applied",
    "watermark_text",
    "watermark_position",
    "source_sha256",
    "watermarked_sha256",
    "width",
    "height",
    "review_status",
    "review_notes",
    "prompt_profile",
    "source_generation_id",
    "created_by",
    "tool",
    "production_ready",
)

PathLike = Union[str, Path]


def _resolve_path(path: PathLike) -> Path:
    return Path(path).expanduser().resolve()


def _iso_now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _manifest_value_strings(manifest: Mapping[str, Any]) -> str:
    return " ".join(str(value) for value in manifest.values())


def calculate_sha256(path: PathLike) -> str:
    """Return lowercase SHA-256 hex digest for a file."""
    resolved = _resolve_path(path)
    if not resolved.is_file():
        raise FileNotFoundError(f"File not found: {resolved}")
    digest = hashlib.sha256()
    with resolved.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_image_dimensions(path: Path) -> tuple[int, int]:
    with Image.open(path) as image:
        width, height = image.size
    return int(width), int(height)


def _make_asset_id(image_role: str, watermarked_sha256: str) -> str:
    short_hash = watermarked_sha256[:12]
    return f"keysuri_{image_role}_{short_hash}"


def build_keysuri_image_asset_manifest(
    *,
    source_image_path: PathLike,
    watermarked_image_path: PathLike,
    program_id: str,
    slot: str,
    image_role: str,
    watermark_position: str = "bottom_right",
    review_status: str = REVIEW_STATUS_PENDING,
    review_notes: str = "",
    prompt_profile: str = "",
    source_generation_id: str | None = None,
    created_by: str = DEFAULT_CREATED_BY,
    tool: str = DEFAULT_TOOL,
    generated_at: str | None = None,
    watermarked_at: str | None = None,
    overlay_applied: bool = True,
    production_ready: bool = False,
) -> dict[str, Any]:
    """Build a v0 manifest dict for a watermarked Kee-Suri raster asset."""
    if image_role not in VALID_IMAGE_ROLES:
        raise ValueError(f"image_role must be one of {VALID_IMAGE_ROLES!r}, got {image_role!r}")
    if review_status not in VALID_REVIEW_STATUSES:
        raise ValueError(f"review_status must be one of {VALID_REVIEW_STATUSES!r}, got {review_status!r}")
    if watermark_position not in VALID_WATERMARK_POSITIONS:
        raise ValueError(
            f"watermark_position must be one of {VALID_WATERMARK_POSITIONS!r}, got {watermark_position!r}",
        )
    if production_ready:
        raise ValueError("production_ready must be false in manifest v0")
    if not overlay_applied:
        raise ValueError("overlay_applied must be true when building a watermarked asset manifest")

    source = _resolve_path(source_image_path)
    watermarked = _resolve_path(watermarked_image_path)
    if not source.is_file():
        raise FileNotFoundError(f"Source image not found: {source}")
    if not watermarked.is_file():
        raise FileNotFoundError(f"Watermarked image not found: {watermarked}")

    source_sha = calculate_sha256(source)
    watermarked_sha = calculate_sha256(watermarked)
    if source_sha == watermarked_sha:
        raise ValueError("source_sha256 and watermarked_sha256 must differ after overlay")

    width, height = _read_image_dimensions(watermarked)

    manifest: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "asset_id": _make_asset_id(image_role, watermarked_sha),
        "program_id": program_id,
        "slot": slot,
        "image_role": image_role,
        "source_image_path": str(source),
        "watermarked_image_path": str(watermarked),
        "generated_at": generated_at or _iso_now(),
        "watermarked_at": watermarked_at or _iso_now(),
        "overlay_applied": True,
        "watermark_text": WATERMARK_TEXT,
        "watermark_position": watermark_position,
        "source_sha256": source_sha,
        "watermarked_sha256": watermarked_sha,
        "width": width,
        "height": height,
        "review_status": review_status,
        "review_notes": review_notes,
        "prompt_profile": prompt_profile,
        "source_generation_id": source_generation_id,
        "created_by": created_by,
        "tool": tool,
        "production_ready": False,
    }

    joined = _manifest_value_strings(manifest)
    for forbidden in FORBIDDEN_LEGACY_TEXTS:
        if forbidden in joined:
            raise ValueError(f"forbidden legacy substring in manifest values: {forbidden!r}")

    return manifest


def _default_manifest_path(manifest: Mapping[str, Any]) -> Path:
    watermarked = _resolve_path(str(manifest["watermarked_image_path"]))
    return watermarked.with_suffix(".manifest.json")


def write_keysuri_image_asset_manifest(
    manifest_or_source_image_path: Mapping[str, Any] | PathLike,
    output_path: PathLike | None = None,
    /,
    **build_kwargs: Any,
) -> Path:
    """Write manifest JSON beside the watermarked image unless output_path is set."""
    if isinstance(manifest_or_source_image_path, Mapping):
        if build_kwargs:
            raise TypeError("build kwargs are not allowed when passing a manifest mapping")
        manifest = dict(manifest_or_source_image_path)
    else:
        manifest = build_keysuri_image_asset_manifest(
            source_image_path=manifest_or_source_image_path,
            **build_kwargs,
        )

    target = _resolve_path(output_path) if output_path is not None else _default_manifest_path(manifest)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return target.resolve()


def validate_keysuri_image_asset_manifest(manifest: Mapping[str, Any]) -> dict[str, Any]:
    """Validate manifest structure and v0 field rules."""
    issues: list[str] = []

    for field in REQUIRED_FIELDS:
        if field not in manifest:
            issues.append(f"missing required field: {field}")

    if issues:
        return {"status": "FAIL", "validation_status": "FAIL", "issues": issues}

    if manifest.get("schema_version") != SCHEMA_VERSION:
        issues.append("invalid schema_version")

    if manifest.get("overlay_applied") is not True:
        issues.append("overlay_applied must be true")

    if manifest.get("watermark_text") != WATERMARK_TEXT:
        issues.append("watermark_text must be MirAI:ON")

    if manifest.get("production_ready") is True:
        issues.append("production_ready must be false")

    review_status = manifest.get("review_status")
    if review_status not in VALID_REVIEW_STATUSES:
        issues.append("invalid review_status")

    image_role = manifest.get("image_role")
    if image_role not in VALID_IMAGE_ROLES:
        issues.append("invalid image_role")

    source_sha = str(manifest.get("source_sha256") or "")
    watermarked_sha = str(manifest.get("watermarked_sha256") or "")
    if source_sha and watermarked_sha and source_sha == watermarked_sha:
        issues.append("source_sha256 must differ from watermarked_sha256")

    joined = _manifest_value_strings(manifest)
    for forbidden in FORBIDDEN_LEGACY_TEXTS:
        if forbidden in joined:
            issues.append(f"forbidden legacy substring: {forbidden}")

    if issues:
        return {"status": "FAIL", "validation_status": "FAIL", "issues": issues}

    return {"status": "PASS", "validation_status": "PASS", "issues": []}


def is_manifest_eligible_for_preview(manifest: Mapping[str, Any]) -> bool:
    """Return True only when manifest is valid and cleared for preview handoff."""
    validation = validate_keysuri_image_asset_manifest(manifest)
    if validation.get("status") != "PASS":
        return False
    if manifest.get("overlay_applied") is not True:
        return False
    if manifest.get("watermark_text") != WATERMARK_TEXT:
        return False
    if manifest.get("production_ready") is True:
        return False
    review_status = manifest.get("review_status")
    return review_status in (REVIEW_STATUS_PASS_DIRECTION, REVIEW_STATUS_APPROVED_FOR_PREVIEW)
