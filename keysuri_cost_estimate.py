"""Best-effort KeeSuri owner-review generation cost estimate (never authoritative).

This is NOT a billing integration — no Cloud Billing API, no external pricing
lookup, no Secret access. It only combines locally-known Gemini usage_metadata
token counts with operator-supplied unit prices (env vars) to produce a rough
estimate for operational visibility (logs/response/artifact metadata). Actual
billed amounts may differ; pricing tables change and this module does not
track them automatically.

Kept for backward compatibility (existing schema/signature/tests unchanged).
The common GENIE_COST_* env vars now take priority over the legacy
KEYSURI_COST_* names below — see genie_cost_estimate.py, which this module
delegates env-price reading to. New services should use
genie_cost_estimate.estimate_genie_generation_cost directly.
"""
from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

from genie_cost_estimate import estimate_genie_generation_cost

# Legacy env var names — still documented here since KeeSuri operators may
# already have these set; genie_cost_estimate._read_price checks the common
# GENIE_COST_* name first and falls back to these automatically.
ENV_INPUT_USD_PER_1M = "KEYSURI_COST_INPUT_USD_PER_1M_TOKENS"
ENV_OUTPUT_USD_PER_1M = "KEYSURI_COST_OUTPUT_USD_PER_1M_TOKENS"
ENV_THOUGHTS_USD_PER_1M = "KEYSURI_COST_THOUGHTS_USD_PER_1M_TOKENS"
ENV_IMAGE_USD_PER_IMAGE = "KEYSURI_COST_IMAGE_USD_PER_IMAGE"
ENV_KRW_PER_USD = "KEYSURI_COST_KRW_PER_USD"


def estimate_keysuri_gemini_cost(
    usage: Optional[Mapping[str, Any]],
    *,
    model: Optional[str] = None,
    image_model: Optional[str] = None,
    program_id: Optional[str] = None,
    run_id: Optional[str] = None,
    image_generated_count: int = 0,
    image_usage: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Build a best-effort cost_estimate dict. Never raises.

    Returns a dict following the schema documented in the module docstring —
    ``total_cost_usd``/``total_cost_krw`` are ``None`` unless enough unit-price
    env vars are set to compute them. Estimate-only; must never affect
    validation_result, HTTP status, or customer-send decisions.
    """
    try:
        common = estimate_genie_generation_cost(
            usage,
            service_family="keysuri",
            text_model=model,
            image_model=image_model,
            program_id=program_id,
            run_id=run_id,
            image_generated_count=image_generated_count,
            image_usage=image_usage,
        )
        common_usage = common.get("usage") if isinstance(common.get("usage"), dict) else {}
        return {
            **common,
            "model": model,
            "usage": {
                "prompt_token_count": common_usage.get("prompt_token_count"),
                "candidates_token_count": common_usage.get("candidates_token_count"),
                "thoughts_token_count": common_usage.get("thoughts_token_count"),
                "total_token_count": common_usage.get("total_token_count"),
                "generated_image_count": common_usage.get("generated_image_count"),
            },
            "image_model": image_model,
            "image_usage": dict(common.get("image_usage") or {}),
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
            "cost_estimate_status": "error",
            "price_env_configured": False,
            "model_pricing": {},
            "missing_price_env": [],
            "pricing_note": f"cost estimate failed: {exc}",
        }
