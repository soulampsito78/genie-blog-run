"""Kee-Suri manual image API controlled canary (default blocked — at most one call per run)."""
from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from zoneinfo import ZoneInfo

from keysuri_image_api_gate import (
    GATE_REPORT_TYPE,
    build_keysuri_image_api_gate_report_from_canary_lock,
)
from keysuri_image_provider_contract import (
    CANARY_PROGRAMS,
    DEFAULT_VERTEX_IMAGE_MODEL,
    DEFAULT_VERTEX_LOCATION,
    OUTPUT_IMAGES_DIR,
    SIDE_EFFECTS_TEMPLATE,
    program_id_is_allowed,
    program_id_is_forbidden,
    resolve_keysuri_reference_asset_path,
    validate_keysuri_image_output_path,
)

REPORT_TYPE = "keysuri_image_api_manual_canary_report"
DEFAULT_LOCK_PATH = "ops/feeds/genie_weather_live_canary_lock_2026-06-04.sample.json"
DEFAULT_OUTPUT_DIR = OUTPUT_IMAGES_DIR
DEFAULT_OUTPUT_REPORT = f"{OUTPUT_IMAGES_DIR}keysuri_image_api_canary_report.json"

CANARY_PROVIDER_VERTEX = "vertex_image"
CANARY_PROVIDER_PENDING = "manual_provider_pending"

FORBIDDEN_REPORT_TERMS = (
    "today_geenee",
    "tomorrow_geenee",
    "tomorrow_genie",
    "Tomorrow_Geenee",
    "테크 앵커",
    "뉴스 앵커",
)

FORBIDDEN_SECRET_SUBSTRINGS = (
    "raw_provider_payload",
    "appid=",
    "Authorization:",
    "Bearer ",
    "WEATHER_API_KEY=",
    "OPENWEATHER_API_KEY=",
    "WEATHERAPI_API_KEY=",
    "data:image",
    "base64,",
)


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


def parse_bool_manual_approval(value: str | bool | None) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def build_keysuri_image_canary_runtime_config_from_env(
    program_id: str | None = None,
    manual_approval: bool | None = None,
) -> dict:
    """Build runtime config from env without exposing secrets."""
    pid = (program_id or os.getenv("GENIE_KEYSURI_IMAGE_CANARY_PROGRAM") or "").strip()
    approval = (
        manual_approval
        if manual_approval is not None
        else parse_bool_manual_approval(os.getenv("GENIE_KEYSURI_IMAGE_MANUAL_APPROVAL"))
    )
    project = (os.getenv("GENIE_VERTEX_PROJECT_ID") or os.getenv("GOOGLE_CLOUD_PROJECT") or "").strip()
    location = (os.getenv("VERTEX_LOCATION") or DEFAULT_VERTEX_LOCATION).strip()
    model = (os.getenv("VERTEX_IMAGE_MODEL") or DEFAULT_VERTEX_IMAGE_MODEL).strip()
    issues: List[dict] = []

    env_ready = bool(project)
    if not env_ready:
        issues.append(
            _issue(
                "project_env_missing",
                "GENIE_VERTEX_PROJECT_ID or GOOGLE_CLOUD_PROJECT required for image canary call",
                "env",
            )
        )

    return {
        "program_id": pid or None,
        "manual_approval_present": approval,
        "project_id_present": bool(project),
        "vertex_location": location,
        "vertex_image_model": model,
        "env_ready_for_call": env_ready,
        "provider": CANARY_PROVIDER_VERTEX if env_ready else CANARY_PROVIDER_PENDING,
        "issues": issues,
    }


def _side_effects(**overrides: bool) -> Dict[str, bool]:
    side = dict(SIDE_EFFECTS_TEMPLATE)
    side.update(overrides)
    return side


