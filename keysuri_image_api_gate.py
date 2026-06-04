"""Kee-Suri controlled image API readiness gate (offline — no image API calls)."""
from __future__ import annotations

import re
from typing import Any, Dict, List

from genie_runtime_weather_binding import RUNTIME_BINDING_STATUS
from keysuri_weather_visual_prompt_integration import (
    PROMPT_CONTRACT_TYPE,
    REPORT_TYPE as PROMPT_REPORT_TYPE,
    SAFETY_CONSTRAINTS,
    SIDE_EFFECTS_DISABLED,
    SOURCE_MODE,
    build_keysuri_weather_visual_prompt_report_from_canary_lock,
    validate_keysuri_weather_visual_prompt_contract,
)

GATE_TYPE = "keysuri_image_api_controlled_dry_run_gate"
GATE_REPORT_TYPE = "keysuri_image_api_controlled_dry_run_gate_report"
IMAGE_API_STATUS_NOT_CALLED = "not_called"
LOCATION = "Seoul"

KEYSURI_PROGRAMS = (
    "keysuri_global_tech",
    "keysuri_korea_tech",
)

FORBIDDEN_PROGRAMS = (
    "today_geenee",
    "tomorrow_geenee",
    "tomorrow_genie",
    "Tomorrow_Geenee",
)

FORBIDDEN_POSITIVE_IDENTITY = (
    "테크 앵커",
    "뉴스 앵커",
    "아나운서",
    "공개 방송형 앵커",
    "public news anchor",
    "broadcaster",
    "tv newsroom host",
    "weathercaster",
    "news anchor",
    "announcer",
    "weather report presenter",
)

FORBIDDEN_SECRET_SUBSTRINGS = (
    "raw_provider_payload",
    "appid=",
    "Authorization:",
    "Bearer ",
    "WEATHER_API_KEY=",
    "OPENWEATHER_API_KEY=",
    "WEATHERAPI_API_KEY=",
)

REQUIRED_SAFETY_KEYS = tuple(SAFETY_CONSTRAINTS.keys())
PERSONA_NAME = "테크 비서 키수리"
IDENTITY_ROLE = "private_tech_secretary"
WEATHER_USAGE_TYPE = "visual_realism_only"


def _issue(code: str, message: str, path: str) -> Dict[str, str]:
    return {"code": code, "message": message, "path": path}


def _collect_strings(value: Any, out: List[str]) -> None:
    if isinstance(value, str):
        out.append(value)
    elif isinstance(value, dict):
        for v in value.values():
            _collect_strings(v, out)
    elif isinstance(value, list):
        for item in value:
            _collect_strings(item, out)


def _program_is_forbidden(program_id: str) -> bool:
    pid = (program_id or "").strip()
    if not pid:
        return True
    lower = pid.lower()
    return lower in {p.lower() for p in FORBIDDEN_PROGRAMS} or lower in (
        "tomorrow_geenee",
        "tomorrow_genie",
        "tomorrow",
    )


