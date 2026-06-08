"""Kee-Suri visual identity / hero image quality gate."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Literal, Optional

VisualGateStatus = Literal["pass", "fail", "manual_review_required"]

MANUAL_VISUAL_CHECKS: tuple[str, ...] = (
    "Same face as approved Kee-Suri reference (Asset 01 or operator-approved JPG)",
    "Sleek short bob hairstyle consistent with locked identity",
    "Thin elegant glasses present and consistent",
    "Professional private secretary presence — not generic office woman",
    "Not public news anchor / broadcast desk styling",
    "Not plastic/CG/anime look",
    "Hands and tablet (if present) anatomically acceptable",
    "Face size and hero dominance acceptable for email hero",
    "MirAI:ON watermark does not cover face, eyes, hands, or tablet",
)

WIDE_HERO_MIN_RATIO = 1.2
SQUARE_MAX_RATIO = 1.05


@dataclass
class VisualIdentityIssue:
    code: str
    message: str
    section: str = "visual_identity"
    excerpt: str = ""
    severity: str = "error"


@dataclass
class VisualIdentityQualityResult:
    status: VisualGateStatus
    issues: List[VisualIdentityIssue] = field(default_factory=list)
    warnings: List[VisualIdentityIssue] = field(default_factory=list)
    manual_checks: List[str] = field(default_factory=list)
    manifest_path: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.status == "pass"

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "issues": [i.__dict__ for i in self.issues],
            "warnings": [w.__dict__ for w in self.warnings],
            "manual_checks": list(self.manual_checks),
            "manifest_path": self.manifest_path,
        }


def _load_manifest(path: Optional[str]) -> Optional[dict]:
    if not path:
        return None
    p = Path(path).expanduser()
    if not p.is_file():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, OSError):
        return None


def _manifest_sidecar_for_image(image_path: Optional[str]) -> Optional[Path]:
    if not image_path:
        return None
    p = Path(image_path).expanduser()
    candidate = p.with_suffix(".manifest.json")
    if candidate.is_file():
        return candidate
    wm = p.name.replace("_mirai_on_watermarked.jpg", "_mirai_on_watermarked.manifest.json")
    alt = p.parent / wm
    if alt.is_file():
        return alt
    return None


def _aspect_ratio(width: int, height: int) -> float:
    if height <= 0:
        return 0.0
    return width / height


def _check_html_hero_css(html: str, warnings: List[VisualIdentityIssue]) -> None:
    style_match = re.search(r"<style>(.*?)</style>", html, flags=re.DOTALL | re.IGNORECASE)
    if not style_match:
        return
    style = style_match.group(1)
    style_compact = style.replace(" ", "")
    if "object-fit:cover" in style_compact and "object-fit:contain" not in style_compact:
        warnings.append(
            VisualIdentityIssue(
                "hero_crop_cover",
                "Hero CSS uses object-fit:cover — may crop face/body without explicit approval",
                section="html_hero_css",
                severity="warning",
            )
        )
    if re.search(r"transform:\s*scale", style, flags=re.IGNORECASE):
        warnings.append(
            VisualIdentityIssue(
                "hero_transform_crop",
                "Hero CSS uses transform scale — may crop hero subject",
                section="html_hero_css",
                severity="warning",
            )
        )
    if re.search(r"\.top-shot-hero\{[^}]*max-height:\s*\d+px", style):
        warnings.append(
            VisualIdentityIssue(
                "hero_max_height_crop",
                "Hero max-height may shrink subject — verify face dominance manually",
                section="html_hero_css",
                severity="warning",
            )
        )


def validate_visual_identity_gate(
    html: str,
    *,
    image_path: Optional[str] = None,
    manifest_path: Optional[str] = None,
    owner_visual_approved: bool = False,
) -> VisualIdentityQualityResult:
    """
    Visual identity gate — never PASS solely on data URI + watermark.

    Without face-recognition or owner approval, generated_test images return
    manual_review_required (not pass).
    """
    issues: List[VisualIdentityIssue] = []
    warnings: List[VisualIdentityIssue] = []

    if 'id="top-shot-image"' not in html:
        issues.append(
            VisualIdentityIssue(
                "hero_image_missing",
                "Hero image section missing from HTML",
            )
        )
        return VisualIdentityQualityResult(
            status="fail",
            issues=issues,
            manual_checks=list(MANUAL_VISUAL_CHECKS),
        )

    img_match = re.search(
        r'id="top-shot-image"[^>]*>[\s\S]*?<img[^>]+src="([^"]+)"',
        html,
        flags=re.IGNORECASE,
    )
    src = img_match.group(1) if img_match else ""
    if src.startswith("data:image/"):
        if len(src) < 500:
            warnings.append(
                VisualIdentityIssue(
                    "hero_data_uri_too_small",
                    "Embedded hero data URI suspiciously small — verify image bytes manually",
                    section="html_hero",
                    severity="warning",
                )
            )
    elif "../" in src or src.startswith("image_canary/"):
        issues.append(
            VisualIdentityIssue(
                "hero_relative_path",
                f"Hero uses fragile relative path: {src!r}",
                section="html_hero",
            )
        )

    _check_html_hero_css(html, warnings)

    resolved_manifest_path = manifest_path
    if not resolved_manifest_path and image_path:
        sidecar = _manifest_sidecar_for_image(image_path)
        if sidecar:
            resolved_manifest_path = str(sidecar)

    manifest = _load_manifest(resolved_manifest_path)
    if not manifest:
        issues.append(
            VisualIdentityIssue(
                "manifest_missing",
                "Image manifest required for visual identity gate",
                section="manifest",
            )
        )
        return VisualIdentityQualityResult(
            status="fail" if issues else "manual_review_required",
            issues=issues,
            manual_checks=list(MANUAL_VISUAL_CHECKS),
            manifest_path=resolved_manifest_path,
        )

    image_source = str(manifest.get("image_source") or "")
    image_role = str(manifest.get("image_role") or "")
    width = int(manifest.get("width") or 0)
    height = int(manifest.get("height") or 0)
    ratio = _aspect_ratio(width, height)

    if not manifest.get("overlay_applied") and manifest.get("watermark") != "MirAI:ON applied":
        issues.append(
            VisualIdentityIssue(
                "watermark_not_applied",
                "Manifest does not confirm MirAI:ON watermark applied",
                section="manifest",
            )
        )

    ref_path = manifest.get("reference_image_path")
    ref_sha = manifest.get("reference_image_sha256")
    quality_verdict = str(manifest.get("quality_verdict") or "")
    owner_review_required = manifest.get("owner_visual_review_required")
    selected_candidate = manifest.get("selected_candidate_id")
    batch_id = manifest.get("batch_id")
    candidate_id = manifest.get("candidate_id")

    if image_source == "generated_test":
        if not ref_path and not ref_sha:
            issues.append(
                VisualIdentityIssue(
                    "reference_image_missing",
                    "generated_test image has no reference_image_path/sha256 — text-only generation cannot pass identity gate",
                    section="manifest",
                )
            )
        if not batch_id and not candidate_id:
            issues.append(
                VisualIdentityIssue(
                    "single_shot_no_batch",
                    "generated_test image lacks batch_id/candidate_id — single-shot auto-embed blocked",
                    section="manifest",
                )
            )
        if not selected_candidate and not quality_verdict:
            issues.append(
                VisualIdentityIssue(
                    "candidate_gate_missing",
                    "No selected_candidate_id or quality_verdict — candidate selection gate missing",
                    section="manifest",
                )
            )
        elif quality_verdict and quality_verdict != "pass":
            issues.append(
                VisualIdentityIssue(
                    "quality_verdict_fail",
                    f"Candidate quality_verdict is {quality_verdict!r}, not pass",
                    section="manifest",
                )
            )
        if owner_review_required is True and not owner_visual_approved:
            pass
        elif not owner_visual_approved:
            warnings.append(
                VisualIdentityIssue(
                    "owner_approval_missing",
                    "generated_test image requires owner visual approval",
                    section="manifest",
                    severity="warning",
                )
            )

    elif image_source in ("approved_canary", "approved_for_preview", ""):
        review_status = str(manifest.get("review_status") or "")
        if review_status not in ("approved_for_preview", "pass_direction") and not owner_visual_approved:
            warnings.append(
                VisualIdentityIssue(
                    "review_status_pending",
                    f"Manifest review_status is {review_status!r} — manual owner review required",
                    section="manifest",
                    severity="warning",
                )
            )

    if image_role and "hero" not in image_role and image_role not in ("top_shot", "email_hero_wide_candidate"):
        warnings.append(
            VisualIdentityIssue(
                "image_role_mismatch",
                f"Unexpected image_role for hero: {image_role!r}",
                section="manifest",
                severity="warning",
            )
        )

    if width and height:
        if ratio <= SQUARE_MAX_RATIO and image_role != "top_shot_approved_square":
            issues.append(
                VisualIdentityIssue(
                    "square_hero_without_approval",
                    f"Square hero ({width}x{height}) used for wide email hero without explicit approval",
                    section="manifest",
                    excerpt=f"{width}x{height}",
                )
            )
        manifest_ratio = manifest.get("aspect_ratio")
        if manifest_ratio is None and width and height:
            warnings.append(
                VisualIdentityIssue(
                    "aspect_ratio_not_recorded",
                    "Manifest missing aspect_ratio field",
                    section="manifest",
                    severity="warning",
                )
            )

    if issues:
        return VisualIdentityQualityResult(
            status="fail",
            issues=issues,
            warnings=warnings,
            manual_checks=list(MANUAL_VISUAL_CHECKS),
            manifest_path=resolved_manifest_path,
        )

    if owner_visual_approved and quality_verdict == "pass" and ref_path:
        return VisualIdentityQualityResult(
            status="pass",
            warnings=warnings,
            manual_checks=list(MANUAL_VISUAL_CHECKS),
            manifest_path=resolved_manifest_path,
        )

    return VisualIdentityQualityResult(
        status="manual_review_required",
        warnings=warnings,
        manual_checks=list(MANUAL_VISUAL_CHECKS),
        manifest_path=resolved_manifest_path,
    )
