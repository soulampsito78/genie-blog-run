"""Best-effort KeeSuri owner-review generation cost estimate (never authoritative).

This is NOT a billing integration — no Cloud Billing API, no external pricing
lookup, no Secret access. It only combines locally-known Gemini usage_metadata
token counts with operator-supplied unit prices (env vars) to produce a rough
estimate for operational visibility (logs/response/artifact metadata). Actual
billed amounts may differ; pricing tables change and this module does not
track them automatically.
"""
from __future__ import annotations

import os
from typing import Any, Dict, Mapping, Optional

ENV_INPUT_USD_PER_1M = "KEYSURI_COST_INPUT_USD_PER_1M_TOKENS"
ENV_OUTPUT_USD_PER_1M = "KEYSURI_COST_OUTPUT_USD_PER_1M_TOKENS"
ENV_THOUGHTS_USD_PER_1M = "KEYSURI_COST_THOUGHTS_USD_PER_1M_TOKENS"
ENV_IMAGE_USD_PER_IMAGE = "KEYSURI_COST_IMAGE_USD_PER_IMAGE"
ENV_KRW_PER_USD = "KEYSURI_COST_KRW_PER_USD"


def _read_float_env(name: str) -> Optional[float]:
    raw = os.getenv(name, "").strip()
    if not raw:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def estimate_keysuri_gemini_cost(
    usage: Optional[Mapping[str, Any]],
    *,
    model: Optional[str] = None,
    program_id: Optional[str] = None,
    run_id: Optional[str] = None,
    image_generated_count: int = 0,
) -> Dict[str, Any]:
    """Build a best-effort cost_estimate dict. Never raises.

    Returns a dict following the schema documented in the module docstring —
    ``total_cost_usd``/``total_cost_krw`` are ``None`` unless enough unit-price
    env vars are set to compute them. Estimate-only; must never affect
    validation_result, HTTP status, or customer-send decisions.
    """
    try:
        usage = dict(usage or {})
        prompt_tokens = usage.get("prompt_token_count")
        candidates_tokens = usage.get("candidates_token_count")
        thoughts_tokens = usage.get("thoughts_token_count")
        total_tokens = usage.get("total_token_count")

        input_price = _read_float_env(ENV_INPUT_USD_PER_1M)
        output_price = _read_float_env(ENV_OUTPUT_USD_PER_1M)
        thoughts_price = _read_float_env(ENV_THOUGHTS_USD_PER_1M)
        image_price = _read_float_env(ENV_IMAGE_USD_PER_IMAGE)
        krw_per_usd = _read_float_env(ENV_KRW_PER_USD)

        pricing_note = "estimate only; actual billing may differ"
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
            "currency": "USD",
            "program_id": program_id,
            "run_id": run_id,
            "model": model,
            "usage": {
                "prompt_token_count": prompt_tokens,
                "candidates_token_count": candidates_tokens,
                "thoughts_token_count": thoughts_tokens,
                "total_token_count": total_tokens,
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
            },
            "total_cost_usd": total_cost_usd,
            "total_cost_krw": total_cost_krw,
            "pricing_source": pricing_source,
            "pricing_note": pricing_note,
        }
    except Exception as exc:  # pragma: no cover - defensive, cost estimate is best-effort
        return {
            "estimate_only": True,
            "currency": "USD",
            "program_id": program_id,
            "run_id": run_id,
            "model": model,
            "usage": dict(usage or {}) if isinstance(usage, Mapping) else {},
            "unit_prices": {},
            "components": {},
            "total_cost_usd": None,
            "total_cost_krw": None,
            "pricing_source": "unknown",
            "pricing_note": f"cost estimate failed: {exc}",
        }
