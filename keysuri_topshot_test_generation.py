"""Kee-Suri Global Tech top-shot canary generation (manual canary only — default blocked)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo

from image_generator import generate_image_file
from keysuri_image_asset_manifest import (
    REVIEW_STATUS_PENDING,
    build_keysuri_image_asset_manifest,
    write_keysuri_image_asset_manifest,
)
from keysuri_image_overlay import apply_keysuri_mirai_on_watermark
from keysuri_image_provider_contract import (
    DEFAULT_VERTEX_IMAGE_MODEL,
    DEFAULT_VERTEX_LOCATION,
    OUTPUT_IMAGES_DIR,
    validate_keysuri_image_output_path,
)

PROGRAM_GLOBAL = "keysuri_global_tech"
SLOT_GLOBAL = "12:30"
PROMPT_PROFILE = "keysuri_global_tech_topshot_contract_preview_test_v1"

BLOCKED_MISSING_ALLOW_IMAGE_API = "missing_allow_image_api"
BLOCKED_MISSING_MANUAL_APPROVAL = "missing_manual_approval"
BLOCKED_DRY_RUN = "dry_run"

POSITIVE_PROMPT = (
    "Premium photorealistic portrait of Kee-Suri, a refined Korean female private AI tech secretary "
    "in her mid-to-late 30s, sleek short bob hair, thin elegant glasses, calm intelligent gaze, "
    "poised executive briefing posture, holding a slim tablet, elegant fitted charcoal or ivory "
    "business outfit, private executive office with dark navy and warm wood tones, premium lighting, "
    "sophisticated but professional, glamorous yet composed, direct private briefing presence, "
    "full upper body and head visible with comfortable headroom, not cropped at chin or forehead, "
    "not a news anchor, not public broadcast, not sci-fi, no text, no collage, high-end editorial realism."
)

NEGATIVE_PROMPT = (
    "news anchor, TV studio, microphone, broadcast desk, cartoon, anime, sci-fi, robot, collage, "
    "multiple people, watermark text, logo, caption, plain office worker, casual hoodie, "
    "extreme close-up face only, cropped head, tiny distant figure, low quality, blurry"
)


@dataclass
class TopshotGenerationResult:
    ok: bool
    program_id: str
    slot: str
    prompt_profile: str
    model_name: str
    dry_run: bool = True
    blocked_reason: Optional[str] = None
    image_api_called: bool = False
    source_image_path: Optional[str] = None
    watermarked_image_path: Optional[str] = None
    manifest_path: Optional[str] = None
    planned_paths: Dict[str, str] = field(default_factory=dict)
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "program_id": self.program_id,
            "slot": self.slot,
            "prompt_profile": self.prompt_profile,
            "model_name": self.model_name,
            "dry_run": self.dry_run,
            "blocked_reason": self.blocked_reason,
            "image_api_called": self.image_api_called,
            "source_image_path": self.source_image_path,
            "watermarked_image_path": self.watermarked_image_path,
            "manifest_path": self.manifest_path,
            "planned_paths": self.planned_paths,
            "error": self.error,
        }


def _output_dir(repo_root: Path) -> Path:
    return (repo_root / OUTPUT_IMAGES_DIR).resolve()


def _stamp() -> str:
    return datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y%m%d_%H%M%S")


def build_topshot_prompt() -> str:
    return f"{POSITIVE_PROMPT}\n\nNEGATIVE:\n{NEGATIVE_PROMPT}"


def build_topshot_output_paths(repo_root: Path, stamp: Optional[str] = None) -> tuple[Path, Path, Path]:
    """Return (source_jpg, watermarked_jpg, manifest_json) paths for a generation stamp."""
    token = stamp or _stamp()
    out_dir = _output_dir(repo_root)
    source = out_dir / f"keysuri_global_generated_topshot_{token}.jpg"
    watermarked = out_dir / f"keysuri_global_generated_topshot_{token}_mirai_on_watermarked.jpg"
    manifest = watermarked.with_suffix(".manifest.json")
    return source, watermarked, manifest


def _validate_canary_output_paths(repo_root: Path, *paths: Path) -> Optional[str]:
    root = repo_root.resolve()
    for path in paths:
        try:
            rel = path.resolve().relative_to(root)
        except ValueError:
            return "output path must stay under repo root"
        rel_str = str(rel).replace("\\", "/")
        issues = validate_keysuri_image_output_path(rel_str)
        if issues:
            return issues[0].get("message", "invalid output path")
    return None


def _blocked_result(
    *,
    model_name: str,
    blocked_reason: str,
    source_path: Path,
    watermarked_path: Path,
    manifest_path: Path,
    error: Optional[str] = None,
) -> TopshotGenerationResult:
    return TopshotGenerationResult(
        ok=False,
        program_id=PROGRAM_GLOBAL,
        slot=SLOT_GLOBAL,
        prompt_profile=PROMPT_PROFILE,
        model_name=model_name,
        dry_run=True,
        blocked_reason=blocked_reason,
        image_api_called=False,
        planned_paths={
            "source_image_path": str(source_path),
            "watermarked_image_path": str(watermarked_path),
            "manifest_path": str(manifest_path),
        },
        error=error,
    )


def _apply_canary_manifest_safety_fields(manifest: Dict[str, Any]) -> Dict[str, Any]:
    manifest["image_source"] = "generated_test"
    manifest["watermark"] = "MirAI:ON applied"
    manifest["intended_use"] = "contract_preview_test"
    manifest["not_customer_final"] = True
    manifest["approved_asset"] = False
    manifest["registry_promoted"] = False
    manifest["canary_only"] = True
    manifest["requires_owner_review"] = True
    return manifest


def build_topshot_dry_run_plan(
    *,
    repo_root: Path,
    model_name: Optional[str] = None,
    stamp: Optional[str] = None,
) -> TopshotGenerationResult:
    """Return planned canary output paths and prompt without calling the image API."""
    model = (model_name or os.getenv("VERTEX_IMAGE_MODEL") or DEFAULT_VERTEX_IMAGE_MODEL).strip()
    source_path, watermarked_path, manifest_path = build_topshot_output_paths(repo_root, stamp=stamp)
    dir_error = _validate_canary_output_paths(repo_root, source_path, watermarked_path, manifest_path)
    if dir_error:
        return _blocked_result(
            model_name=model,
            blocked_reason=BLOCKED_DRY_RUN,
            source_path=source_path,
            watermarked_path=watermarked_path,
            manifest_path=manifest_path,
            error=dir_error,
        )
    return TopshotGenerationResult(
        ok=True,
        program_id=PROGRAM_GLOBAL,
        slot=SLOT_GLOBAL,
        prompt_profile=PROMPT_PROFILE,
        model_name=model,
        dry_run=True,
        blocked_reason=BLOCKED_DRY_RUN,
        image_api_called=False,
        planned_paths={
            "source_image_path": str(source_path.resolve()),
            "watermarked_image_path": str(watermarked_path.resolve()),
            "manifest_path": str(manifest_path.resolve()),
            "prompt_profile": PROMPT_PROFILE,
            "prompt_preview": build_topshot_prompt()[:240] + "…",
        },
    )


def generate_keysuri_global_topshot_test(
    *,
    repo_root: Path,
    project_id: Optional[str] = None,
    model_name: Optional[str] = None,
    location: Optional[str] = None,
    reference_image_path: Optional[Path] = None,
    stamp: Optional[str] = None,
    dry_run: bool = True,
    allow_image_api: bool = False,
    manual_approval: bool = False,
) -> TopshotGenerationResult:
    """Generate, watermark, and manifest a Global Tech top-shot canary image.

  Default is dry-run / blocked. Live image API requires explicit ``allow_image_api``
  and ``manual_approval``. Never mutates the approved asset registry.
    """
    model = (model_name or os.getenv("VERTEX_IMAGE_MODEL") or DEFAULT_VERTEX_IMAGE_MODEL).strip()
    source_path, watermarked_path, manifest_path = build_topshot_output_paths(repo_root, stamp=stamp)

    if dry_run or not allow_image_api:
        reason = BLOCKED_DRY_RUN if dry_run else BLOCKED_MISSING_ALLOW_IMAGE_API
        plan = build_topshot_dry_run_plan(repo_root=repo_root, model_name=model, stamp=stamp)
        plan.blocked_reason = reason
        plan.ok = reason == BLOCKED_DRY_RUN
        if reason == BLOCKED_MISSING_ALLOW_IMAGE_API:
            plan.error = "Image API blocked — pass allow_image_api=True with manual_approval=True"
        return plan

    if not manual_approval:
        return _blocked_result(
            model_name=model,
            blocked_reason=BLOCKED_MISSING_MANUAL_APPROVAL,
            source_path=source_path,
            watermarked_path=watermarked_path,
            manifest_path=manifest_path,
            error="Image API blocked — manual_approval=True is required",
        )

    dir_error = _validate_canary_output_paths(repo_root, source_path, watermarked_path, manifest_path)
    if dir_error:
        return _blocked_result(
            model_name=model,
            blocked_reason=BLOCKED_MISSING_ALLOW_IMAGE_API,
            source_path=source_path,
            watermarked_path=watermarked_path,
            manifest_path=manifest_path,
            error=dir_error,
        )

    source_path.parent.mkdir(parents=True, exist_ok=True)
    pid = (project_id or os.getenv("GENIE_VERTEX_PROJECT_ID") or os.getenv("GOOGLE_CLOUD_PROJECT") or "").strip()
    if not pid:
        return TopshotGenerationResult(
            ok=False,
            program_id=PROGRAM_GLOBAL,
            slot=SLOT_GLOBAL,
            prompt_profile=PROMPT_PROFILE,
            model_name=model,
            dry_run=False,
            blocked_reason=BLOCKED_MISSING_ALLOW_IMAGE_API,
            image_api_called=False,
            error="GENIE_VERTEX_PROJECT_ID or GOOGLE_CLOUD_PROJECT required for image generation",
        )

    vertex_location = (location or os.getenv("VERTEX_LOCATION") or DEFAULT_VERTEX_LOCATION).strip()
    full_prompt = build_topshot_prompt()
    generated_at = datetime.now(ZoneInfo("Asia/Seoul")).isoformat(timespec="seconds")

    try:
        generate_image_file(
            prompt=full_prompt,
            output_path=source_path,
            model_name=model,
            reference_image_path=reference_image_path,
            project_id=pid,
            location=vertex_location,
        )
        apply_keysuri_mirai_on_watermark(source_path, watermarked_path)
        manifest = build_keysuri_image_asset_manifest(
            source_image_path=source_path,
            watermarked_image_path=watermarked_path,
            program_id=PROGRAM_GLOBAL,
            slot=SLOT_GLOBAL,
            image_role="top_shot",
            review_status=REVIEW_STATUS_PENDING,
            review_notes="Generated canary top-shot only — not an approved registry asset.",
            prompt_profile=PROMPT_PROFILE,
            generated_at=generated_at,
            created_by="keysuri_topshot_test_generation",
            tool="scripts/generate_keysuri_global_topshot_test.py",
        )
        _apply_canary_manifest_safety_fields(manifest)
        write_keysuri_image_asset_manifest(manifest, manifest_path)
    except Exception as exc:  # noqa: BLE001 — canary pipeline surfaces provider errors
        return TopshotGenerationResult(
            ok=False,
            program_id=PROGRAM_GLOBAL,
            slot=SLOT_GLOBAL,
            prompt_profile=PROMPT_PROFILE,
            model_name=model,
            dry_run=False,
            image_api_called=True,
            source_image_path=str(source_path) if source_path.exists() else None,
            error=str(exc),
        )

    return TopshotGenerationResult(
        ok=True,
        program_id=PROGRAM_GLOBAL,
        slot=SLOT_GLOBAL,
        prompt_profile=PROMPT_PROFILE,
        model_name=model,
        dry_run=False,
        image_api_called=True,
        source_image_path=str(source_path.resolve()),
        watermarked_image_path=str(watermarked_path.resolve()),
        manifest_path=str(manifest_path.resolve()),
    )