def _validate_prompt_contract_for_gate(
    program_id: str,
    prompt_contract: dict,
) -> tuple[bool, List[str], Dict[str, bool]]:
    """Return validation_passed, blocked_reasons, check flags."""
    blocked: List[str] = []
    checks = {
        "identity_checked": False,
        "weather_usage_checked": False,
        "safety_constraints_checked": False,
        "secret_guard_checked": False,
        "retirement_guard_checked": False,
    }

    if _program_is_forbidden(program_id):
        blocked.append(f"forbidden_program:{program_id}")
        return False, blocked, checks

    if program_id not in KEYSURI_PROGRAMS:
        blocked.append(f"unknown_program:{program_id}")
        return False, blocked, checks

    if not isinstance(prompt_contract, dict):
        blocked.append("prompt_contract_invalid")
        return False, blocked, checks

    contract_issues = validate_keysuri_weather_visual_prompt_contract(prompt_contract)
    for issue in contract_issues:
        blocked.append(f"{issue['code']}:{issue['path']}")

    if str(prompt_contract.get("prompt_contract_type") or "") != PROMPT_CONTRACT_TYPE:
        blocked.append("prompt_contract_type_invalid")
    if str(prompt_contract.get("source_mode") or "") != SOURCE_MODE:
        blocked.append("source_mode_invalid")
    if prompt_contract.get("runtime_binding_status") != RUNTIME_BINDING_STATUS:
        blocked.append("runtime_binding_status_invalid")

    pos = str(prompt_contract.get("positive_prompt") or "").strip()
    neg = str(prompt_contract.get("negative_prompt") or "").strip()
    if not pos:
        blocked.append("positive_prompt_missing")
    if not neg:
        blocked.append("negative_prompt_missing")

    identity = prompt_contract.get("identity")
    if not isinstance(identity, dict):
        blocked.append("identity_missing")
    else:
        if identity.get("persona_name") == PERSONA_NAME and identity.get("role") == IDENTITY_ROLE:
            checks["identity_checked"] = True
        else:
            blocked.append("identity_invalid")
        pos_lower = pos.lower()
        for term in FORBIDDEN_POSITIVE_IDENTITY:
            if term.lower() in pos_lower:
                blocked.append(f"forbidden_identity_in_positive:{term}")
                checks["identity_checked"] = False

    usage = prompt_contract.get("weather_visual_usage")
    if isinstance(usage, dict) and usage.get("usage_type") == WEATHER_USAGE_TYPE:
        checks["weather_usage_checked"] = True
    else:
        blocked.append("weather_usage_invalid")

    safety = prompt_contract.get("safety_constraints")
    if isinstance(safety, dict) and all(safety.get(k) is True for k in REQUIRED_SAFETY_KEYS):
        checks["safety_constraints_checked"] = True
    else:
        blocked.append("safety_constraints_invalid")

    neg_lower = neg.lower()
    texts: List[str] = []
    _collect_strings(prompt_contract, texts)
    blob_lower = "\n".join(texts).lower()
    secret_ok = True
    for forbidden in FORBIDDEN_SECRET_SUBSTRINGS:
        if forbidden.lower() in blob_lower:
            blocked.append(f"forbidden_secret:{forbidden}")
            secret_ok = False
    checks["secret_guard_checked"] = secret_ok and "appid=" not in blob_lower

    retirement_ok = True
    for term in ("tomorrow_geenee", "tomorrow_genie", "tomorrow_geenee", "Tomorrow_Geenee"):
        if term.lower() in blob_lower and "no tomorrow_geenee" not in blob_lower:
            retirement_ok = False
            blocked.append(f"forbidden_retired:{term}")
    if re.search(r"\b18:00\b", blob_lower) and "no tomorrow" not in blob_lower:
        retirement_ok = False
        blocked.append("forbidden_scheduler_18_00")
    if "today_geenee" in blob_lower and "no today_geenee" not in neg_lower:
        retirement_ok = False
        blocked.append("forbidden_today_geenee")
    checks["retirement_guard_checked"] = retirement_ok

    side = prompt_contract.get("side_effects")
    if isinstance(side, dict):
        for key, expected in SIDE_EFFECTS_DISABLED.items():
            if side.get(key) is not expected:
                blocked.append(f"side_effect_invalid:{key}")

    validation_passed = len(blocked) == 0
    if validation_passed:
        checks = {k: True for k in checks}

    return validation_passed, blocked, checks