def _base_report(
    *,
    canary_status: str,
    program_id: str | None,
    manual_approval_present: bool,
    dry_run: bool,
    provider: str,
    request_count: int = 0,
    image_api_call_status: str = "not_called",
    image_generation_status: str = "not_generated",
    output_image_path: str | None = None,
    reference_asset: str | None = None,
    prompt_source: dict | None = None,
    side_effects: dict | None = None,
    issues: List[dict] | None = None,
    output_report_path: str = DEFAULT_OUTPUT_REPORT,
    wardrobe_date_kst: str | None = None,
    wardrobe_profile_id: str | None = None,
    daily_wardrobe_seed: str | None = None,
    wardrobe_prompt_injected: bool = False,
) -> dict:
    return {
        "report_type": REPORT_TYPE,
        "canary_status": canary_status,
        "provider": provider,
        "program_id": program_id,
        "request_count": request_count,
        "one_program_per_run": True,
        "manual_approval_required": True,
        "manual_approval_present": manual_approval_present,
        "dry_run": dry_run,
        "image_api_call_status": image_api_call_status,
        "image_generation_status": image_generation_status,
        "output_image_path": output_image_path,
        "output_report_path": output_report_path,
        "reference_asset": reference_asset,
        "prompt_source": prompt_source,
        "wardrobe_date_kst": wardrobe_date_kst,
        "wardrobe_profile_id": wardrobe_profile_id,
        "daily_wardrobe_seed": daily_wardrobe_seed,
        "wardrobe_prompt_injected": wardrobe_prompt_injected,
        "today_geenee_in_canary": False,
        "tomorrow_geenee_in_canary": False,
        "secrets_exposed": False,
        "raw_provider_payload_saved": False,
        "ready_for_scheduler": False,
        "ready_for_production_auto_call": False,
        "runtime_wiring": "none",
        "side_effects": side_effects or _side_effects(),
        "issues": issues or [],
    }


def _wardrobe_metadata_from_prompt_source(prompt_source: dict | None) -> dict:
    if not isinstance(prompt_source, dict):
        return {
            "wardrobe_date_kst": None,
            "wardrobe_profile_id": None,
            "daily_wardrobe_seed": None,
            "wardrobe_prompt_injected": False,
        }
    return {
        "wardrobe_date_kst": prompt_source.get("wardrobe_date_kst"),
        "wardrobe_profile_id": prompt_source.get("wardrobe_profile_id"),
        "daily_wardrobe_seed": prompt_source.get("daily_wardrobe_seed"),
        "wardrobe_prompt_injected": bool(prompt_source.get("wardrobe_prompt_injected")),
    }


def _validate_prompt_source_override(prompt_source: dict) -> List[dict]:
    issues: List[dict] = []
    if not isinstance(prompt_source, dict):
        issues.append(_issue("prompt_source_override_invalid", "must be a dict", "prompt_source_override"))
        return issues
    if not str(prompt_source.get("positive_prompt") or "").strip():
        issues.append(
            _issue(
                "prompt_source_override_missing_positive",
                "positive_prompt is required",
                "prompt_source_override.positive_prompt",
            )
        )
    if not str(prompt_source.get("negative_prompt") or "").strip():
        issues.append(
            _issue(
                "prompt_source_override_missing_negative",
                "negative_prompt is required",
                "prompt_source_override.negative_prompt",
            )
        )
    override_pid = str(prompt_source.get("program_id") or "").strip()
    if override_pid and not program_id_is_allowed(override_pid):
        issues.append(
            _issue(
                "prompt_source_override_invalid_program",
                f"invalid program_id {override_pid!r}",
                "prompt_source_override.program_id",
            )
        )
    return issues


def _normalize_program_arg(program_id: str | None) -> tuple[str | None, List[dict]]:
    issues: List[dict] = []
    if program_id is None:
        return None, issues
    raw = str(program_id).strip()
    if not raw:
        return None, issues
    if "," in raw or ";" in raw or " " in raw:
        issues.append(
            _issue(
                "multiple_programs_rejected",
                "exactly one program per run; multiple selection is not allowed",
                "program_id",
            )
        )
        return raw.split(",")[0].strip(), issues
    return raw, issues


