from __future__ import annotations

import csv
import hashlib
import io
import unittest
from decimal import Decimal
from pathlib import Path

from admin_cost_ledger import cost_ledger_object_key
from tools.backfill_cost_ledger import (
    LedgerDocument,
    build_backfill_plan,
    execute,
)

FIXTURE = Path(__file__).parent / "fixtures" / "cost_ledger_2026_07_13_rows.csv"


class FakeLedgerStore:
    def __init__(self, key: str, text: str, *, fail_replace: bool = False) -> None:
        self.objects = {key: LedgerDocument(text, 1)}
        self.next_generation = 2
        self.fail_replace = fail_replace
        self.create_calls = 0
        self.replace_calls = 0

    def read(self, key: str) -> LedgerDocument:
        doc = self.objects[key]
        return LedgerDocument(doc.text, doc.generation)

    def create(self, key: str, text: str) -> LedgerDocument:
        if key in self.objects:
            raise RuntimeError("if_generation_match=0 failed")
        self.create_calls += 1
        doc = LedgerDocument(text, self.next_generation)
        self.next_generation += 1
        self.objects[key] = doc
        return self.read(key)

    def replace_from_object(self, source_key: str, destination_key: str, expected_generation: int) -> LedgerDocument:
        self.replace_calls += 1
        if self.fail_replace:
            raise RuntimeError("precondition failed")
        current = self.objects[destination_key]
        if current.generation != expected_generation:
            raise RuntimeError("generation mismatch")
        source = self.objects[source_key]
        doc = LedgerDocument(source.text, self.next_generation)
        self.next_generation += 1
        self.objects[destination_key] = doc
        return self.read(destination_key)


def _fixture_text() -> str:
    return FIXTURE.read_text(encoding="utf-8")


