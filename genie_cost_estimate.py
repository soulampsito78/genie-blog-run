"""Best-effort Genie/KeeSuri generation cost estimate (never authoritative).

Shared across KeeSuri, Today_Geenee, and Tomorrow_Geenee. NOT a billing
integration — no Cloud Billing API, no external pricing lookup, no Secret
access. Combines locally-known Gemini usage_metadata token counts with
operator-supplied unit prices (env vars) into a rough, estimate-only figure
for operational visibility (logs/response/artifact metadata). Actual billed
amounts may differ; infra costs (Cloud Run, GCS, SMTP, blog posting) are not
modeled here.
"""
from __future__ import annotations

import os
import re
from typing import Any, Dict, Mapping, Optional, Sequence

# Common env vars — checked first for every service_family.
ENV_INPUT_USD_PER_1M = "GENIE_COST_INPUT_USD_PER_1M_TOKENS"
ENV_OUTPUT_USD_PER_1M = "GENIE_COST_OUTPUT_USD_PER_1M_TOKENS"
ENV_THOUGHTS_USD_PER_1M = "GENIE_COST_THOUGHTS_USD_PER_1M_TOKENS"
ENV_IMAGE_USD_PER_IMAGE = "GENIE_COST_IMAGE_USD_PER_IMAGE"
ENV_KRW_PER_USD = "GENIE_COST_KRW_PER_USD"

# Legacy KeeSuri-only env vars — kept as a fallback for operators who already
# configured pricing before the common GENIE_COST_* names existed.
_LEGACY_KEYSURI_ENV_INPUT_USD_PER_1M = "KEYSURI_COST_INPUT_USD_PER_1M_TOKENS"
_LEGACY_KEYSURI_ENV_OUTPUT_USD_PER_1M = "KEYSURI_COST_OUTPUT_USD_PER_1M_TOKENS"
_LEGACY_KEYSURI_ENV_THOUGHTS_USD_PER_1M = "KEYSURI_COST_THOUGHTS_USD_PER_1M_TOKENS"
_LEGACY_KEYSURI_ENV_IMAGE_USD_PER_IMAGE = "KEYSURI_COST_IMAGE_USD_PER_IMAGE"
_LEGACY_KEYSURI_ENV_KRW_PER_USD = "KEYSURI_COST_KRW_PER_USD"

_PRICE_ENV_FALLBACK_CHAINS: Dict[str, Sequence[str]] = {
    "input": (ENV_INPUT_USD_PER_1M, _LEGACY_KEYSURI_ENV_INPUT_USD_PER_1M),
    "output": (ENV_OUTPUT_USD_PER_1M, _LEGACY_KEYSURI_ENV_OUTPUT_USD_PER_1M),
    "thoughts": (ENV_THOUGHTS_USD_PER_1M, _LEGACY_KEYSURI_ENV_THOUGHTS_USD_PER_1M),
    "image": (ENV_IMAGE_USD_PER_IMAGE, _LEGACY_KEYSURI_ENV_IMAGE_USD_PER_IMAGE),
    "krw_per_usd": (ENV_KRW_PER_USD, _LEGACY_KEYSURI_ENV_KRW_PER_USD),
}

_PRICE_KIND_SUFFIXES = {
    "input": "INPUT_USD_PER_1M_TOKENS",
    "output": "OUTPUT_USD_PER_1M_TOKENS",
    "thoughts": "THOUGHTS_USD_PER_1M_TOKENS",
    "image": "IMAGE_USD_PER_IMAGE",
    "krw_per_usd": "KRW_PER_USD",
}


def normalize_model_env_key(model: Optional[str]) -> Optional[str]:
    """Normalize a model id into the env-key segment used for pricing.

    Examples:
    - gemini-2.5-flash -> GEMINI_2_5_FLASH
    - gemini-3-flash-preview -> GEMINI_3_FLASH_PREVIEW
    - gemini-2.5-flash-image -> GEMINI_2_5_FLASH_IMAGE
    """
    if not model:
        return None
    normalized = re.sub(r"[^A-Za-z0-9]+", "_", str(model).strip()).strip("_").upper()
    return normalized or None