def _gate_prompt_source(
    lock_path: str,
    program_id: str,
    manual_approval_for_gate: bool,
    *,
    run_date_kst: str | None = None,
    subject_top_headline: str = "",
) -> tuple[dict | None, List[dict], bool]:
    """Return prompt_source, issues, gate_ready.

    The gate report itself (identity / safety / secret validation) is unchanged and
    still governs go/no-go. When ``run_date_kst`` is provided, the returned
    positive/negative prompt is the diversified production top image prompt
    (deterministic per program/date/headline) instead of the static design snapshot.
    """
    issues: List[dict] = []
    try:
        gate_report = build_keysuri_image_api_gate_report_from_canary_lock(
            lock_path,
            manual_approval=manual_approval_for_gate,
        )
    except Exception as exc:  # noqa: BLE001 — surface as gate issue
        issues.append(
            _issue("gate_build_failed", str(exc), "gate_report")
        )
        return None, issues, False

    if gate_report.get("report_status") != "pass":
        issues.append(
            _issue(
                "gate_report_not_pass",
                "image API gate report must pass before canary call",
                "gate_report",
            )
        )
        return None, issues, False

    entries = gate_report.get("gate_entries") or {}
    entry = entries.get(program_id)
    if not isinstance(entry, dict):
        issues.append(
            _issue("gate_entry_missing", f"gate entry missing for {program_id!r}", "gate_entries")
        )
        return None, issues, False

    if not entry.get("validation_passed"):
        issues.append(
            _issue(
                "gate_validation_failed",
                "gate entry validation_passed must be true",
                f"gate_entries.{program_id}",
            )
        )
        return None, issues, False

    snap = entry.get("prompt_contract_snapshot") or {}
    prompt_source = {
        "source_gate_report_type": GATE_REPORT_TYPE,
        "program_id": program_id,
        "positive_prompt": str(snap.get("positive_prompt") or ""),
        "negative_prompt": str(snap.get("negative_prompt") or ""),
    }

    if run_date_kst:
        try:
            from keysuri_weather_visual_prompt_integration import (
                build_keysuri_production_top_image_prompt,
            )

            diversified = build_keysuri_production_top_image_prompt(
                program_id,
                run_date_kst=run_date_kst,
                subject_top_headline=subject_top_headline,
            )
            prompt_source["positive_prompt"] = diversified["positive_prompt"]
            prompt_source["negative_prompt"] = diversified["negative_prompt"]
            prompt_source["top_image_variation"] = diversified["variation"]
            prompt_source["prompt_diversified"] = True
            # The FINAL diversified prompt — the one actually sent to the image
            # API — must itself pass the safety validation, not just the static
            # design snapshot the gate report already checked.
            final_status = diversified["final_prompt_validation_status"]
            final_issues = diversified["final_prompt_validation_issues"]
            prompt_source["final_prompt_validated"] = True
            prompt_source["final_prompt_validation_status"] = final_status
            prompt_source["final_prompt_validation_issues"] = final_issues
            if final_status != "pass":
                for fi in final_issues:
                    issues.append(fi)
                # Final prompt failed safety validation -> gate is NOT ready.
                return prompt_source, issues, False
        except Exception as exc:  # noqa: BLE001 — fail closed on builder error
            issues.append(
                _issue(
                    "diversified_prompt_build_failed",
                    str(exc),
                    "top_image_variation",
                )
            )
            prompt_source["final_prompt_validated"] = True
            prompt_source["final_prompt_validation_status"] = "block"
            prompt_source["final_prompt_validation_issues"] = [
                {"code": "diversified_prompt_build_failed", "message": str(exc)}
            ]
            return prompt_source, issues, False

    return prompt_source, issues, True


