"""Kee-Suri image provider/env contract (manual canary only — no production wiring)."""
from __future__ import annotations

import os
from typing import Dict, List

CONTRACT_TYPE = "keysuri_image_provider_env_contract"

CANARY_PROGRAMS = ("keysuri_global_tech", "keysuri_korea_tech")

FORBIDDEN_CANARY_PROGRAMS = (
    "today_geenee",
    "tomorrow_geenee",
    "tomorrow_genie",
    "Tomorrow_Geenee",
    "tomorrow",
)

CANONICAL_PROVIDER = "manual_provider_pending"
SUPPORTED_FUTURE_PROVIDERS = (
    "openai_image",
    "vertex_image",
    "other_manual_provider",
)
PROVIDER_SELECTION_STATUS = "not_selected_in_this_batch"

DEFAULT_VERTEX_LOCATION = "global"
DEFAULT_VERTEX_IMAGE_MODEL = "gemini-2.5-flash-image"

REFERENCE_ASSET_DEFAULT = "assets/keysuri/reference/image_keysuri_asset_01_main_briefing.png"
REFERENCE_ASSET_FULL_BODY = "assets/keysuri/reference/image_keysuri_asset_02_full_body.png"

OUTPUT_IMAGES_DIR = "output/keysuri_preview/image_canary/"
OUTPUT_REPORTS_DIR = "output/keysuri_preview/weather_canary/"

FORBIDDEN_OUTPUT_PREFIXES = (
    "assets/",
    "static/",
    "ops/",
)

FORBIDDEN_PATH_MARKERS = ("..", "data:image", "base64,")

FORBIDDEN_REPORT_SUBSTRINGS = (
    "raw_provider_payload",
    "appid=",
    "Authorization:",
    "Bearer ",
    "WEATHER_API_KEY=",
    "OPENWEATHER_API_KEY=",
    "WEATHERAPI_API_KEY=",
)

SENSITIVE_ENV_NAMES = (
    "GENIE_IMAGE_PROVIDER",
    "GENIE_VERTEX_PROJECT_ID",
    "GOOGLE_CLOUD_PROJECT",
    "VERTEX_LOCATION",
    "VERTEX_IMAGE_MODEL",
    "GENIE_KEYSURI_IMAGE_CANARY_PROGRAM",
    "GENIE_KEYSURI_IMAGE_MANUAL_APPROVAL",
    "GENIE_KEYSURI_IMAGE_REFERENCE_ASSET",
)

SIDE_EFFECTS_TEMPLATE: Dict[str, bool] = {
    "called_weather_api": False,
    "called_gemini": False,
    "called_image_api": False,
    "generated_image": False,
    "fetched_live_news": False,
    "sent_email": False,
    "published_naver": False,
    "changed_scheduler": False,
}


def _issue(code: str, message: str, path: str) -> Dict[str, str]:
    return {"code": code, "message": message, "path": path}


def mask_secret(value: str | None) -> str:
    """Return a safe masked representation; never return the full secret."""
    if value is None or not str(value).strip():
        return "(missing)"
    text = str(value).strip()
    if len(text) <= 4:
        return "****"
    return f"****{text[-4:]}"