def _read_float_env(name: str) -> Optional[float]:
    raw = os.getenv(name, "").strip()
    if not raw:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _read_price(kind: str) -> Optional[float]:
    """Priority: GENIE_COST_* (common) > legacy KEYSURI_COST_* (fallback)."""
    for env_name in _PRICE_ENV_FALLBACK_CHAINS[kind]:
        value = _read_float_env(env_name)
        if value is not None:
            return value
    return None


def _service_prefix(service_family: Optional[str]) -> Optional[str]:
    if not service_family:
        return None
    prefix = re.sub(r"[^A-Za-z0-9]+", "_", str(service_family).strip()).strip("_").upper()
    return prefix or None


def _model_specific_env(kind: str, model_key: Optional[str]) -> Optional[str]:
    suffix = _PRICE_KIND_SUFFIXES[kind]
    if not model_key:
        return None
    if kind == "image":
        return f"GENIE_COST_{model_key}_USD_PER_IMAGE"
    return f"GENIE_COST_{model_key}_{suffix}"


def _service_model_specific_env(kind: str, service_family: Optional[str], model_key: Optional[str]) -> Optional[str]:
    suffix = _PRICE_KIND_SUFFIXES[kind]
    service = _service_prefix(service_family)
    if not service or not model_key:
        return None
    if kind == "image":
        return f"{service}_COST_{model_key}_USD_PER_IMAGE"
    return f"{service}_COST_{model_key}_{suffix}"


def _read_price_from_envs(env_names: Sequence[str]) -> tuple[Optional[float], Optional[str]]:
    for env_name in env_names:
        value = _read_float_env(env_name)
        if value is not None:
            return value, env_name
    return None, None


def _text_price_env_chain(
    kind: str,
    *,
    text_model_key: Optional[str],
    service_family: Optional[str],
) -> Sequence[str]:
    envs = []
    model_env = _model_specific_env(kind, text_model_key)
    service_model_env = _service_model_specific_env(kind, service_family, text_model_key)
    if model_env:
        envs.append(model_env)
    if service_model_env and service_model_env not in envs:
        envs.append(service_model_env)
    envs.extend(_PRICE_ENV_FALLBACK_CHAINS[kind])
    return tuple(envs)


def _image_requires_model_specific_price(image_model_key: Optional[str]) -> bool:
    # Gemini image models are priced with image-token semantics in the official
    # table; do not apply a generic per-image fallback unless operators set a
    # model-specific per-image env explicitly.
    return bool(image_model_key and image_model_key.startswith("GEMINI_") and image_model_key.endswith("_IMAGE"))


def _image_price_env_chain(
    *,
    image_model_key: Optional[str],
    service_family: Optional[str],
) -> Sequence[str]:
    envs = []
    model_env = _model_specific_env("image", image_model_key)
    service_model_env = _service_model_specific_env("image", service_family, image_model_key)
    if model_env:
        envs.append(model_env)
    if service_model_env and service_model_env not in envs:
        envs.append(service_model_env)
    if not _image_requires_model_specific_price(image_model_key):
        envs.extend(_PRICE_ENV_FALLBACK_CHAINS["image"])
    return tuple(envs)


def _pricing_source_from_env(env_name: Optional[str]) -> Optional[str]:
    if not env_name:
        return None
    if env_name.startswith("GENIE_COST_") and any(
        segment in env_name for segment in ("GEMINI_", "IMAGEN_")
    ):
        return "model_specific_env"
    if env_name.startswith("KEYSURI_COST_"):
        return "legacy_keysuri_env"
    if env_name.startswith("GENIE_COST_"):
        return "env"
    return "service_specific_env"


def _safe_token_cost(tokens: Any, price: Optional[float]) -> Optional[float]:
    if tokens is None or price is None:
        return None
    try:
        return (float(tokens) / 1_000_000.0) * price
    except (TypeError, ValueError):
        return None


def _has_usage(
    prompt_tokens: Any,
    candidates_tokens: Any,
    thoughts_tokens: Any,
    total_tokens: Any,
    image_generated_count: int,
) -> bool:
    return any(v is not None for v in (prompt_tokens, candidates_tokens, thoughts_tokens, total_tokens)) or bool(image_generated_count)