def build_keysuri_image_api_canary_report(
    *,
    program_id: str | None = None,
    manual_approval: bool = False,
    dry_run: bool = False,
    reference_asset: str | None = None,
    output_dir: str = DEFAULT_OUTPUT_DIR,
    lock_path: str = DEFAULT_LOCK_PATH,
    prompt_source_override: dict | None = None,
    _generate_image_fn: Callable[..., Path] | None = None,
) -> dict:
    """Build manual image API canary report (may perform one mocked/real generation)."""
    return run_keysuri_image_api_canary(
        program_id=program_id,
        manual_approval=manual_approval,
        dry_run=dry_run,
        reference_asset=reference_asset,
        output_dir=output_dir,
        lock_path=lock_path,
        prompt_source_override=prompt_source_override,
        _generate_image_fn=_generate_image_fn,
    )


def run_keysuri_image_api_canary(
    program_id: str | None = None,
    manual_approval: bool = False,
    dry_run: bool = False,
    reference_asset: str | None = None,
    output_dir: str = DEFAULT_OUTPUT_DIR,
    lock_path: str = DEFAULT_LOCK_PATH,
    prompt_source_override: dict | None = None,
    _generate_image_fn: Callable[..., Path] | None = None,
) -> dict:
    """Run Kee-Suri manual image API canary with default blocked/no-call path."""
    path_issues = validate_keysuri_image_output_path(output_dir)
    if path_issues:
        return _base_report(
            canary_status="blocked_invalid_output_dir",
            program_id=None,
            manual_approval_present=bool(manual_approval),
            dry_run=dry_run,
            provider=CANARY_PROVIDER_PENDING,
            issues=path_issues,
        )

    normalized_out = str(output_dir).strip().replace("\\", "/").rstrip("/") + "/"
    manual_present = parse_bool_manual_approval(manual_approval) or parse_bool_manual_approval(
        os.getenv("GENIE_KEYSURI_IMAGE_MANUAL_APPROVAL")
    )

    pid, multi_issues = _normalize_program_arg(program_id)
    if pid is None:
        pid, _ = _normalize_program_arg(os.getenv("GENIE_KEYSURI_IMAGE_CANARY_PROGRAM"))

    all_issues: List[dict] = list(multi_issues)
    if any(i.get("code") == "multiple_programs_rejected" for i in multi_issues):
        return _base_report(
            canary_status="blocked_invalid_program",
            program_id=pid,
            manual_approval_present=manual_present,
            dry_run=dry_run,
            provider=CANARY_PROVIDER_PENDING,
            issues=all_issues,
        )

    runtime = build_keysuri_image_canary_runtime_config_from_env(program_id=pid, manual_approval=manual_present)
    provider = str(runtime.get("provider") or CANARY_PROVIDER_PENDING)
    if not manual_present:
        return _base_report(
            canary_status="blocked_no_manual_approval",
            program_id=pid,
            manual_approval_present=False,
            dry_run=dry_run,
            provider=provider,
            issues=all_issues,
        )

    if not pid:
        return _base_report(
            canary_status="blocked_missing_program",
            program_id=None,
            manual_approval_present=True,
            dry_run=dry_run,
            provider=provider,
            issues=all_issues,
        )

    if program_id_is_forbidden(pid):
        return _base_report(
            canary_status="blocked_forbidden_program",
            program_id=pid,
            manual_approval_present=True,
            dry_run=dry_run,
            provider=provider,
            issues=all_issues,
        )

    if not program_id_is_allowed(pid):
        return _base_report(
            canary_status="blocked_invalid_program",
            program_id=pid,
            manual_approval_present=True,
            dry_run=dry_run,
            provider=provider,
            issues=all_issues,
        )

    ref_path, ref_issues = resolve_keysuri_reference_asset_path(reference_asset)
    all_issues.extend(ref_issues)
    repo_root = Path(__file__).resolve().parent
    ref_abs = repo_root / ref_path
    if ref_issues or not ref_abs.is_file():
        return _base_report(
            canary_status="blocked_missing_reference_asset",
            program_id=pid,
            manual_approval_present=True,
            dry_run=dry_run,
            provider=provider,
            reference_asset=ref_path,
            issues=all_issues + (
                []
                if ref_abs.is_file()
                else [_issue("reference_file_missing", f"reference asset not found: {ref_path}", "reference_asset")]
            ),
        )

    if prompt_source_override is not None:
        override_issues = _validate_prompt_source_override(prompt_source_override)
        all_issues.extend(override_issues)
        if override_issues:
            return _base_report(
                canary_status="blocked_invalid_prompt_source_override",
                program_id=pid,
                manual_approval_present=True,
                dry_run=dry_run,
                provider=provider,
                reference_asset=ref_path,
                prompt_source=dict(prompt_source_override),
                issues=all_issues,
                **_wardrobe_metadata_from_prompt_source(prompt_source_override),
            )
        prompt_source = dict(prompt_source_override)
        override_pid = str(prompt_source.get("program_id") or "").strip()
        if override_pid and override_pid != pid:
            all_issues.append(
                _issue(
                    "prompt_source_program_mismatch",
                    "prompt_source_override.program_id must match run program_id",
                    "prompt_source_override.program_id",
                )
            )
            return _base_report(
                canary_status="blocked_invalid_prompt_source_override",
                program_id=pid,
                manual_approval_present=True,
                dry_run=dry_run,
                provider=provider,
                reference_asset=ref_path,
                prompt_source=prompt_source,
                issues=all_issues,
                **_wardrobe_metadata_from_prompt_source(prompt_source),
            )
        gate_ready = True
    else:
        prompt_source, gate_issues, gate_ready = _gate_prompt_source(
            lock_path,
            pid,
            manual_approval_for_gate=True,
        )
        all_issues.extend(gate_issues)
        if not gate_ready or prompt_source is None:
            return _base_report(
                canary_status="blocked_gate_not_ready",
                program_id=pid,
                manual_approval_present=True,
                dry_run=dry_run,
                provider=provider,
                reference_asset=ref_path,
                prompt_source=prompt_source,
                issues=all_issues,
            )

    wardrobe_meta = _wardrobe_metadata_from_prompt_source(prompt_source)

    if not runtime.get("env_ready_for_call"):
        all_issues.extend(runtime.get("issues") or [])
        return _base_report(
            canary_status="blocked_missing_image_env",
            program_id=pid,
            manual_approval_present=True,
            dry_run=dry_run,
            provider=CANARY_PROVIDER_PENDING,
            reference_asset=ref_path,
            prompt_source=prompt_source,
            issues=all_issues,
            **wardrobe_meta,
        )

    if dry_run:
        return _base_report(
            canary_status="dry_run_ready",
            program_id=pid,
            manual_approval_present=True,
            dry_run=True,
            provider=CANARY_PROVIDER_VERTEX,
            reference_asset=ref_path,
            prompt_source=prompt_source,
            issues=all_issues,
            **wardrobe_meta,
        )

    now = datetime.now(ZoneInfo("Asia/Seoul"))
    slug = "global" if pid == "keysuri_global_tech" else "korea"
    out_name = f"keysuri_{slug}_canary_{now.strftime('%Y%m%d_%H%M%S')}.jpg"
    output_image_path = f"{normalized_out}{out_name}"
    path_check = validate_keysuri_image_output_path(output_image_path)
    if path_check:
        return _base_report(
            canary_status="blocked_invalid_output_dir",
            program_id=pid,
            manual_approval_present=True,
            dry_run=False,
            provider=provider,
            reference_asset=ref_path,
            prompt_source=prompt_source,
            issues=all_issues + path_check,
        )

    out_abs = repo_root / output_image_path
    positive = prompt_source.get("positive_prompt") or ""
    negative = prompt_source.get("negative_prompt") or ""
    full_prompt = f"{positive}\n\nNEGATIVE:\n{negative}"

    generate_fn = _generate_image_fn
    if generate_fn is None:
        from image_generator import generate_image_file as generate_fn  # noqa: PLC0415

    project = (os.getenv("GENIE_VERTEX_PROJECT_ID") or os.getenv("GOOGLE_CLOUD_PROJECT") or "").strip()
    try:
        generate_fn(
            prompt=full_prompt,
            output_path=out_abs,
            model_name=str(runtime.get("vertex_image_model") or DEFAULT_VERTEX_IMAGE_MODEL),
            reference_image_path=ref_abs,
            project_id=project or None,
            location=str(runtime.get("vertex_location") or DEFAULT_VERTEX_LOCATION),
        )
        return _base_report(
            canary_status="called_once",
            program_id=pid,
            manual_approval_present=True,
            dry_run=False,
            provider=CANARY_PROVIDER_VERTEX,
            request_count=1,
            image_api_call_status="called_once",
            image_generation_status="generated",
            output_image_path=output_image_path,
            reference_asset=ref_path,
            prompt_source=prompt_source,
            side_effects=_side_effects(
                called_gemini=True,
                called_image_api=True,
                generated_image=True,
            ),
            issues=all_issues,
            **wardrobe_meta,
        )
    except Exception as exc:  # noqa: BLE001 — canary error surface
        all_issues.append(_issue("image_generation_failed", str(exc), "generate"))
        return _base_report(
            canary_status="api_error",
            program_id=pid,
            manual_approval_present=True,
            dry_run=False,
            provider=CANARY_PROVIDER_VERTEX,
            request_count=1,
            image_api_call_status="called_once",
            image_generation_status="not_generated",
            output_image_path=None,
            reference_asset=ref_path,
            prompt_source=prompt_source,
            side_effects=_side_effects(called_gemini=True, called_image_api=True),
            issues=all_issues,
            **wardrobe_meta,
        )