def build_keysuri_image_provider_env_contract() -> dict:
    """Return static image provider/env contract for manual Kee-Suri canary."""
    return {
        "contract_type": CONTRACT_TYPE,
        "provider_policy": {
            "canonical_provider": CANONICAL_PROVIDER,
            "supported_future_providers": list(SUPPORTED_FUTURE_PROVIDERS),
            "provider_selection_status": PROVIDER_SELECTION_STATUS,
        },
        "env_policy": {
            "canonical_envs": {
                "GENIE_VERTEX_PROJECT_ID": "preferred; fallback GOOGLE_CLOUD_PROJECT",
                "VERTEX_LOCATION": f"default {DEFAULT_VERTEX_LOCATION}",
                "VERTEX_IMAGE_MODEL": f"default {DEFAULT_VERTEX_IMAGE_MODEL}",
                "GENIE_KEYSURI_IMAGE_CANARY_PROGRAM": "required when calling",
                "GENIE_KEYSURI_IMAGE_MANUAL_APPROVAL": "must be 1|true|yes to allow call",
                "GENIE_KEYSURI_IMAGE_REFERENCE_ASSET": "01 | 02 optional, default 01",
            },
            "required_for_future_manual_canary": [
                "GENIE_IMAGE_PROVIDER",
                "provider_specific_image_api_key_or_secret",
            ],
            "must_not_commit": [
                ".env",
                "API keys",
                "provider secrets",
                "generated images",
            ],
            "must_not_print": [
                "full API key",
                "provider secret",
                "base64 image data",
            ],
        },
        "reference_assets": {
            "default": REFERENCE_ASSET_DEFAULT,
            "full_body": REFERENCE_ASSET_FULL_BODY,
        },
        "output_policy": {
            "future_generated_images_dir": OUTPUT_IMAGES_DIR,
            "future_generated_reports_dir": OUTPUT_REPORTS_DIR,
            "must_remain_unstaged": True,
            "must_not_commit_images": True,
        },
        "runtime_policy": {
            "manual_only": True,
            "one_program_per_run": True,
            "default_no_call": True,
            "max_requests_per_run": 1,
            "scheduler_allowed": False,
            "production_auto_call_allowed": False,
            "runtime_wiring": "none",
        },
        "side_effects": dict(SIDE_EFFECTS_TEMPLATE),
    }


def get_keysuri_image_provider_env_summary_from_env() -> dict:
    """Summarize env presence only; never expose full secret values."""
    presence: Dict[str, str] = {}
    for name in SENSITIVE_ENV_NAMES:
        val = os.getenv(name)
        presence[name] = "set" if val and str(val).strip() else "unset"

    project = (os.getenv("GENIE_VERTEX_PROJECT_ID") or os.getenv("GOOGLE_CLOUD_PROJECT") or "").strip()
    program = (os.getenv("GENIE_KEYSURI_IMAGE_CANARY_PROGRAM") or "").strip()
    approval = (os.getenv("GENIE_KEYSURI_IMAGE_MANUAL_APPROVAL") or "").strip()

    return {
        "contract_type": CONTRACT_TYPE,
        "env_presence": presence,
        "project_id_present": bool(project),
        "project_id_masked": mask_secret(project) if project else "(missing)",
        "canary_program_env": program or None,
        "manual_approval_env_set": approval.lower() in ("1", "true", "yes") if approval else False,
        "vertex_location": (os.getenv("VERTEX_LOCATION") or DEFAULT_VERTEX_LOCATION).strip(),
        "vertex_image_model": (os.getenv("VERTEX_IMAGE_MODEL") or DEFAULT_VERTEX_IMAGE_MODEL).strip(),
        "reference_asset_env": (os.getenv("GENIE_KEYSURI_IMAGE_REFERENCE_ASSET") or "01").strip(),
        "secrets_printed": False,
    }