class BackfillPlanTests(unittest.TestCase):
    def test_fixture_matches_production_distribution_and_totals(self) -> None:
        plan = build_backfill_plan(_fixture_text())
        self.assertEqual(plan.row_count, 13)
        self.assertEqual(plan.model_counts["gemini-2.5-flash"], 9)
        self.assertEqual(plan.model_counts["gemini-3-flash-preview"], 4)
        self.assertEqual(plan.model_totals["gemini-2.5-flash"], Decimal("0.255861"))
        self.assertEqual(plan.model_totals["gemini-3-flash-preview"], Decimal("0.0684325"))
        self.assertEqual(plan.total_text_cost, Decimal("0.3242935"))
        self.assertEqual(plan.unknown_models, [])
        self.assertEqual(plan.duplicate_run_ids, [])
        self.assertEqual(plan.invalid_rows, [])
        self.assertEqual(plan.changed_row_count, 13)

    def test_column_order_inserts_text_total_after_reasoning(self) -> None:
        plan = build_backfill_plan(_fixture_text())
        fields = next(csv.reader(io.StringIO(plan.final_text)))
        thoughts = fields.index("text_thoughts_cost_usd")
        self.assertEqual(fields[thoughts + 1], "text_total_cost_usd")

    def test_crlf_source_hash_and_line_endings_are_byte_exact(self) -> None:
        raw = _fixture_text().replace("\n", "\r\n")
        plan = build_backfill_plan(raw)
        self.assertEqual(
            plan.source_sha256,
            hashlib.sha256(raw.encode("utf-8")).hexdigest(),
        )
        self.assertEqual(plan.final_text.count("\r\n"), plan.row_count + 1)
        self.assertNotIn("\n", plan.final_text.replace("\r\n", ""))

    def test_rows_are_partial_text_only_with_unknown_image_pricing(self) -> None:
        plan = build_backfill_plan(_fixture_text())
        rows = list(csv.DictReader(io.StringIO(plan.final_text)))
        self.assertEqual(plan.text_total_nonempty_rows, 13)
        self.assertTrue(all(row["cost_estimate_status"] == "partial_text_only" for row in rows))
        self.assertTrue(all(row["missing_price_env"] == "unknown_image_pricing" for row in rows))
        self.assertTrue(all(row["image_cost_usd"] == "" for row in rows))
        self.assertTrue(all(row["total_cost_usd"] == "" for row in rows))

    def test_existing_nonempty_cost_is_preserved(self) -> None:
        rows = list(csv.DictReader(io.StringIO(_fixture_text())))
        fields = list(rows[0])
        rows[0]["text_input_cost_usd"] = "9.123"
        out = io.StringIO()
        writer = csv.DictWriter(out, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
        plan = build_backfill_plan(out.getvalue())
        final = list(csv.DictReader(io.StringIO(plan.final_text)))
        self.assertEqual(final[0]["text_input_cost_usd"], "9.123")

    def test_unknown_model_is_skipped(self) -> None:
        raw = _fixture_text().replace("gemini-2.5-flash", "unknown-model", 1)
        plan = build_backfill_plan(raw)
        self.assertEqual(plan.target_row_count, 12)
        self.assertEqual(plan.unknown_models, ["unknown-model"])

    def test_duplicate_run_id_is_detected(self) -> None:
        raw = _fixture_text().replace("fixture_run_02", "fixture_run_01", 1)
        plan = build_backfill_plan(raw)
        self.assertEqual(plan.duplicate_run_ids, ["fixture_run_01"])
        self.assertFalse(plan.can_apply)

    def test_invalid_token_total_is_detected(self) -> None:
        raw = _fixture_text().replace(",21979,", ",21978,", 1)
        plan = build_backfill_plan(raw)
        self.assertEqual(len(plan.invalid_rows), 1)
        self.assertFalse(plan.can_apply)

    def test_zero_generated_images_sets_complete_total(self) -> None:
        raw = _fixture_text().replace(",21979,,,,,,,,", ",21979,0,,,,,,,,", 1)
        plan = build_backfill_plan(raw)
        row = list(csv.DictReader(io.StringIO(plan.final_text)))[0]
        self.assertEqual(row["cost_estimate_status"], "estimated")
        self.assertEqual(row["total_cost_usd"], row["text_total_cost_usd"])
        self.assertEqual(row["missing_price_env"], "")


class BackfillExecutionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.key = cost_ledger_object_key("2026-07")

    def test_dry_run_has_no_mutation(self) -> None:
        store = FakeLedgerStore(self.key, _fixture_text())
        report = execute(store, "bucket", "2026-07", "dry-run")
        self.assertFalse(report["mutation"])
        self.assertEqual(store.create_calls, 0)
        self.assertEqual(store.replace_calls, 0)
        self.assertEqual(store.read(self.key).text, _fixture_text())

    def test_apply_creates_backup_and_atomically_replaces(self) -> None:
        store = FakeLedgerStore(self.key, _fixture_text())
        report = execute(store, "bucket", "2026-07", "apply")
        self.assertTrue(report["mutation"])
        self.assertTrue(report["atomic_replacement"])
        self.assertEqual(report["backup_sha256"], report["source_sha256"])
        self.assertEqual(report["text_total_nonempty_rows"], 13)
        final_plan = build_backfill_plan(store.read(self.key).text)
        self.assertEqual(final_plan.changed_row_count, 0)
        self.assertEqual(final_plan.text_total_nonempty_rows, 13)
        self.assertTrue(any("/backups/" in key for key in store.objects))

    def test_apply_is_idempotent(self) -> None:
        store = FakeLedgerStore(self.key, _fixture_text())
        execute(store, "bucket", "2026-07", "apply")
        object_count = len(store.objects)
        report = execute(store, "bucket", "2026-07", "apply")
        self.assertFalse(report["mutation"])
        self.assertTrue(report["idempotent_noop"])
        self.assertEqual(len(store.objects), object_count)

    def test_atomic_replace_failure_preserves_original(self) -> None:
        source = _fixture_text()
        store = FakeLedgerStore(self.key, source, fail_replace=True)
        with self.assertRaisesRegex(RuntimeError, "original_preserved=true"):
            execute(store, "bucket", "2026-07", "apply")
        self.assertEqual(store.read(self.key).text, source)

    def test_verify_is_read_only_after_apply(self) -> None:
        store = FakeLedgerStore(self.key, _fixture_text())
        execute(store, "bucket", "2026-07", "apply")
        creates = store.create_calls
        report = execute(store, "bucket", "2026-07", "verify")
        self.assertTrue(report["verification_pass"])
        self.assertEqual(report["changed_rows"], 0)
        self.assertEqual(store.create_calls, creates)


if __name__ == "__main__":
    unittest.main()