def _validate_structural_product_fields(report: dict) -> None:
    """Reject forbidden products in structural fields (not prompt negative rules)."""
    pid = report.get("program_id")
    if pid is not None and program_id_is_forbidden(str(pid)):
        raise ValueError(f"Canary report program_id is forbidden: {pid!r}")
    if report.get("today_geenee_in_canary") is True:
        raise ValueError("today_geenee_in_canary must be false")
    if report.get("tomorrow_geenee_in_canary") is True:
        raise ValueError("tomorrow_geenee_in_canary must be false")


def sanitize_keysuri_image_api_canary_report(report: dict) -> dict:
    """Return JSON-safe canary report without secrets or raw payloads."""
    out = json.loads(json.dumps(report, default=str))
    for key in list(out.keys()):
        if key in ("raw_provider_payload", "_api_key") or key.endswith("_api_key"):
            out.pop(key, None)
    _validate_structural_product_fields(out)
    texts: List[str] = []
    _collect_strings(out, texts)
    blob = "\n".join(texts)
    for term in FORBIDDEN_REPORT_TERMS:
        if term in ("today_geenee", "tomorrow_geenee", "tomorrow_genie", "Tomorrow_Geenee"):
            continue
        if term.lower() in blob.lower():
            raise ValueError(f"Canary report contains forbidden term: {term!r}")
    for sub in FORBIDDEN_SECRET_SUBSTRINGS:
        if sub.lower() in blob.lower():
            raise ValueError(f"Canary report contains forbidden substring: {sub!r}")
    return out