def validate_keysuri_image_provider_env_contract(contract: dict) -> List[dict]:
    """Validate static provider/env contract shape."""
    issues: List[dict] = []
    if not isinstance(contract, dict):
        issues.append(_issue("contract_invalid", "contract must be a dict", "contract"))
        return issues

    if contract.get("contract_type") != CONTRACT_TYPE:
        issues.append(
            _issue(
                "contract_type_invalid",
                f"contract_type must be {CONTRACT_TYPE!r}",
                "contract_type",
            )
        )

    provider_policy = contract.get("provider_policy")
    if not isinstance(provider_policy, dict):
        issues.append(_issue("provider_policy_invalid", "provider_policy must be a dict", "provider_policy"))
    else:
        if provider_policy.get("canonical_provider") != CANONICAL_PROVIDER:
            issues.append(
                _issue(
                    "canonical_provider_invalid",
                    f"canonical_provider must be {CANONICAL_PROVIDER!r}",
                    "provider_policy.canonical_provider",
                )
            )
        if provider_policy.get("provider_selection_status") != PROVIDER_SELECTION_STATUS:
            issues.append(
                _issue(
                    "provider_selection_status_invalid",
                    f"provider_selection_status must be {PROVIDER_SELECTION_STATUS!r}",
                    "provider_policy.provider_selection_status",
                )
            )

    runtime = contract.get("runtime_policy")
    if not isinstance(runtime, dict):
        issues.append(_issue("runtime_policy_invalid", "runtime_policy must be a dict", "runtime_policy"))
    else:
        for key, expected in (
            ("manual_only", True),
            ("one_program_per_run", True),
            ("default_no_call", True),
            ("max_requests_per_run", 1),
            ("scheduler_allowed", False),
            ("production_auto_call_allowed", False),
            ("runtime_wiring", "none"),
        ):
            if runtime.get(key) != expected:
                issues.append(
                    _issue(
                        "runtime_policy_field_invalid",
                        f"runtime_policy.{key} must be {expected!r}",
                        f"runtime_policy.{key}",
                    )
                )

    output_policy = contract.get("output_policy")
    if isinstance(output_policy, dict):
        if not str(output_policy.get("future_generated_images_dir") or "").startswith(OUTPUT_IMAGES_DIR):
            issues.append(
                _issue(
                    "output_images_dir_invalid",
                    f"future_generated_images_dir must start with {OUTPUT_IMAGES_DIR!r}",
                    "output_policy.future_generated_images_dir",
                )
            )
        if output_policy.get("must_not_commit_images") is not True:
            issues.append(
                _issue(
                    "must_not_commit_images_invalid",
                    "must_not_commit_images must be true",
                    "output_policy.must_not_commit_images",
                )
            )

    side = contract.get("side_effects")
    if isinstance(side, dict):
        for key, expected in SIDE_EFFECTS_TEMPLATE.items():
            if side.get(key) is not expected:
                issues.append(
                    _issue(
                        "side_effect_invalid",
                        f"side_effects.{key} must be {expected!r}",
                        f"side_effects.{key}",
                    )
                )

    return issues


def validate_keysuri_image_output_path(path: str) -> List[dict]:
    """Allow only paths under output/keysuri_preview/image_canary/."""
    issues: List[dict] = []
    if not path or not str(path).strip():
        issues.append(_issue("path_empty", "output path must not be empty", "path"))
        return issues

    normalized = str(path).strip().replace("\\", "/")
    if normalized.startswith("/"):
        issues.append(_issue("path_absolute", "absolute paths are not allowed", "path"))
        return issues

    for marker in FORBIDDEN_PATH_MARKERS:
        if marker in normalized.lower():
            issues.append(
                _issue(
                    "path_forbidden_marker",
                    f"path must not contain {marker!r}",
                    "path",
                )
            )
            return issues

    for prefix in FORBIDDEN_OUTPUT_PREFIXES:
        if normalized.startswith(prefix) or f"/{prefix}" in normalized:
            issues.append(
                _issue(
                    "path_forbidden_prefix",
                    f"path must not be under {prefix!r}",
                    "path",
                )
            )
            return issues

    if not normalized.startswith(OUTPUT_IMAGES_DIR):
        issues.append(
            _issue(
                "path_outside_image_canary_dir",
                f"path must start with {OUTPUT_IMAGES_DIR!r}",
                "path",
            )
        )

    return issues


def resolve_keysuri_reference_asset_path(reference_asset: str | None = None) -> tuple[str, List[dict]]:
    """Resolve reference asset to repo-relative path."""
    issues: List[dict] = []
    raw = (reference_asset or os.getenv("GENIE_KEYSURI_IMAGE_REFERENCE_ASSET") or "01").strip()
    if raw in ("01", "1", "default"):
        return REFERENCE_ASSET_DEFAULT, issues
    if raw in ("02", "2", "full_body"):
        return REFERENCE_ASSET_FULL_BODY, issues
    normalized = raw.replace("\\", "/")
    if normalized.startswith("assets/keysuri/reference/"):
        return normalized, issues
    issues.append(
        _issue(
            "reference_asset_invalid",
            "reference asset must be 01, 02, or under assets/keysuri/reference/",
            "reference_asset",
        )
    )
    return REFERENCE_ASSET_DEFAULT, issues


def program_id_is_forbidden(program_id: str) -> bool:
    pid = (program_id or "").strip()
    if not pid:
        return False
    lower = pid.lower()
    if lower in {p.lower() for p in FORBIDDEN_CANARY_PROGRAMS}:
        return True
    return lower in ("tomorrow_geenee", "tomorrow_genie", "tomorrow")


def program_id_is_allowed(program_id: str) -> bool:
    return (program_id or "").strip() in CANARY_PROGRAMS