def build_keysuri_image_api_gate_entry(
    program_id: str,
    prompt_contract: dict,
    manual_approval: bool = False,
) -> dict:
    """Build controlled image API gate entry for one Kee-Suri prompt contract."""
    pid = (program_id or "").strip()
    if _program_is_forbidden(pid):
        raise ValueError(f"Forbidden program for image API gate: {program_id!r}")
    if pid not in KEYSURI_PROGRAMS:
        raise ValueError(f"Unknown program for image API gate: {program_id!r}")

    validation_passed, blocked_reasons, checks = _validate_prompt_contract_for_gate(
        program_id,
        prompt_contract,
    )

    manual_approval_present = bool(manual_approval)
    image_api_call_allowed = validation_passed and manual_approval_present
    ready_for_image_api_call = image_api_call_allowed

    return {
        "program_id": (program_id or "").strip(),
        "gate_type": GATE_TYPE,
        "prompt_contract_type": PROMPT_CONTRACT_TYPE,
        "source_mode": SOURCE_MODE,
        "runtime_binding_status": RUNTIME_BINDING_STATUS,
        "weather_condition": str(prompt_contract.get("weather_condition") or "cloudy").strip(),
        "location": LOCATION,
        "validation_passed": validation_passed,
        "identity_checked": checks["identity_checked"],
        "weather_usage_checked": checks["weather_usage_checked"],
        "safety_constraints_checked": checks["safety_constraints_checked"],
        "secret_guard_checked": checks["secret_guard_checked"],
        "retirement_guard_checked": checks["retirement_guard_checked"],
        "manual_approval_required": True,
        "manual_approval_present": manual_approval_present,
        "ready_for_image_api_call": ready_for_image_api_call,
        "image_api_call_allowed": image_api_call_allowed,
        "image_api_call_status": IMAGE_API_STATUS_NOT_CALLED,
        "blocked_reasons": blocked_reasons,
        "prompt_contract_snapshot": {
            "positive_prompt": str(prompt_contract.get("positive_prompt") or ""),
            "negative_prompt": str(prompt_contract.get("negative_prompt") or ""),
            "safety_constraints": dict(prompt_contract.get("safety_constraints") or SAFETY_CONSTRAINTS),
        },
        "side_effects": dict(SIDE_EFFECTS_DISABLED),
    }


def build_keysuri_image_api_gate_report(
    prompt_report: dict,
    manual_approval: bool = False,
) -> dict:
    """Build image API gate report from Batch 8.16 visual prompt report."""
    issues: List[dict] = []
    gate_entries: Dict[str, dict] = {}

    if str(prompt_report.get("report_type") or "") != PROMPT_REPORT_TYPE:
        issues.append(
            _issue(
                "prompt_report_type_invalid",
                f"prompt report must be {PROMPT_REPORT_TYPE!r}",
                "prompt_report",
            )
        )

    if str(prompt_report.get("report_status") or "") != "pass":
        issues.append(
            _issue(
                "prompt_report_not_pass",
                "visual prompt report must pass before image API gate",
                "prompt_report",
            )
        )

    contracts = prompt_report.get("prompt_contracts")
    if not isinstance(contracts, dict):
        issues.append(
            _issue("prompt_contracts_invalid", "prompt_contracts must be a dict", "prompt_contracts")
        )
        contracts = {}

    for forbidden in FORBIDDEN_PROGRAMS:
        if forbidden in contracts:
            issues.append(
                _issue(
                    "forbidden_program_in_prompt_report",
                    f"Must not include {forbidden!r}",
                    "prompt_contracts",
                )
            )

    for program_id in KEYSURI_PROGRAMS:
        if program_id not in contracts:
            issues.append(
                _issue(
                    "prompt_contract_missing",
                    f"prompt_contracts must include {program_id!r}",
                    "prompt_contracts",
                )
            )
        else:
            gate_entries[program_id] = build_keysuri_image_api_gate_entry(
                program_id,
                contracts[program_id],
                manual_approval=manual_approval,
            )

    manual_approval_present = bool(manual_approval)
    all_validation_passed = (
        len(gate_entries) == len(KEYSURI_PROGRAMS)
        and all(e.get("validation_passed") for e in gate_entries.values())
    )
    image_api_call_allowed = all_validation_passed and manual_approval_present
    ready_for_image_api_call = image_api_call_allowed

    report: Dict[str, Any] = {
        "report_type": GATE_REPORT_TYPE,
        "report_status": "pass",
        "source_prompt_report_type": PROMPT_REPORT_TYPE,
        "runtime_binding_status": RUNTIME_BINDING_STATUS,
        "manual_approval_required": True,
        "manual_approval_present": manual_approval_present,
        "ready_for_image_api_call": ready_for_image_api_call,
        "image_api_call_allowed": image_api_call_allowed,
        "image_api_call_status": IMAGE_API_STATUS_NOT_CALLED,
        "gate_entries": gate_entries,
        "ready_for_scheduler": False,
        "ready_for_production_auto_call": False,
        "side_effects": dict(SIDE_EFFECTS_DISABLED),
        "issues": issues,
    }

    validation_issues = validate_keysuri_image_api_gate_report(report)
    issues.extend(validation_issues)
    report["issues"] = issues
    report["report_status"] = (
        "pass"
        if not issues
        and len(gate_entries) == len(KEYSURI_PROGRAMS)
        and all_validation_passed
        else "blocked"
    )
    return report


