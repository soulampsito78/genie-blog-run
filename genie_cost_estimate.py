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

        input_price = _read_price("input")
        output_price = _read_price("output")
        thoughts_price = _read_price("thoughts")
        image_price = _read_price("image")
        krw_per_usd = _read_price("krw_per_usd")

        pricing_note = (
            "estimate only; actual billing may differ. Cloud Run/GCS/SMTP/blog "
            "posting infra costs may be separate."
        )
        thoughts_price_used = thoughts_price
        if thoughts_tokens and thoughts_price is None and output_price is not None:
            thoughts_price_used = output_price
            pricing_note += (
                f"; {ENV_THOUGHTS_USD_PER_1M} not set, thoughts tokens billed at "
                f"{ENV_OUTPUT_USD_PER_1M} rate as fallback"
            )

        text_input_cost = (
            (prompt_tokens / 1_000_000.0) * input_price
            if prompt_tokens is not None and input_price is not None
            else None
        )
        text_output_cost = (
            (candidates_tokens / 1_000_000.0) * output_price
            if candidates_tokens is not None and output_price is not None
            else None
        )
        text_thoughts_cost = (
            (thoughts_tokens / 1_000_000.0) * thoughts_price_used
            if thoughts_tokens is not None and thoughts_price_used is not None
            else None
        )
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

        env_prices_set = [p for p in (input_price, output_price, thoughts_price, image_price) if p is not None]
        if not env_prices_set:
            pricing_source = "unknown"
        elif None in (input_price, output_price):
            pricing_source = "partial"
        else:
            pricing_source = "env"

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
            "pricing_note": f"cost estimate failed: {exc}",
        }
