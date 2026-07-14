from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

import pytest

from genie_billing_export import (
    aggregate_monthly_rows,
    billing_freshness_status,
    classify_service_sku,
    normalize_billing_row,
    pending_billing_summary,
    signed_credit_total,
)
from genie_cost_allocation import allocation_metrics, modeled_service_cost
from genie_infra_cost_estimate import (
    estimate_cloud_run_list_cost,
    estimate_gcs_operation_list_cost,
    estimate_logging_list_cost,
    estimate_run_direct_infra,
)
from tools.backfill_cost_ledger import LedgerDocument
from tools.backfill_infra_cost_ledger import build_infra_backfill_plan, execute
from tools.import_billing_costs import build_query, dry_run_query, main, month_utc_bounds


def billing_row(**overrides):
    row = {
        "billing_account_id": "masked",
        "project": {"id": "gen-lang-client-0667098249", "name": "GENIE"},
        "service": {"id": "svc", "description": "Cloud Build"},
        "sku": {"id": "sku", "description": "build minute"},
        "invoice": {"month": "202607"},
        "usage": {"amount": "1", "unit": "s"},
        "usage_start_time": "2026-07-14T00:00:00+00:00",
        "usage_end_time": "2026-07-14T01:00:00+00:00",
        "exported_at": "2026-07-14T02:00:00+00:00",
        "cost": "1000",
        "credits": [{"amount": "-200"}],
        "currency": "KRW",
        "currency_conversion_rate": "1400",
    }
    row.update(overrides)
    return row


def test_gross_credit_net_uses_exported_signed_credit():
    normalized = normalize_billing_row(billing_row())
    assert normalized["gross_cost"] == "1000"
    assert normalized["credits"] == "-200"
    assert normalized["net_cost"] == "800"


def test_credit_sign_is_never_flipped():
    assert signed_credit_total([{"amount": "5"}, {"amount": "-2"}]) == Decimal("3")


def test_vertex_ai_is_reconciliation_only():
    assert classify_service_sku("", "Vertex AI", "") == "AI_DIRECT_RECONCILIATION"


def test_non_ai_unknown_is_preserved():
    summary = aggregate_monthly_rows([billing_row(service={"id": "x", "description": "New Service"})])
    assert summary["other_unclassified_net"] == "800"
    assert summary["unknown_service_skus"][0]["service_description"] == "New Service"


def test_currency_is_preserved():
    assert normalize_billing_row(billing_row())["currency"] == "KRW"


def test_usd_conversion_uses_export_rate_only():
    normalized = normalize_billing_row(billing_row())
    assert Decimal(normalized["net_cost_usd"]) == Decimal("800") / Decimal("1400")
    assert normalized["currency_conversion_source"] == "billing_export_currency_conversion_rate"


def test_non_usd_without_conversion_stays_unconverted():
    normalized = normalize_billing_row(billing_row(currency_conversion_rate=None))
    assert normalized["net_cost_usd"] is None


def test_cloud_run_direct_estimate_exact():
    value = estimate_cloud_run_list_cost(1000, configured_vcpu=1, configured_memory_gib="0.5", request_count=1)
    assert value == Decimal("0.000024") + Decimal("0.00000125") + Decimal("0.0000004")


def test_gcs_direct_estimate_counts_operations():
    assert estimate_gcs_operation_list_cost(1000, 1000) == Decimal("0.0054")


def test_logging_is_pre_free_tier_list_estimate():
    assert estimate_logging_list_cost(1024 ** 3) == Decimal("0.50")


@pytest.mark.parametrize("service", ["Cloud Build", "Cloud Scheduler"])
def test_shared_services_are_deterministic(service):
    assert classify_service_sku("", service, "") == "SHARED_PLATFORM"


def test_modeled_cost_excludes_full_gcp_net():
    assert modeled_service_cost("1.2", "0.3", "0.1") == Decimal("1.6")


def test_operational_allocation_includes_probe_and_failed_rows():
    rows = [{"validation_result": "pass"}, {"validation_result": "failed"}, {"trigger_source": "probe"}]
    metrics = allocation_metrics("3", rows)
    assert metrics["operational_run_count"] == 3
    assert metrics["shared_overhead_per_operational_run"] == "1"


def test_delivered_burden_uses_delivered_status_only():
    rows = [{"customer_delivery_status": "smtp_accepted"}, {"customer_delivery_status": "not_sent"}]
    metrics = allocation_metrics("4", rows)
    assert metrics["delivered_run_count"] == 1
    assert metrics["shared_overhead_burden_per_delivered_run"] == "4"


def test_zero_denominators_are_blank_not_zero():
    metrics = allocation_metrics("4", [])
    assert metrics["shared_overhead_per_operational_run"] is None
    assert metrics["shared_overhead_burden_per_delivered_run"] is None


def test_pending_status_is_not_an_estimate():
    summary = pending_billing_summary("2026-07")
    assert summary["billing_data_status"] == "billing_export_pending"
    assert "gcp_net_cost" not in summary


def test_stale_export_is_detected():
    now = datetime(2026, 7, 14, tzinfo=timezone.utc)
    assert billing_freshness_status("2026-07-10T00:00:00+00:00", now=now) == "billing_data_stale"


