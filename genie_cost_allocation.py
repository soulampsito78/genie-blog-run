"""Management-accounting allocation without AI/GCP double counting."""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, Iterable, Mapping, Optional

from genie_billing_export import decimal_or_none, decimal_text

DELIVERED_STATUSES = frozenset({
    "sent", "smtp_accepted", "delivery_confirmed",
    "customer_sent_after_approval", "sent_after_owner_approval",
})


def allocation_metrics(shared_platform_net: Any, rows: Iterable[Mapping[str, Any]]) -> Dict[str, Any]:
    records = list(rows)
    shared = decimal_or_none(shared_platform_net)
    operational = len(records)  # successful, blocked, failed, probe, and no-send all count.
    delivered = sum(
        str(row.get("customer_delivery_status") or "").strip() in DELIVERED_STATUSES
        for row in records
    )
    return {
        "operational_run_count": operational,
        "delivered_run_count": delivered,
        "shared_overhead_per_operational_run": decimal_text(shared / operational)
        if shared is not None and operational else None,
        "shared_overhead_per_operational_run_status": (
            "allocated" if shared is not None and operational else "denominator_zero" if not operational else "billing_pending"
        ),
        "shared_overhead_burden_per_delivered_run": decimal_text(shared / delivered)
        if shared is not None and delivered else None,
        "shared_overhead_burden_per_delivered_run_status": (
            "allocated" if shared is not None and delivered else "denominator_zero" if not delivered else "billing_pending"
        ),
        "cogs_allocation_policy": "shared_platform_net/all_operational_runs;delivered_burden_analysis_only",
    }


def modeled_service_cost(
    ai_model_list_cost_usd: Any,
    non_ai_infra_net_usd: Any,
    confirmed_external_cost_usd: Any = 0,
) -> Optional[Decimal]:
    """AI list cost + non-AI infra only; full GCP net is intentionally absent."""
    values = [
        decimal_or_none(ai_model_list_cost_usd),
        decimal_or_none(non_ai_infra_net_usd),
        decimal_or_none(confirmed_external_cost_usd),
    ]
    return None if any(value is None for value in values) else sum(values, Decimal("0"))
