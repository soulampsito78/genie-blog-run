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

GOOGLE_CLOUD_VERTEX_PRICING_URL = (
    "https://cloud.google.com/gemini-enterprise-agent-platform/generative-ai/pricing"
)
GOOGLE_CLOUD_VERTEX_PRICING_CHECKED_AT = "2026-07-14T17:06:57+09:00"

# Official Google Cloud Vertex AI Standard text prices, checked at the time
# above. Response and reasoning tokens share one canonical output rate.
GOOGLE_CLOUD_VERTEX_STANDARD_TEXT_PRICING: Dict[str, Dict[str, Any]] = {
    "gemini-2.5-flash": {
        "provider": "google_cloud_vertex_ai",
        "pricing_tier": "standard",
        "pricing_url": GOOGLE_CLOUD_VERTEX_PRICING_URL,
        "pricing_checked_at": GOOGLE_CLOUD_VERTEX_PRICING_CHECKED_AT,
        "model": "gemini-2.5-flash",
        "input_usd_per_1m_tokens": 0.30,
        "output_and_reasoning_usd_per_1m_tokens": 2.50,
    },
    "gemini-3-flash-preview": {
        "provider": "google_cloud_vertex_ai",
        "pricing_tier": "standard",
        "pricing_url": GOOGLE_CLOUD_VERTEX_PRICING_URL,
        "pricing_checked_at": GOOGLE_CLOUD_VERTEX_PRICING_CHECKED_AT,
        "model": "gemini-3-flash-preview",
        "input_usd_per_1m_tokens": 0.50,
        "output_and_reasoning_usd_per_1m_tokens": 3.00,
    },
}

# Common env vars — checked first for every service_family.
ENV_INPUT_USD_PER_1M = "GENIE_COST_INPUT_USD_PER_1M_TOKENS"
ENV_OUTPUT_USD_PER_1M = "GENIE_COST_OUTPUT_USD_PER_1M_TOKENS"
# Deprecated compatibility name. It is intentionally never used as a pricing
# rate: Google Cloud Standard prices response and reasoning at one output rate.
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
    "image": (ENV_IMAGE_USD_PER_IMAGE, _LEGACY_KEYSURI_ENV_IMAGE_USD_PER_IMAGE),
    "krw_per_usd": (ENV_KRW_PER_USD, _LEGACY_KEYSURI_ENV_KRW_PER_USD),
}

_PRICE_KIND_SUFFIXES = {
    "input": "INPUT_USD_PER_1M_TOKENS",
    "output": "OUTPUT_USD_PER_1M_TOKENS",
    "image": "IMAGE_USD_PER_IMAGE",
    "krw_per_usd": "KRW_PER_USD",
}

_DEPRECATED_THOUGHTS_ENV_NAMES = (
    ENV_THOUGHTS_USD_PER_1M,
    _LEGACY_KEYSURI_ENV_THOUGHTS_USD_PER_1M,
)


def canonical_model_id(model: Optional[str]) -> Optional[str]:
    """Return the model id from a short or fully-qualified Vertex resource."""
    if not model:
        return None
    value = str(model).strip().rstrip("/")
    if not value:
        return None
    match = re.search(r"(?:^|/)publishers/google/models/([^/]+)$", value, re.IGNORECASE)
    if match:
        value = match.group(1)
    elif "/models/" in value.lower():
        value = re.split(r"/models/", value, maxsplit=1, flags=re.IGNORECASE)[-1]
    return value.strip().lower() or None


def standard_text_pricing_for_model(model: Optional[str]) -> Optional[Dict[str, Any]]:
    """Return a copy of the verified Vertex Standard pricing contract."""
    canonical = canonical_model_id(model)
    pricing = GOOGLE_CLOUD_VERTEX_STANDARD_TEXT_PRICING.get(canonical or "")
    return dict(pricing) if pricing else None


def normalize_model_env_key(model: Optional[str]) -> Optional[str]:
    """Normalize a model id into the env-key segment used for pricing.

    Examples:
    - gemini-2.5-flash -> GEMINI_2_5_FLASH
    - gemini-3-flash-preview -> GEMINI_3_FLASH_PREVIEW
    - gemini-2.5-flash-image -> GEMINI_2_5_FLASH_IMAGE
    """
    canonical = canonical_model_id(model)
    if not canonical:
        return None
    normalized = re.sub(r"[^A-Za-z0-9]+", "_", canonical).strip("_").upper()
    return normalized or None


