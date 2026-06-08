"""Unified Kee-Suri contract-preview validation report (three explicit gates)."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from keysuri_approved_image_assets import ImageSourceMode
from keysuri_briefing_content_quality import validate_briefing_content_gate
from keysuri_contract_preview_quality import validate_contract_preview_structural_gate
from keysuri_html_preview_validation import validate_keysuri_html_preview
from keysuri_approved_image_assets import default_top_role_for_program
from keysuri_visual_identity_quality import validate_visual_identity_gate

GateStatus = Literal["pass", "fail", "warn", "manual_review_required", "skip"]
OverallStatus = Literal["blocked", "manual_visual_review_required", "owner_visual_review_ready"]


@dataclass
class GateIssue:
    code: str
    message: str
    section: str = ""
    item_index: Optional[int] = None
    excerpt: str = ""
    severity: str = "error"

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "message": self.message,
            "section": self.section,
            "item_index": self.item_index,
            "excerpt": self.excerpt,
            "severity": self.severity,
        }


@dataclass
class GateResult:
    gate: str
    status: GateStatus
    label: str
    issues: List[GateIssue] = field(default_factory=list)
    warnings: List[GateIssue] = field(default_factory=list)
    manual_checks: List[str] = field(default_factory=list)

    @property
    def is_pass(self) -> bool:
        return self.status == "pass"

    def to_dict(self) -> dict:
        return {
            "gate": self.gate,
            "status": self.status,
            "label": self.label,
            "issues": [i.to_dict() for i in self.issues],
            "warnings": [w.to_dict() for w in self.warnings],
            "manual_checks": list(self.manual_checks),
        }


@dataclass
class KeeSuriPreviewValidationReport:
    structural_gate: GateResult
    content_briefing_gate: GateResult
    visual_identity_gate: GateResult
    overall_status: OverallStatus
    ready_for_owner_visual_review: bool
    ready_for_owner_manual_visual_inspection: bool
    ready_for_test_email: bool = False
    can_send_test_email: bool = False
    reasons: List[str] = field(default_factory=list)
    html_validator_status: str = "SKIP"
    image_manifest_path: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "structural_gate": self.structural_gate.to_dict(),
            "content_briefing_gate": self.content_briefing_gate.to_dict(),
            "visual_identity_gate": self.visual_identity_gate.to_dict(),
            "overall_status": self.overall_status,
            "ready_for_owner_visual_review": self.ready_for_owner_visual_review,
            "ready_for_owner_manual_visual_inspection": self.ready_for_owner_manual_visual_inspection,
            "ready_for_test_email": self.ready_for_test_email,
            "can_send_test_email": self.can_send_test_email,
            "reasons": list(self.reasons),
            "html_validator_status": self.html_validator_status,
            "image_manifest_path": self.image_manifest_path,
        }

    def to_json(self, *, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)


def _gate_from_structural(result) -> GateResult:
    issues = [
        GateIssue(code=i.code, message=i.message, severity=i.severity)
        for i in result.issues
    ]
    warnings = [
        GateIssue(code=w.code, message=w.message, severity=w.severity)
        for w in result.warnings
    ]
    return GateResult(
        gate="structural",
        status="pass" if result.ok else "fail",
        label="Structural / HTML quality only",
        issues=issues,
        warnings=warnings,
    )


def _gate_from_briefing(result) -> GateResult:
    issues = [
        GateIssue(
            code=i.code,
            message=i.message,
            section=i.section,
            item_index=i.item_index,
            excerpt=i.excerpt,
            severity=i.severity,
        )
        for i in result.issues
    ]
    warnings = [
        GateIssue(
            code=w.code,
            message=w.message,
            section=w.section,
            item_index=w.item_index,
            excerpt=w.excerpt,
            severity=w.severity,
        )
        for w in result.warnings
    ]
    status: GateStatus = "pass" if result.ok else "fail"
    if result.manual_review_required and result.ok:
        status = "manual_review_required"
    return GateResult(
        gate="content_briefing",
        status=status,
        label="Content briefing quality (visible Korean text)",
        issues=issues,
        warnings=warnings,
    )


def _gate_from_visual(result) -> GateResult:
    issues = [
        GateIssue(
            code=i.code,
            message=i.message,
            section=i.section,
            excerpt=i.excerpt,
            severity=i.severity,
        )
        for i in result.issues
    ]
    warnings = [
        GateIssue(
            code=w.code,
            message=w.message,
            section=w.section,
            excerpt=w.excerpt,
            severity=w.severity,
        )
        for w in result.warnings
    ]
    return GateResult(
        gate="visual_identity",
        status=result.status,
        label="Visual identity / hero image quality",
        issues=issues,
        warnings=warnings,
        manual_checks=list(result.manual_checks),
    )


def compute_overall_status(
    structural: GateResult,
    content: GateResult,
    visual: GateResult,
) -> tuple[OverallStatus, bool, bool, List[str]]:
    """Return overall_status, owner_visual_review_ready, manual_inspection, reasons."""
    reasons: List[str] = []

    if structural.status == "fail":
        reasons.append("structural_gate failed — HTML/structure blocked")
        return "blocked", False, False, reasons

    if content.status == "fail":
        reasons.append("content_briefing_gate failed — briefing text blocked")
        return "blocked", False, False, reasons

    if visual.status == "fail":
        reasons.append("visual_identity_gate failed — image identity blocked")
        return "blocked", False, False, reasons

    if visual.status == "manual_review_required":
        reasons.append(
            "visual_identity_gate is manual_review_required — "
            "image generated/watermarked/embedded but identity not machine-validated; owner approval required"
        )
        content_ok = content.status in ("pass", "warn", "manual_review_required")
        if content_ok and structural.status == "pass":
            return "manual_visual_review_required", False, True, reasons
        return "blocked", False, False, reasons

    if visual.status == "pass" and structural.status == "pass" and content.status == "pass":
        reasons.append(
            "all gates pass including visual_identity — owner_visual_review_ready "
            "(test email still requires separate CID/email gate)"
        )
        return "owner_visual_review_ready", True, True, reasons

    if content.status == "warn":
        reasons.append("content_briefing_gate has warnings — manual inspection recommended")
        return "manual_visual_review_required", False, True, reasons

    reasons.append("gate combination requires manual review")
    return "manual_visual_review_required", False, True, reasons


def validate_keysuri_contract_preview(
    html: str,
    *,
    html_path: Optional[str] = None,
    program_id: Optional[str] = None,
    image_path: Optional[str] = None,
    image_manifest_path: Optional[str] = None,
    repo_root: Optional[str | Path] = None,
    image_source_mode: Optional[ImageSourceMode] = None,
    briefing_source_metadata: Optional[dict] = None,
) -> KeeSuriPreviewValidationReport:
    """Run all three gates and produce unified readiness report."""
    html_validator_status = "SKIP"
    if html_path:
        vresult = validate_keysuri_html_preview(html_path, profile="contract_preview", program_id=program_id)
        html_validator_status = vresult.validation_status
        if not vresult.is_pass():
            structural_extra = GateResult(
                gate="structural",
                status="fail",
                label="Structural / HTML quality only",
                issues=[
                    GateIssue(
                        code=i.code,
                        message=i.message,
                        section="html_file_validator",
                    )
                    for i in vresult.issues
                ],
            )
            content = GateResult(
                gate="content_briefing",
                status="skip",
                label="Content briefing quality (visible Korean text)",
            )
            visual = validate_visual_identity_gate(
                html,
                image_path=image_path,
                manifest_path=image_manifest_path,
                repo_root=repo_root,
                program_id=program_id,
                image_source_mode=image_source_mode,
                requested_role=default_top_role_for_program(program_id or ""),
            )
            visual_gate = _gate_from_visual(visual)
            overall, ready, manual, reasons = compute_overall_status(
                structural_extra, content, visual_gate
            )
            if visual.match_reason == "approved_asset_registry_match":
                reasons.insert(
                    0,
                    f"visual_identity_gate pass via approved_asset_registry_match ({visual.approved_asset_id})",
                )
            return KeeSuriPreviewValidationReport(
                structural_gate=structural_extra,
                content_briefing_gate=content,
                visual_identity_gate=visual_gate,
                overall_status=overall,
                ready_for_owner_visual_review=ready,
                ready_for_owner_manual_visual_inspection=manual,
                reasons=reasons,
                html_validator_status=html_validator_status,
                image_manifest_path=image_manifest_path,
            )

    structural_gate = _gate_from_structural(validate_contract_preview_structural_gate(html))
    content_gate = _gate_from_briefing(
        validate_briefing_content_gate(html, source_metadata=briefing_source_metadata)
    )
    visual_result = validate_visual_identity_gate(
        html,
        image_path=image_path,
        manifest_path=image_manifest_path,
        repo_root=repo_root,
        program_id=program_id,
        image_source_mode=image_source_mode,
        requested_role=default_top_role_for_program(program_id or ""),
    )
    visual_gate = _gate_from_visual(visual_result)

    overall, ready, manual, reasons = compute_overall_status(
        structural_gate, content_gate, visual_gate
    )
    if visual_result.match_reason == "approved_asset_registry_match":
        reasons.insert(
            0,
            f"visual_identity_gate pass via approved_asset_registry_match ({visual_result.approved_asset_id})",
        )

    return KeeSuriPreviewValidationReport(
        structural_gate=structural_gate,
        content_briefing_gate=content_gate,
        visual_identity_gate=visual_gate,
        overall_status=overall,
        ready_for_owner_visual_review=ready,
        ready_for_owner_manual_visual_inspection=manual,
        reasons=reasons,
        html_validator_status=html_validator_status,
        image_manifest_path=image_manifest_path,
    )


def load_manifest(path: str | Path) -> Optional[dict]:
    p = Path(path).expanduser()
    if not p.is_file():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, OSError):
        return None
