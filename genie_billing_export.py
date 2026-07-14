"""Cloud Billing export normalization and monthly management summaries.

The exported ``cost`` and signed ``credits.amount`` values are authoritative.
This module never substitutes list-price estimates for missing billing data.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional
from zoneinfo import ZoneInfo

from admin_store import (
    _gcs_download_text,
    _uses_gcs_backend,
    admin_artifact_gcs_prefix,
    admin_runs_dir,
)

PROJECT_ID = "gen-lang-client-0667098249"
DATASET_ID = "genie_billing_export"
KST = ZoneInfo("Asia/Seoul")

BILLING_CATEGORIES = (
    "AI_DIRECT_RECONCILIATION",
    "RUN_COMPUTE",
    "RUN_STORAGE",
    "SHARED_PLATFORM",
    "OTHER_UNCLASSIFIED",
)


def decimal_or_none(value: Any) -> Optional[Decimal]:
    if value in (None, ""):
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def decimal_text(value: Optional[Decimal]) -> Optional[str]:
    if value is None:
        return None
    rendered = format(value, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered or "0"


def signed_credit_total(credits: Any) -> Decimal:
    """Sum exported credit amounts without guessing or flipping their sign."""
    if not isinstance(credits, (list, tuple)):
        return Decimal("0")
    total = Decimal("0")
    for credit in credits:
        if not isinstance(credit, Mapping):
            continue
        amount = decimal_or_none(credit.get("amount"))
        if amount is not None:
            total += amount
    return total


def billing_freshness_status(
    last_usage_time: Any,
    *,
    now: Optional[datetime] = None,
    max_lag_hours: int = 48,
) -> str:
    if not last_usage_time:
        return "billing_export_pending"
    try:
        stamp = datetime.fromisoformat(str(last_usage_time).replace("Z", "+00:00"))
    except ValueError:
        return "billing_data_stale"
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    reference = now or datetime.now(timezone.utc)
    return "billing_data_stale" if reference.astimezone(timezone.utc) - stamp.astimezone(timezone.utc) > timedelta(hours=max_lag_hours) else "billing_data_fresh"


def load_classification(path: Optional[Path] = None) -> Dict[str, Any]:
    source = path or Path(__file__).with_name("config") / "genie_billing_sku_classification.yaml"
    # JSON is valid YAML and avoids adding a production parser dependency.
    data = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("billing classification must be an object")
    return data


def classify_service_sku(
    service_id: str,
    service_description: str,
    sku_id: str,
    *,
    config: Optional[Mapping[str, Any]] = None,
) -> str:
    mapping = dict(config or load_classification())
    sid = str(service_id or "").strip()
    sdesc = str(service_description or "").strip()
    sku = str(sku_id or "").strip()
    for category in BILLING_CATEGORIES[:-1]:
        rule = mapping.get(category) if isinstance(mapping.get(category), Mapping) else {}
        if sku and sku in set(rule.get("sku_ids") or []):
            return category
        if sid and sid in set(rule.get("service_ids") or []):
            return category
        if sdesc and sdesc in set(rule.get("service_descriptions") or []):
            return category
    return "OTHER_UNCLASSIFIED"


def normalize_billing_row(
    row: Mapping[str, Any], *, config: Optional[Mapping[str, Any]] = None
) -> Dict[str, Any]:
    """Normalize one Standard/Detailed export row using Decimal arithmetic."""
    project = row.get("project") if isinstance(row.get("project"), Mapping) else {}
    service = row.get("service") if isinstance(row.get("service"), Mapping) else {}
    sku = row.get("sku") if isinstance(row.get("sku"), Mapping) else {}
    usage = row.get("usage") if isinstance(row.get("usage"), Mapping) else {}
    invoice = row.get("invoice") if isinstance(row.get("invoice"), Mapping) else {}
    resource = row.get("resource") if isinstance(row.get("resource"), Mapping) else {}
    location = row.get("location") if isinstance(row.get("location"), Mapping) else {}

    gross = decimal_or_none(row.get("cost")) or Decimal("0")
    credits = signed_credit_total(row.get("credits"))
    net = gross + credits
    currency = str(row.get("currency") or "").strip()
    conversion = decimal_or_none(row.get("currency_conversion_rate"))
    usd_gross = usd_credits = usd_net = None
    conversion_source = None
    if currency == "USD":
        usd_gross, usd_credits, usd_net = gross, credits, net
        conversion_source = "billing_currency_usd"
    elif conversion is not None and conversion > 0:
        usd_gross = gross / conversion
        usd_credits = credits / conversion
        usd_net = net / conversion
        conversion_source = "billing_export_currency_conversion_rate"

    usage_start = row.get("usage_start_time")
    usage_date_kst = row.get("usage_date_kst")
    if not usage_date_kst and usage_start:
        try:
            stamp = datetime.fromisoformat(str(usage_start).replace("Z", "+00:00"))
            usage_date_kst = stamp.astimezone(KST).date().isoformat()
        except ValueError:
            usage_date_kst = None

    service_id = str(service.get("id") or row.get("service_id") or "")
    service_description = str(service.get("description") or row.get("service_description") or "")
    sku_id = str(sku.get("id") or row.get("sku_id") or "")
    category = classify_service_sku(
        service_id, service_description, sku_id, config=config
    )
    return {
        "billing_account_id": row.get("billing_account_id"),
        "project_id": project.get("id") or row.get("project_id"),
        "project_name": project.get("name") or row.get("project_name"),
        "service_id": service_id,
        "service_description": service_description,
        "sku_id": sku_id,
        "sku_description": sku.get("description") or row.get("sku_description"),
        "resource_name": resource.get("name") or row.get("resource_name"),
        "location": location.get("location") or row.get("location_name"),
        "usage_start_time": usage_start,
        "usage_end_time": row.get("usage_end_time"),
        "usage_date_kst": usage_date_kst,
        "invoice_month": invoice.get("month") or row.get("invoice_month"),
        "usage_amount": usage.get("amount") or row.get("usage_amount"),
        "usage_unit": usage.get("unit") or row.get("usage_unit"),
        "cost": decimal_text(gross),
        "credits": decimal_text(credits),
        "gross_cost": decimal_text(gross),
        "net_cost": decimal_text(net),
        "currency": currency,
        "currency_conversion_rate": decimal_text(conversion),
        "gross_cost_usd": decimal_text(usd_gross),
        "credits_usd": decimal_text(usd_credits),
        "net_cost_usd": decimal_text(usd_net),
        "currency_conversion_source": conversion_source,
        "labels": row.get("labels") or [],
        "system_labels": row.get("system_labels") or [],
        "export_source_table": row.get("export_source_table"),
        "exported_at": row.get("export_time") or row.get("exported_at"),
        "cost_category": category,
    }


def aggregate_monthly_rows(
    rows: Iterable[Mapping[str, Any]], *, config: Optional[Mapping[str, Any]] = None
) -> Dict[str, Any]:
    normalized = [normalize_billing_row(row, config=config) for row in rows]
    currencies = sorted({str(row.get("currency") or "") for row in normalized if row.get("currency")})
    category_totals: Dict[str, Decimal] = {category: Decimal("0") for category in BILLING_CATEGORIES}
    gross = credits = net = Decimal("0")
    latest_usage = latest_load = None
    unknown: List[Dict[str, str]] = []
    usd_convertible = True
    usd_gross = usd_credits = usd_net = Decimal("0")
    for row in normalized:
        row_gross = decimal_or_none(row.get("gross_cost")) or Decimal("0")
        row_credits = decimal_or_none(row.get("credits")) or Decimal("0")
        row_net = decimal_or_none(row.get("net_cost")) or Decimal("0")
        gross += row_gross
        credits += row_credits
        net += row_net
        category = str(row.get("cost_category") or "OTHER_UNCLASSIFIED")
        category_totals.setdefault(category, Decimal("0"))
        category_totals[category] += row_net
        if category == "OTHER_UNCLASSIFIED":
            unknown.append({
                "service_id": str(row.get("service_id") or ""),
                "service_description": str(row.get("service_description") or ""),
                "sku_id": str(row.get("sku_id") or ""),
                "sku_description": str(row.get("sku_description") or ""),
            })
        row_usd_net = decimal_or_none(row.get("net_cost_usd"))
        row_usd_gross = decimal_or_none(row.get("gross_cost_usd"))
        row_usd_credits = decimal_or_none(row.get("credits_usd"))
        if row_usd_net is None or row_usd_gross is None or row_usd_credits is None:
            usd_convertible = False
        else:
            usd_gross += row_usd_gross
            usd_credits += row_usd_credits
            usd_net += row_usd_net
        latest_usage = max(filter(None, [latest_usage, row.get("usage_end_time")]), default=None)
        latest_load = max(filter(None, [latest_load, row.get("exported_at")]), default=None)

    currency = currencies[0] if len(currencies) == 1 else None
    vertex = category_totals["AI_DIRECT_RECONCILIATION"]
    non_ai = net - vertex
    return {
        "billing_data_status": "billing_data_partial" if normalized else "billing_export_pending",
        "billing_export_last_usage_time": latest_usage,
        "billing_export_last_load_time": latest_load,
        "billing_data_freshness": billing_freshness_status(latest_usage),
        "billing_row_count": len(normalized),
        "gcp_gross_cost": decimal_text(gross),
        "gcp_credits": decimal_text(credits),
        "gcp_net_cost": decimal_text(net),
        "vertex_ai_billed_gross": decimal_text(sum(
            (decimal_or_none(row.get("gross_cost")) or Decimal("0"))
            for row in normalized if row.get("cost_category") == "AI_DIRECT_RECONCILIATION"
        )),
        "vertex_ai_billed_net": decimal_text(vertex),
        "non_ai_infra_gross": decimal_text(gross - sum(
            (decimal_or_none(row.get("gross_cost")) or Decimal("0"))
            for row in normalized if row.get("cost_category") == "AI_DIRECT_RECONCILIATION"
        )),
        "non_ai_infra_net": decimal_text(non_ai),
        "run_compute_net": decimal_text(category_totals["RUN_COMPUTE"]),
        "run_storage_net": decimal_text(category_totals["RUN_STORAGE"]),
        "shared_platform_net": decimal_text(category_totals["SHARED_PLATFORM"]),
        "other_unclassified_net": decimal_text(category_totals["OTHER_UNCLASSIFIED"]),
        "billing_currency": currency,
        "billing_cost_usd": decimal_text(usd_net) if usd_convertible and normalized else None,
        "billing_gross_usd": decimal_text(usd_gross) if usd_convertible and normalized else None,
        "billing_credits_usd": decimal_text(usd_credits) if usd_convertible and normalized else None,
        "billing_cost_krw": decimal_text(net) if currency == "KRW" else None,
        "currency_conversion_source": (
            "billing_export_currency_conversion_rate" if usd_convertible and currency != "USD" and normalized
            else "billing_currency_usd" if currency == "USD" else None
        ),
        "billing_reconciliation_status": (
            "infra_mapping_partial" if unknown else "billing_data_partial"
        ),
        "unknown_service_skus": unknown,
    }


def billing_summary_object_key(month: str) -> str:
    return f"{admin_artifact_gcs_prefix()}/cost_reports/genie_billing_summary_{month}.json"


def billing_summary_path(month: str) -> Path:
    return admin_runs_dir() / "cost_reports" / f"genie_billing_summary_{month}.json"


def pending_billing_summary(month: str) -> Dict[str, Any]:
    return {
        "month": month,
        "billing_data_status": "billing_export_pending",
        "billing_reconciliation_status": "billing_export_pending",
        "billing_row_count": 0,
        "unknown_service_skus": [],
    }


def load_billing_summary(month: str) -> Dict[str, Any]:
    raw: Optional[str]
    if _uses_gcs_backend():
        raw = _gcs_download_text(billing_summary_object_key(month))
    else:
        path = billing_summary_path(month)
        raw = path.read_text(encoding="utf-8") if path.is_file() else None
    if not raw:
        return pending_billing_summary(month)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return pending_billing_summary(month)
    return data if isinstance(data, dict) else pending_billing_summary(month)