def _configured_deprecated_thoughts_env() -> Optional[str]:
    candidates = list(_DEPRECATED_THOUGHTS_ENV_NAMES)
    candidates.extend(
        name
        for name in sorted(os.environ)
        if name.endswith("_THOUGHTS_USD_PER_1M_TOKENS") and name not in candidates
    )
    for env_name in candidates:
        if os.getenv(env_name, "").strip():
            return env_name
    return None


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
        image_envs = _image_price_env_chain(
            image_model_key=image_model_key, service_family=service_family
        )

        input_price, input_price_env = _read_price_from_envs(input_envs)
        output_price, output_price_env = _read_price_from_envs(output_envs)
        image_price, image_price_env = _read_price_from_envs(image_envs)
        krw_per_usd, krw_per_usd_env = _read_price_from_envs(_PRICE_ENV_FALLBACK_CHAINS["krw_per_usd"])
        deprecated_thoughts_env = _configured_deprecated_thoughts_env()
        standard_contract = standard_text_pricing_for_model(text_model)

        pricing_note = (
            "estimate only; actual billing may differ. Cloud Run/GCS/SMTP/blog "
            "posting infra costs may be separate; response and reasoning tokens "
            "use the selected output-token rate"
        )
        if deprecated_thoughts_env:
            pricing_note += (
                f"; deprecated {deprecated_thoughts_env} is ignored"
            )

        text_input_cost = _safe_token_cost(prompt_tokens, input_price)
        text_output_cost = _safe_token_cost(candidates_tokens, output_price)
        text_thoughts_cost = _safe_token_cost(thoughts_tokens, output_price)
        image_cost = (
            image_generated_count * image_price
            if image_generated_count and image_price is not None
            else (0.0 if image_price is not None else None)
        )

        text_cost_components = [text_input_cost, text_output_cost, text_thoughts_cost]
        known_text_components = [c for c in text_cost_components if c is not None]
        text_total_cost_usd = sum(known_text_components) if known_text_components else None

        cost_components = [*text_cost_components, image_cost]
        known_components = [c for c in cost_components if c is not None]
        image_unconfigured = bool(image_generated_count) and image_cost is None
        # Do not present a text-only subtotal as a complete production total.
        total_cost_usd = (
            None if image_unconfigured else (sum(known_components) if known_components else None)
        )

        # Optional FX only — never required for USD status or totals.
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
        elif image_model and image_price is None and _image_requires_model_specific_price(image_model_key):
            image_pricing_status = "unsupported_or_unconfigured"

        text_priced = text_total_cost_usd is not None
        if text_priced and image_unconfigured:
            pricing_note += "; text cost calculated; image cost not configured"
        elif image_unconfigured:
            pricing_note += (
                "; Image model pricing is not configured as per-image; "
                "image cost not calculated."
            )

        env_prices_set = [p for p in (input_price, output_price, image_price) if p is not None]
        if not env_prices_set:
            pricing_source = "unknown"
        elif None in (input_price, output_price):
            pricing_source = "partial"
        else:
            pricing_source = "env"

        # KRW is optional display FX and must not appear in missing_price_env.
        missing_price_env = []
        if _needs_price(prompt_tokens) and input_price is None and input_envs:
            missing_price_env.append(input_envs[0])
        if (
            _needs_price(candidates_tokens) or _needs_price(thoughts_tokens)
        ) and output_price is None and output_envs:
            missing_price_env.append(output_envs[0])
        if image_generated_count and image_price is None:
            if not image_model_key:
                missing_price_env.append("unknown_image_pricing")
            elif image_envs:
                missing_price_env.append(image_envs[0])
        missing_price_env = list(dict.fromkeys(missing_price_env))

        usage_present = _has_usage(
            prompt_tokens,
            candidates_tokens,
            thoughts_tokens,
            total_tokens,
            image_generated_count,
        )
        price_env_configured = bool(env_prices_set)
        if not usage_present:
            cost_estimate_status = "unavailable"
        elif not known_components:
            cost_estimate_status = "usage_only"
        elif text_priced and image_unconfigured:
            cost_estimate_status = "partial_text_only"
        elif (
            not missing_price_env
            and total_cost_usd is not None
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
                "provider": standard_contract.get("provider") if standard_contract else None,
                "pricing_tier": standard_contract.get("pricing_tier") if standard_contract else None,
                "pricing_url": standard_contract.get("pricing_url") if standard_contract else None,
                "pricing_checked_at": standard_contract.get("pricing_checked_at") if standard_contract else None,
                "model": standard_contract.get("model") if standard_contract else canonical_model_id(text_model),
                "input_usd_per_1m_tokens": standard_contract.get("input_usd_per_1m_tokens") if standard_contract else None,
                "output_and_reasoning_usd_per_1m_tokens": standard_contract.get("output_and_reasoning_usd_per_1m_tokens") if standard_contract else None,
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
                "thoughts_usd_per_1m_tokens": output_price,
                "image_usd_per_image": image_price,
                "krw_per_usd": krw_per_usd,
                "input_price_env": input_price_env,
                "output_price_env": output_price_env,
                "thoughts_price_env": output_price_env,
                "deprecated_thoughts_price_env_ignored": deprecated_thoughts_env,
                "image_price_env": image_price_env,
                "krw_per_usd_env": krw_per_usd_env,
            },
            "components": {
                "text_input_cost_usd": text_input_cost,
                "text_output_cost_usd": text_output_cost,
                "text_thoughts_cost_usd": text_thoughts_cost,
                "text_total_cost_usd": text_total_cost_usd,
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