def validate_keysuri_image_api_gate_entry(entry: dict) -> List[dict]:
    """Validate a single image API gate entry."""
    issues: List[dict] = []
    if not isinstance(entry, dict):
        issues.append(_issue("entry_invalid", "entry must be a dict", "entry"))
        return issues

    pid = str(entry.get("program_id") or "").strip()
    if pid not in KEYSURI_PROGRAMS:
        issues.append(_issue("program_id_invalid", f"program_id must be in {KEYSURI_PROGRAMS}", "program_id"))

    if entry.get("gate_type") != GATE_TYPE:
        issues.append(_issue("gate_type_invalid", f"gate_type must be {GATE_TYPE!r}", "gate_type"))

    if entry.get("image_api_call_status") != IMAGE_API_STATUS_NOT_CALLED:
        issues.append(
            _issue(
                "image_api_call_status_invalid",
                f"image_api_call_status must be {IMAGE_API_STATUS_NOT_CALLED!r}",
                "image_api_call_status",
            )
        )

    side = entry.get("side_effects")
    if isinstance(side, dict):
        if side.get("called_image_api") is not False:
            issues.append(
                _issue(
                    "called_image_api_must_be_false",
                    "called_image_api must be false in this batch",
                    "side_effects.called_image_api",
                )
            )
        for key, expected in SIDE_EFFECTS_DISABLED.items():
            if side.get(key) is not expected:
                issues.append(
                    _issue(
                        "side_effect_invalid",
                        f"side_effects.{key} must be {expected!r}",
                        f"side_effects.{key}",
                    )
                )

    if entry.get("manual_approval_required") is not True:
        issues.append(
            _issue(
                "manual_approval_required_invalid",
                "manual_approval_required must be true",
                "manual_approval_required",
            )
        )

    manual_present = entry.get("manual_approval_present")
    validation_passed = entry.get("validation_passed")
    if validation_passed is True and manual_present is False:
        if entry.get("ready_for_image_api_call") is not False:
            issues.append(
                _issue(
                    "ready_for_image_api_call_invalid",
                    "ready_for_image_api_call must be false without manual approval",
                    "ready_for_image_api_call",
                )
            )
        if entry.get("image_api_call_allowed") is not False:
            issues.append(
                _issue(
                    "image_api_call_allowed_invalid",
                    "image_api_call_allowed must be false without manual approval",
                    "image_api_call_allowed",
                )
            )

    if validation_passed is True and manual_present is True:
        if entry.get("image_api_call_allowed") is not True:
            issues.append(
                _issue(
                    "image_api_call_allowed_invalid",
                    "image_api_call_allowed must be true when validation and manual approval pass",
                    "image_api_call_allowed",
                )
            )

    snapshot = entry.get("prompt_contract_snapshot")
    if not isinstance(snapshot, dict):
        issues.append(
            _issue("snapshot_invalid", "prompt_contract_snapshot must be a dict", "prompt_contract_snapshot")
        )
    else:
        for key in ("positive_prompt", "negative_prompt", "safety_constraints"):
            if key not in snapshot:
                issues.append(
                    _issue("snapshot_missing_key", f"snapshot must include {key!r}", f"snapshot.{key}")
                )

    texts: List[str] = []
    _collect_strings(entry, texts)
    blob_lower = "\n".join(texts).lower()
    for forbidden in FORBIDDEN_SECRET_SUBSTRINGS:
        if forbidden.lower() in blob_lower:
            issues.append(
                _issue(
                    "forbidden_secret_or_payload",
                    f"Must not contain {forbidden!r}",
                    "entry",
                )
            )

    return issues