def _needs_price(tokens: Any) -> bool:
    try:
        return tokens is not None and float(tokens) > 0
    except (TypeError, ValueError):
        return tokens is not None


def estimate_genie_generation_cost(
    usage: Optional[Mapping[str, Any]],
    *,
    service_family: str,
    text_model: Optional[str] = None,
    image_model: Optional[str] = None,
    program_id: Optional[str] = None,
    mode: Optional[str] = None,
    run_id: Optional[str] = None,
    image_generated_count: int = 0,
) -> Dict[str, Any]:
    """Build a best-effort cost_estimate dict. Never raises.

    service_family: "keysuri" | "today_genie" | "tomorrow_genie" | "genie".
    Returns ``total_cost_usd``/``total_cost_krw`` as ``None`` unless enough
    unit-price env vars are set to compute them — usage counts are always
    preserved even when pricing is entirely unknown. Estimate-only; must
    never affect validation_result, HTTP status, or customer-send decisions.
    """
    try:
        usage = dict(usage or {})
        prompt_tokens = usage.get("prompt_token_count")
        candidates_tokens = usage.get("candidates_token_count")
        thoughts_tokens = usage.get("thoughts_token_count")
        total_tokens = usage.get("total_token_count")

        text_model_key = normalize_model_env_key(text_model)
        image_model_key = normalize_model_env_key(image_model)

        input_envs = _text_price_env_chain(
            "input", text_model_key=text_model_key, service_family=service_family
        )
        output_envs = _text_price_env_chain(
            "output", text_model_key=text_model_key, service_family=service_family
        )
        thoughts_envs = _text_price_env_chain(
            "thoughts", text_model_key=text_model_key, service_family=service_family
        )
        image_envs = _image_price_env_chain(
            image_model_key=image_model_key, service_family=service_family
        )

        input_price, input_price_env = _read_price_from_envs(input_envs)
        output_price, output_price_env = _read_price_from_envs(output_envs)
        thoughts_price, thoughts_price_env = _read_price_from_envs(thoughts_envs)
        image_price, image_price_env = _read_price_from_envs(image_envs)
        krw_per_usd, krw_per_usd_env = _read_price_from_envs(_PRICE_ENV_FALLBACK_CHAINS["krw_per_usd"])

        pricing_note = (
            "estimate only; actual billing may differ. Cloud Run/GCS/SMTP/blog "
            "posting infra costs may be separate."
        )
        thoughts_price_used = thoughts_price
        if thoughts_tokens and thoughts_price is None and output_price is not None:
            thoughts_price_used = output_price
            pricing_note += (
                "; thoughts token unit price not set, thoughts tokens billed at "
                "the selected output-token rate as fallback"
            )

        text_input_cost = _safe_token_cost(prompt_tokens, input_price)
        text_output_cost = _safe_token_cost(candidates_tokens, output_price)
        text_thoughts_cost = _safe_token_cost(thoughts_tokens, thoughts_price_used)
        image_cost = (
            image_generated_count * image_price
            if image_generated_count and image_price is not None
            else (0.0 if image_price is not None else None)
        )

        cost_components = [text_input_cost, text_output_cost, text_thoughts_cost, image_cost]
        known_components = [c for c in cost_components if c is not None]
        total_cost_usd = sum(known_components) if known_components else None

        total_cost_krw = (
            total_cost_usd * krw_per_usd
            if total_cost_usd is not None and krw_per_usd is not None
            else None
        )

        image_pricing_status = "not_applicable"
        if image_generated_count:
            if image_price is not None:
                image_pricing_status = "configured"
            else:
                image_pricing_status = "unsupported_or_unconfigured"
                pricing_note += (
                    "; Image model pricing is not configured as per-image; "
                    "image cost not calculated."
                )
        elif image_model and image_price is None and _image_requires_model_specific_price(image_model_key):
            image_pricing_status = "unsupported_or_unconfigured"

        env_prices_set = [p for p in (input_price, output_price, thoughts_price, image_price) if p is not None]
        if not env_prices_set:
            pricing_source = "unknown"
        elif None in (input_price, output_price):
            pricing_source = "partial"
        else:
            pricing_source = "env"

        missing_price_env = []
        if _needs_price(prompt_tokens) and input_price is None and input_envs:
            missing_price_env.append(input_envs[0])
        if _needs_price(candidates_tokens) and output_price is None and output_envs:
            missing_price_env.append(output_envs[0])
        if _needs_price(thoughts_tokens) and thoughts_price_used is None and thoughts_envs:
            missing_price_env.append(thoughts_envs[0])
        if image_generated_count and image_price is None and image_envs:
            missing_price_env.append(image_envs[0])
        if total_cost_usd is not None and krw_per_usd is None:
            missing_price_env.append(ENV_KRW_PER_USD)
        missing_price_env = list(dict.fromkeys(missing_price_env))

        usage_present = _has_usage(
            prompt_tokens,
            candidates_tokens,
            thoughts_tokens,
            total_tokens,
            image_generated_count,
        )
        price_env_configured = bool(env_prices_set or krw_per_usd is not None)
        if not usage_present:
            cost_estimate_status = "unavailable"
        elif not known_components:
            cost_estimate_status = "usage_only"
        elif (
            not missing_price_env
            and total_cost_usd is not None
            and total_cost_krw is not None
            and (not image_generated_count or image_cost is not None)
        ):
            cost_estimate_status = "estimated"
        else:
            cost_estimate_status = "partial"

        return {
            "estimate_only": True,
            "service_family": service_family,
            "program_id": program_id,
            "mode": mode,
            "run_id": run_id,
            "currency": "USD",
            "model": {
                "text_model": text_model,
                "image_model": image_model,
            },
            "cost_estimate_status": cost_estimate_status,
            "price_env_configured": price_env_configured,
            "model_pricing": {
                "text_model_key": text_model_key,
                "image_model_key": image_model_key,
                "text_pricing_source": _pricing_source_from_env(input_price_env or output_price_env),
                "image_pricing_source": _pricing_source_from_env(image_price_env),
                "image_pricing_status": image_pricing_status,
            },
            "missing_price_env": missing_price_env,
            "usage": {
                "prompt_token_count": prompt_tokens,
                "candidates_token_count": candidates_tokens,
                "thoughts_token_count": thoughts_tokens,
                "total_token_count": total_tokens,
                "generated_image_count": image_generated_count,
            },
            "unit_prices": {
                "input_usd_per_1m_tokens": input_price,
                "output_usd_per_1m_tokens": output_price,
                "thoughts_usd_per_1m_tokens": thoughts_price,
                "image_usd_per_image": image_price,
                "krw_per_usd": krw_per_usd,
                "input_price_env": input_price_env,
                "output_price_env": output_price_env,
                "thoughts_price_env": thoughts_price_env,
                "image_price_env": image_price_env,
                "krw_per_usd_env": krw_per_usd_env,
            },
            "components": {
                "text_input_cost_usd": text_input_cost,
                "text_output_cost_usd": text_output_cost,
                "text_thoughts_cost_usd": text_thoughts_cost,
                "image_cost_usd": image_cost,
                "infra_cost_usd": None,
            },
            "total_cost_usd": total_cost_usd,
            "total_cost_krw": total_cost_krw,
            "pricing_source": pricing_source,
            "pricing_note": pricing_note,
        }
    except Exception as exc:  # pragma: no cover - defensive, cost estimate is best-effort
        return {
            "estimate_only": True,
            "service_family": service_family,
            "program_id": program_id,
            "mode": mode,
            "run_id": run_id,
            "currency": "USD",
            "model": {"text_model": text_model, "image_model": image_model},
            "usage": dict(usage or {}) if isinstance(usage, Mapping) else {},
            "unit_prices": {},
            "components": {},
            "total_cost_usd": None,
            "total_cost_krw": None,
            "pricing_source": "error",
            "cost_estimate_status": "error",
            "price_env_configured": False,
            "model_pricing": {
                "text_model_key": normalize_model_env_key(text_model),
                "image_model_key": normalize_model_env_key(image_model),
                "text_pricing_source": None,
                "image_pricing_source": None,
                "image_pricing_status": "unknown",
            },
            "missing_price_env": [],
            "pricing_note": f"cost estimate failed: {exc}",
        }