def test_fresh_export_is_detected():
    now = datetime(2026, 7, 14, tzinfo=timezone.utc)
    assert billing_freshness_status("2026-07-13T12:00:00+00:00", now=now) == "billing_data_fresh"


def minimal_ledger() -> str:
    out = io.StringIO(newline="")
    writer = csv.DictWriter(out, fieldnames=[
        "run_id", "customer_delivery_status", "total_cost_usd",
        "run_direct_infra_list_estimate_usd", "text_total_cost_usd",
    ])
    writer.writeheader()
    writer.writerow({
        "run_id": "20260714_000000_today_genie_1234abcd",
        "customer_delivery_status": "not_sent",
        "total_cost_usd": "1.25",
        "run_direct_infra_list_estimate_usd": "0.05",
        "text_total_cost_usd": "0.25",
    })
    return out.getvalue()


def test_backfill_preserves_ai_fields_and_is_idempotent():
    plan = build_infra_backfill_plan(minimal_ledger(), {"shared_platform_net": "0.70"})
    assert plan.changed_row_count == 1
    rows = list(csv.DictReader(io.StringIO(plan.final_text)))
    assert rows[0]["total_cost_usd"] == "1.25"
    assert rows[0]["text_total_cost_usd"] == "0.25"
    assert build_infra_backfill_plan(plan.final_text, {"shared_platform_net": "0.70"}).changed_row_count == 0


class FakeStore:
    def __init__(self, raw, fail_replace=False):
        self.docs = {"admin_runs/cost_reports/genie_cost_ledger_2026-07.csv": LedgerDocument(raw, 1)}
        self.fail_replace = fail_replace
        self.created = []

    def read(self, key):
        return self.docs[key]

    def create(self, key, text):
        self.created.append(key)
        doc = LedgerDocument(text, len(self.docs) + 1)
        self.docs[key] = doc
        return doc

    def replace_from_object(self, source_key, destination_key, expected_generation):
        if self.fail_replace and destination_key.endswith(".csv"):
            raise RuntimeError("copy failed")
        doc = LedgerDocument(self.docs[source_key].text, len(self.docs) + 1)
        self.docs[destination_key] = doc
        return doc


def test_apply_creates_backup_and_atomic_replacement():
    store = FakeStore(minimal_ledger())
    report = execute(store, "bucket", "2026-07", {"shared_platform_net": "0.7"}, "apply")
    assert report["atomic_replacement"] is True
    assert any("/backups/" in key for key in store.created)


def test_atomic_failure_preserves_original():
    raw = minimal_ledger()
    store = FakeStore(raw, fail_replace=True)
    with pytest.raises(RuntimeError, match="original_preserved=True"):
        execute(store, "bucket", "2026-07", {"shared_platform_net": "0.7"}, "apply")
    assert store.read("admin_runs/cost_reports/genie_cost_ledger_2026-07.csv").text == raw


def test_bigquery_query_has_project_and_partition_time_bounds():
    query = build_query("p.d.t", "2026-07")
    assert "project.id = 'gen-lang-client-0667098249'" in query
    assert "usage_start_time >=" in query and "usage_start_time <" in query


def test_maximum_bytes_billed_is_always_passed():
    completed = SimpleNamespace(stdout="Query will process 123 bytes", stderr="")
    with mock.patch("tools.import_billing_costs.subprocess.run", return_value=completed) as run:
        assert dry_run_query("SELECT 1", 999) == 123
    assert "--maximum_bytes_billed=999" in run.call_args.args[0]


def test_dry_run_pending_makes_no_mutation(capsys):
    with mock.patch("tools.import_billing_costs.discover_source_table", return_value=None), \
         mock.patch("tools.import_billing_costs.export_service_account_status", return_value={"usage_export_writer": False, "pricing_export_writer": False}), \
         mock.patch("tools.import_billing_costs.atomic_write_summary") as write:
        assert main(["--month", "2026-07", "--dry-run"]) == 0
    assert write.call_count == 0
    assert json.loads(capsys.readouterr().out)["mutation"] is False


def test_decimal_precision_and_zero_are_distinct_from_unknown():
    summary = aggregate_monthly_rows([
        billing_row(cost="0.1", credits=[]), billing_row(cost="0.2", credits=[]),
    ])
    assert summary["gcp_net_cost"] == "0.3"
    assert normalize_billing_row(billing_row(cost="0", credits=[]))["net_cost"] == "0"
    assert pending_billing_summary("2026-07").get("gcp_net_cost") is None


def test_usage_month_and_invoice_month_are_not_conflated():
    normalized = normalize_billing_row(billing_row(
        usage_start_time="2026-07-31T16:00:00+00:00",
        invoice={"month": "202608"},
    ))
    assert normalized["usage_date_kst"] == "2026-08-01"
    assert normalized["invoice_month"] == "202608"


def test_month_bounds_use_kst_timezone():
    start, end = month_utc_bounds("2026-07")
    assert start.startswith("2026-06-30T15:00:00")
    assert end.startswith("2026-07-31T15:00:00")


def test_infra_status_distinguishes_partial_from_zero():
    partial = estimate_run_direct_infra({"request_latency_ms": 0})
    assert partial["cloud_run_list_estimate_usd"] == "0.0000004"
    assert partial["gcs_list_estimate_usd"] is None
    assert partial["run_direct_infra_estimate_status"] == "partial_list_estimate"
