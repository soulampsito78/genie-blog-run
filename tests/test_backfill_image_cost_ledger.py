from __future__ import annotations

import csv
import io
import unittest
from unittest import mock

from admin_cost_ledger import COST_LEDGER_COLUMNS, cost_ledger_object_key
from tools.backfill_cost_ledger import LedgerDocument
from tools.backfill_image_cost_ledger import build_backfill_plan, execute, load_evidence


def _ledger(rows):
    fields = [
        "run_id",
        "program_id",
        "revision",
        "text_model",
        "image_model",
        "generated_image_count",
        "text_total_cost_usd",
        "image_cost_usd",
        "total_cost_usd",
        "cost_estimate_status",
        "missing_price_env",
    ]
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue()


class ImageBackfillPlanTests(unittest.TestCase):
    def test_only_high_confidence_row_is_backfilled_and_unknown_stays_blank(self) -> None:
        evidence = load_evidence("2026-07")
        proven = evidence["runs"][0]
        raw = _ledger(
            [
                {
                    "run_id": proven["run_id"],
                    "program_id": proven["program_id"],
                    "revision": proven["revision"],
                    "text_model": "gemini-2.5-flash",
                    "image_model": "gemini-2.5-flash-image",
                    "text_total_cost_usd": "0.01",
                    "cost_estimate_status": "partial_text_only",
                },
                {
                    "run_id": "20260701_000000_unknown_aaaaaaaa",
                    "text_model": "gemini-2.5-flash",
                    "text_total_cost_usd": "0.02",
                    "cost_estimate_status": "partial_text_only",
                },
            ]
        )
        plan = build_backfill_plan(raw, evidence)
        rows = list(csv.DictReader(io.StringIO(plan.final_text)))
        self.assertTrue(plan.can_apply)
        self.assertEqual(plan.high_confidence_count, 1)
        self.assertEqual(plan.insufficient_count, 1)
        self.assertEqual(rows[0]["image_cost_usd"], "0.0774")
        self.assertEqual(rows[0]["total_cost_usd"], "0.0874")
        self.assertEqual(rows[0]["cost_estimate_status"], "fully_priced_ai_model_cost")
        self.assertEqual(rows[0]["text_total_cost_usd"], "0.01")
        self.assertEqual(rows[1]["image_cost_usd"], "")
        self.assertEqual(rows[1]["total_cost_usd"], "")
        self.assertEqual(rows[1]["cost_estimate_status"], "partial_text_only")

    def test_plan_is_idempotent(self) -> None:
        evidence = load_evidence("2026-07")
        item = evidence["runs"][7]
        raw = _ledger(
            [{
                "run_id": item["run_id"],
                "program_id": item["program_id"],
                "revision": item["revision"],
                "text_model": "gemini-3-flash-preview",
                "image_model": "gemini-2.5-flash-image",
                "text_total_cost_usd": "0.0121615",
                "cost_estimate_status": "partial_text_only",
            }]
        )
        first = build_backfill_plan(raw, evidence)
        second = build_backfill_plan(first.final_text, evidence)
        self.assertEqual(first.changed_row_count, 1)
        self.assertEqual(second.changed_row_count, 0)
        self.assertEqual(second.source_sha256, second.final_sha256)

    def test_existing_conflicting_image_cost_blocks_apply(self) -> None:
        evidence = load_evidence("2026-07")
        item = evidence["runs"][0]
        raw = _ledger(
            [{
                "run_id": item["run_id"],
                "text_total_cost_usd": "0.01",
                "image_cost_usd": "999",
            }]
        )
        plan = build_backfill_plan(raw, evidence)
        self.assertFalse(plan.can_apply)
        self.assertIn("conflicts with evidence", plan.invalid_rows[0])

    def test_committed_13_run_evidence_totals(self) -> None:
        evidence = load_evidence("2026-07")
        text_costs = [
            "0.0276587", "0.030435", "0.0266569", "0.0302351", "0.0319929",
            "0.0302994", "0.025876", "0.0121615", "0.012644", "0.027276",
            "0.0158775", "0.025431", "0.0277495",
        ]
        raw = _ledger(
            [
                {
                    "run_id": item["run_id"],
                    "program_id": item["program_id"],
                    "revision": item["revision"],
                    "text_model": "gemini-2.5-flash",
                    "image_model": "gemini-2.5-flash-image",
                    "text_total_cost_usd": text_cost,
                    "cost_estimate_status": "partial_text_only",
                }
                for item, text_cost in zip(evidence["runs"], text_costs)
            ]
        )
        plan = build_backfill_plan(raw, evidence)
        self.assertTrue(plan.can_apply)
        self.assertEqual(plan.row_count, 13)
        self.assertEqual(plan.paid_output_count, 22)
        self.assertEqual(str(plan.image_total), "0.8514")
        self.assertEqual(str(plan.text_total), "0.3242935")
        self.assertEqual(str(plan.complete_total), "1.1756935")
        self.assertEqual(plan.model_counts, {"gemini-2.5-flash-image": 13})
        self.assertEqual(str(plan.model_image_totals["gemini-2.5-flash-image"]), "0.8514")

    def test_revision_commit_mapping_and_enriched_per_run_evidence(self) -> None:
        evidence = load_evidence("2026-07")
        expected = {
            "genie-blog-run-00243-pvn": "8879d27260d1062c885c904e4e5b0dbba3df39e7",
            "genie-blog-run-00245-pfr": "c6af822837a20d51cce34f36c384a5e70020f80d",
            "genie-blog-run-00246-rwj": "0fe359fc6e652caa87093b685bfe069478d37b10",
            "genie-blog-run-00247-pfs": "3e1151af0a84347791fc3dad3da9224514c85532",
            "genie-blog-run-00248-2dl": "289445b053f7bd05bdcb7a946b4cb1fb16188dc0",
            "genie-blog-run-00249-jhp": "dc2603c7c3097fc45323c40ef1b3ea51440051ac",
            "genie-blog-run-00251-wwp": "a1d02f1ea6879868dbad95e4d4f639d43c347c4b",
            "genie-blog-run-00252-lp7": "c2b732c5bd521b81f6b7b7959f4e22564fcc3f37",
            "genie-blog-run-00253-kxl": "807a6952202e8d64e0fc97886525bf825c549932",
        }
        for item in evidence["runs"]:
            self.assertEqual(item["commit_sha"], expected[item["revision"]])
            self.assertTrue(item["created_at_kst"].endswith("+09:00"))
            self.assertEqual(item["generated_artifact_count"], item["successful_output_count"])
            self.assertTrue(item["backfill_allowed"])
            self.assertEqual(item["image_model_normalized"], "gemini-2.5-flash-image")

    def test_csv_columns_keep_canonical_order(self) -> None:
        evidence = load_evidence("2026-07")
        item = evidence["runs"][0]
        plan = build_backfill_plan(
            (source := _ledger([{"run_id": item["run_id"], "text_total_cost_usd": "0.01"}])),
            evidence,
        )
        original_fields = next(csv.reader(io.StringIO(source)))
        fields = next(csv.reader(io.StringIO(plan.final_text)))
        self.assertEqual(fields[: len(original_fields)], original_fields)
        self.assertEqual(
            fields[len(original_fields) :],
            [field for field in COST_LEDGER_COLUMNS if field not in original_fields],
        )