def validate_keysuri_image_api_gate_report(report: dict) -> List[dict]:
    """Validate image API gate report."""
    issues: List[dict] = []
    if not isinstance(report, dict):
        issues.append(_issue("report_invalid", "report must be a dict", "report"))
        return issues

    if report.get("report_type") != GATE_REPORT_TYPE:
        issues.append(
            _issue(
                "report_type_invalid",
                f"report_type must be {GATE_REPORT_TYPE!r}",
                "report_type",
            )
        )

    if report.get("source_prompt_report_type") != PROMPT_REPORT_TYPE:
        issues.append(
            _issue(
                "source_prompt_report_type_invalid",
                f"source_prompt_report_type must be {PROMPT_REPORT_TYPE!r}",
                "source_prompt_report_type",
            )
        )

    if report.get("runtime_binding_status") != RUNTIME_BINDING_STATUS:
        issues.append(
            _issue(
                "runtime_binding_status_invalid",
                f"runtime_binding_status must be {RUNTIME_BINDING_STATUS!r}",
                "runtime_binding_status",
            )
        )

    if report.get("image_api_call_status") != IMAGE_API_STATUS_NOT_CALLED:
        issues.append(
            _issue(
                "image_api_call_status_invalid",
                "image_api_call_status must be not_called",
                "image_api_call_status",
            )
        )

    if report.get("ready_for_scheduler") is not False:
        issues.append(_issue("ready_for_scheduler_invalid", "must be false", "ready_for_scheduler"))
    if report.get("ready_for_production_auto_call") is not False:
        issues.append(
            _issue(
                "ready_for_production_auto_call_invalid",
                "must be false",
                "ready_for_production_auto_call",
            )
        )

    side = report.get("side_effects")
    if isinstance(side, dict) and side.get("called_image_api") is not False:
        issues.append(
            _issue(
                "called_image_api_must_be_false",
                "called_image_api must be false",
                "side_effects.called_image_api",
            )
        )

    entries = report.get("gate_entries")
    if not isinstance(entries, dict):
        issues.append(_issue("gate_entries_invalid", "gate_entries must be a dict", "gate_entries"))
        return issues

    for forbidden in FORBIDDEN_PROGRAMS:
        if forbidden in entries:
            issues.append(
                _issue(
                    "forbidden_gate_entry",
                    f"Must not include gate entry for {forbidden!r}",
                    "gate_entries",
                )
            )

    for program_id in KEYSURI_PROGRAMS:
        if program_id not in entries:
            issues.append(
                _issue(
                    "gate_entry_missing",
                    f"gate_entries must include {program_id!r}",
                    "gate_entries",
                )
            )
        else:
            issues.extend(validate_keysuri_image_api_gate_entry(entries[program_id]))

    manual_present = report.get("manual_approval_present")
    if manual_present is False:
        if report.get("ready_for_image_api_call") is not False:
            issues.append(
                _issue(
                    "ready_for_image_api_call_invalid",
                    "report ready_for_image_api_call must be false without manual approval",
                    "ready_for_image_api_call",
                )
            )
        if report.get("image_api_call_allowed") is not False:
            issues.append(
                _issue(
                    "image_api_call_allowed_invalid",
                    "report image_api_call_allowed must be false without manual approval",
                    "image_api_call_allowed",
                )
            )

    texts: List[str] = []
    _collect_strings(report, texts)
    blob_lower = "\n".join(texts).lower()
    for forbidden in FORBIDDEN_SECRET_SUBSTRINGS:
        if forbidden.lower() in blob_lower:
            issues.append(
                _issue(
                    "forbidden_secret_or_payload",
                    f"Must not contain {forbidden!r}",
                    "report",
                )
            )

    return issues


def build_keysuri_image_api_gate_report_from_canary_lock(
    lock_path: str,
    manual_approval: bool = False,
) -> dict:
    """Build image API gate report from sanitized canary lock via Batch 8.16 prompts."""
    prompt_report = build_keysuri_weather_visual_prompt_report_from_canary_lock(lock_path)
    return build_keysuri_image_api_gate_report(prompt_report, manual_approval=manual_approval)