def validate_keysuri_image_api_canary_report(report: dict) -> List[dict]:
    """Validate manual image API canary report."""
    issues: List[dict] = []
    if not isinstance(report, dict):
        issues.append(_issue("report_invalid", "report must be a dict", "report"))
        return issues

    if report.get("report_type") != REPORT_TYPE:
        issues.append(
            _issue(
                "report_type_invalid",
                f"report_type must be {REPORT_TYPE!r}",
                "report_type",
            )
        )

    if report.get("one_program_per_run") is not True:
        issues.append(_issue("one_program_per_run_invalid", "must be true", "one_program_per_run"))

    if report.get("manual_approval_required") is not True:
        issues.append(
            _issue("manual_approval_required_invalid", "must be true", "manual_approval_required")
        )

    if report.get("today_geenee_in_canary") is not False:
        issues.append(_issue("today_geenee_invalid", "must be false", "today_geenee_in_canary"))

    if report.get("tomorrow_geenee_in_canary") is not False:
        issues.append(_issue("tomorrow_geenee_invalid", "must be false", "tomorrow_geenee_in_canary"))

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

    if report.get("runtime_wiring") != "none":
        issues.append(_issue("runtime_wiring_invalid", "must be none", "runtime_wiring"))

    if report.get("secrets_exposed") is not False:
        issues.append(_issue("secrets_exposed_invalid", "must be false", "secrets_exposed"))

    if report.get("raw_provider_payload_saved") is not False:
        issues.append(
            _issue(
                "raw_provider_payload_saved_invalid",
                "must be false",
                "raw_provider_payload_saved",
            )
        )

    req = report.get("request_count")
    if req not in (0, 1):
        issues.append(_issue("request_count_invalid", "request_count must be 0 or 1", "request_count"))
    elif isinstance(req, int) and req > 1:
        issues.append(_issue("request_count_too_high", "request_count must not exceed 1", "request_count"))

    status = report.get("canary_status")
    if status == "called_once":
        if req != 1:
            issues.append(
                _issue(
                    "request_count_called_once",
                    "request_count must be 1 when called_once",
                    "request_count",
                )
            )
        out_path = report.get("output_image_path")
        if not out_path:
            issues.append(
                _issue("output_image_path_missing", "output_image_path required for called_once", "output_image_path")
            )
        else:
            issues.extend(validate_keysuri_image_output_path(str(out_path)))

    pid = report.get("program_id")
    if pid is not None:
        if program_id_is_forbidden(str(pid)):
            issues.append(_issue("forbidden_program", f"forbidden program {pid!r}", "program_id"))
        elif not program_id_is_allowed(str(pid)):
            issues.append(_issue("invalid_program", f"invalid program {pid!r}", "program_id"))

    side = report.get("side_effects")
    if isinstance(side, dict):
        if side.get("called_weather_api") is not False:
            issues.append(
                _issue(
                    "called_weather_api_invalid",
                    "called_weather_api must remain false",
                    "side_effects.called_weather_api",
                )
            )
        for key in ("fetched_live_news", "sent_email", "published_naver", "changed_scheduler"):
            if side.get(key) is not False:
                issues.append(
                    _issue(
                        "side_effect_forbidden",
                        f"side_effects.{key} must be false",
                        f"side_effects.{key}",
                    )
                )

    blocked_statuses = (
        "blocked_no_manual_approval",
        "blocked_missing_program",
        "blocked_invalid_program",
        "blocked_forbidden_program",
        "blocked_gate_not_ready",
        "blocked_missing_image_env",
        "blocked_missing_reference_asset",
        "blocked_invalid_output_dir",
    )
    if status in blocked_statuses or status == "dry_run_ready":
        if req != 0:
            issues.append(
                _issue(
                    "request_count_blocked",
                    "request_count must be 0 for blocked/dry_run_ready",
                    "request_count",
                )
            )
        if report.get("image_api_call_status") != "not_called":
            issues.append(
                _issue(
                    "image_api_call_status_blocked",
                    "image_api_call_status must be not_called",
                    "image_api_call_status",
                )
            )
        if isinstance(side, dict) and side.get("called_image_api") is not False:
            issues.append(
                _issue(
                    "called_image_api_blocked",
                    "called_image_api must be false when blocked",
                    "side_effects.called_image_api",
                )
            )

    texts: List[str] = []
    _collect_strings(report, texts)
    blob = "\n".join(texts)
    blob_lower = blob.lower()
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