class _Object:
    size = 1


class _Bucket:
    def get_blob(self, _key):
        return _Object()


class _Store:
    def __init__(self, key: str, raw: str, *, fail_replace: bool = False) -> None:
        self.docs = {key: LedgerDocument(raw, 7)}
        self.created = []
        self.replaced = []
        self.fail_replace = fail_replace

    def read(self, key):
        return self.docs[key]

    def create(self, key, text):
        self.created.append(key)
        doc = LedgerDocument(text, len(self.docs) + 10)
        self.docs[key] = doc
        return doc

    def replace_from_object(self, source_key, destination_key, expected_generation):
        self.replaced.append((source_key, destination_key, expected_generation))
        if self.fail_replace:
            raise RuntimeError("injected atomic copy failure")
        source = self.docs[source_key]
        final = LedgerDocument(source.text, expected_generation + 1)
        self.docs[destination_key] = final
        return final


class ImageBackfillExecutionTests(unittest.TestCase):
    def _source(self):
        evidence = load_evidence("2026-07")
        item = evidence["runs"][0]
        raw = _ledger([{"run_id": item["run_id"], "text_total_cost_usd": "0.01"}])
        key = cost_ledger_object_key("2026-07")
        return evidence, raw, key

    def test_dry_run_does_not_create_or_replace_objects(self) -> None:
        evidence, raw, key = self._source()
        store = _Store(key, raw)
        report = execute(_Bucket(), "bucket", "2026-07", "dry-run", evidence, store=store)
        self.assertTrue(report["verification_pass"])
        self.assertFalse(report["mutation"])
        self.assertEqual(store.created, [])
        self.assertEqual(store.replaced, [])

    def test_apply_creates_backup_and_is_idempotent(self) -> None:
        evidence, raw, key = self._source()
        store = _Store(key, raw)
        with mock.patch(
            "tools.backfill_image_cost_ledger._ensure_evidence_object",
            return_value={"evidence_object": "evidence", "evidence_sha256": "sha", "evidence_generation": 1},
        ):
            report = execute(_Bucket(), "bucket", "2026-07", "apply", evidence, store=store)
            second = execute(_Bucket(), "bucket", "2026-07", "apply", evidence, store=store)
        self.assertTrue(report["atomic_replacement"])
        self.assertTrue(any("/backups/" in key for key in store.created))
        self.assertTrue(second["idempotent_noop"])

    def test_atomic_copy_failure_preserves_original(self) -> None:
        evidence, raw, key = self._source()
        store = _Store(key, raw, fail_replace=True)
        with self.assertRaisesRegex(RuntimeError, "original_preserved=True"):
            execute(_Bucket(), "bucket", "2026-07", "apply", evidence, store=store)
        self.assertEqual(store.read(key).text, raw)


if __name__ == "__main__":
    unittest.main()
