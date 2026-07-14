"""Run-level GCP list-price estimates, kept separate from actual billing."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Mapping, Optional

from genie_billing_export import decimal_text

# Current official public list prices checked 2026-07-14. These are management
# estimates before monthly free allotments, credits, contract pricing, or taxes.
CLOUD_RUN_ACTIVE_VCPU_SECOND_USD = Decimal("0.000024")
CLOUD_RUN_ACTIVE_GIB_SECOND_USD = Decimal("0.0000025")
CLOUD_RUN_REQUEST_USD = Decimal("0.0000004")
GCS_STANDARD_CLASS_A_USD_PER_1000 = Decimal("0.005")
GCS_STANDARD_CLASS_B_USD_PER_1000 = Decimal("0.0004")
LOGGING_INGEST_USD_PER_GIB = Decimal("0.50")
GIB = Decimal(1024 ** 3)

PRICING_SOURCE = (
    "google_cloud_official_list_price_checked_2026-07-14;"
    "cloud_run_request_based;gcs_standard_operations;logging_pre_free_tier"
)


def _decimal(value: Any) -> Optional[Decimal]:
    if value in (None, ""):
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return parsed if parsed.is_finite() and parsed >= 0 else None


def _elapsed_ms(meta: Mapping[str, Any]) -> Optional[Decimal]:
    for key in ("request_latency_ms", "service_run_elapsed_ms", "elapsed_ms"):
        parsed = _decimal(meta.get(key))
        if parsed is not None:
            return parsed
    start, end = meta.get("request_start"), meta.get("request_end")
    if start and end:
        try:
            a = datetime.fromisoformat(str(start).replace("Z", "+00:00"))
            b = datetime.fromisoformat(str(end).replace("Z", "+00:00"))
            return Decimal(str(max(0.0, (b - a).total_seconds() * 1000)))
        except ValueError:
            return None
    return None


def estimate_cloud_run_list_cost(
    latency_ms: Any,
    *,
    configured_vcpu: Any = 1,
    configured_memory_gib: Any = Decimal("0.5"),
    request_count: Any = 1,
) -> Optional[Decimal]:
    latency = _decimal(latency_ms)
    vcpu = _decimal(configured_vcpu)
    memory = _decimal(configured_memory_gib)
    requests = _decimal(request_count)
    if None in (latency, vcpu, memory, requests):
        return None
    seconds = latency / Decimal("1000")
    return (
        seconds * vcpu * CLOUD_RUN_ACTIVE_VCPU_SECOND_USD
        + seconds * memory * CLOUD_RUN_ACTIVE_GIB_SECOND_USD
        + requests * CLOUD_RUN_REQUEST_USD
    )


def estimate_gcs_operation_list_cost(class_a: Any, class_b: Any) -> Optional[Decimal]:
    a, b = _decimal(class_a), _decimal(class_b)
    if a is None or b is None:
        return None
    return (
        a * GCS_STANDARD_CLASS_A_USD_PER_1000 / Decimal("1000")
        + b * GCS_STANDARD_CLASS_B_USD_PER_1000 / Decimal("1000")
    )


def estimate_logging_list_cost(log_bytes: Any) -> Optional[Decimal]:
    size = _decimal(log_bytes)
    return None if size is None else size / GIB * LOGGING_INGEST_USD_PER_GIB


def estimate_run_direct_infra(meta: Mapping[str, Any]) -> Dict[str, Any]:
    latency = _elapsed_ms(meta)
    vcpu = _decimal(meta.get("configured_vcpu")) or Decimal("1")
    memory = _decimal(meta.get("configured_memory_gib")) or Decimal("0.5")
    request_count = _decimal(meta.get("request_count")) or Decimal("1")
    cloud_run = estimate_cloud_run_list_cost(
        latency, configured_vcpu=vcpu, configured_memory_gib=memory, request_count=request_count
    )
    gcs = estimate_gcs_operation_list_cost(
        meta.get("class_a_operation_count"), meta.get("class_b_operation_count")
    )
    logging_cost = estimate_logging_list_cost(meta.get("run_log_bytes_estimate"))
    network = _decimal(meta.get("network_list_estimate_usd"))
    components = [cloud_run, gcs, logging_cost, network]
    known = [value for value in components if value is not None]
    status = "complete_list_estimate" if all(value is not None for value in components) else (
        "partial_list_estimate" if known else "insufficient_usage_telemetry"
    )
    total = sum(known, Decimal("0")) if known else None
    return {
        "cloud_run_revision": meta.get("cloud_run_revision") or meta.get("revision"),
        "request_start": meta.get("request_start"),
        "request_end": meta.get("request_end"),
        "request_latency_ms": decimal_text(latency),
        "configured_vcpu": decimal_text(vcpu),
        "configured_memory_gib": decimal_text(memory),
        "billing_mode": meta.get("billing_mode") or "request_based",
        "min_instances": meta.get("min_instances", 0),
        "max_instances": meta.get("max_instances", 20),
        "concurrency": meta.get("concurrency", 80),
        "request_count": decimal_text(request_count),
        "cloud_run_list_estimate_usd": decimal_text(cloud_run),
        "artifact_object_count": meta.get("artifact_object_count"),
        "artifact_total_bytes": meta.get("artifact_total_bytes"),
        "class_a_operation_count": meta.get("class_a_operation_count"),
        "class_b_operation_count": meta.get("class_b_operation_count"),
        "artifact_retention_hours": meta.get("artifact_retention_hours"),
        "gcs_list_estimate_usd": decimal_text(gcs),
        "run_log_bytes_estimate": meta.get("run_log_bytes_estimate"),
        "logging_list_estimate_usd": decimal_text(logging_cost),
        "response_bytes": meta.get("response_bytes"),
        "artifact_egress_bytes": meta.get("artifact_egress_bytes"),
        "network_list_estimate_usd": decimal_text(network),
        "run_direct_infra_list_estimate_usd": decimal_text(total),
        "run_direct_infra_estimate_status": status,
        "infra_pricing_source": PRICING_SOURCE,
        "infra_pricing_checked_at": "2026-07-14T00:00:00+09:00",
    }
