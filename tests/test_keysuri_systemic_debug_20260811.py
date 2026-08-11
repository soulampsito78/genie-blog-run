from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from keysuri_source_text_normalization import (
    AMBIGUOUS_UNSAFE,
    FEED_READ_MORE_MARKER,
    LEGIT_QUOTED,
    LEGIT_SENTENCE_FINAL,
    classify_ellipsis_structure,
    normalize_feed_source_text,
    normalize_keysuri_source_pack,
)
from keysuri_visible_text_quality import (
    KEYSURI_DANGLING_QUOTED_TITLE_BLOCKED,
    merge_visible_text_quality_fields,
    repair_korean_connector_ellipsis_text,
    validate_and_repair_keysuri_visible_text_quality,
)


class SourceNormalizationAndGrammarTests(unittest.TestCase):
    def test_wordpress_feed_read_more_entities_are_removed_upstream(self) -> None:
        variants = (
            "with hands-on experiences [&#8230;]",
            "with hands-on experiences […]",
            "with hands-on experiences [...]",
            "with hands-on experiences 【…】",
        )
        for value in variants:
            with self.subTest(value=value):
                result = normalize_feed_source_text(value)
                self.assertEqual(result.text, "with hands-on experiences")
                self.assertIn(FEED_READ_MORE_MARKER, result.provenance_classes)

    def test_ambiguous_parenthetical_ellipsis_is_preserved_for_blocking(self) -> None:
        result = normalize_feed_source_text("확인 불가 (…)")
        self.assertEqual(result.text, "확인 불가 (…)")
        self.assertIn(AMBIGUOUS_UNSAFE, result.provenance_classes)
        repaired = repair_korean_connector_ellipsis_text(result.text)
        self.assertTrue(repaired.blocked)

    def test_legitimate_quoted_and_sentence_final_ellipsis_are_preserved(self) -> None:
        quoted = "그는 “잠시 멈추겠습니다…”라고 설명했습니다."
        final = "이 흐름은 계속 지켜보겠습니다…"
        self.assertIn(LEGIT_QUOTED, classify_ellipsis_structure(quoted))
        self.assertIn(LEGIT_SENTENCE_FINAL, classify_ellipsis_structure(final))
        for value in (quoted, final):
            result = repair_korean_connector_ellipsis_text(value)
            self.assertFalse(result.blocked)
            self.assertEqual(result.text, value)

    def test_connector_property_matrix_repairs_without_residual(self) -> None:
        ellipses = ("…", "..", "...", "⋯", "‥")
        spaces = ("", " ", "\u00a0", "\u200b")
        left_edges = ("오늘", "today —", "흥국·", "Warships:", "'3파전'")
        cases = 0
        for left in left_edges:
            for ellipsis in ellipses:
                for gap in spaces:
                    value = f"{left}{gap}{ellipsis}{gap}다음 신호"
                    result = repair_korean_connector_ellipsis_text(value)
                    self.assertFalse(result.blocked, value)
                    self.assertNotRegex(result.text, r"…|\.{2,}|⋯|‥")
                    cases += 1
        self.assertEqual(cases, 100)

    def test_source_pack_records_bounded_normalization_provenance(self) -> None:
        pack = {
            "program_id": "keysuri_global_tech",
            "sources": [{"source_id": "s1", "title": "NVIDIA", "snippet": "tail [&#8230;]"}],
            "claims": [{"claim_id": "c1", "headline": "NVIDIA", "summary": "tail […]"}],
        }
        out = normalize_keysuri_source_pack(pack)
        self.assertEqual(out["sources"][0]["snippet"], "tail")
        self.assertEqual(out["claims"][0]["summary"], "tail")
        diag = out["source_text_normalization"]
        self.assertEqual(diag["changed_field_count"], 2)
        self.assertTrue(all("source_id" in item for item in diag["changed_fields"]))

    def test_raw_rss_numeric_entity_is_removed_before_source_record(self) -> None:
        from keysuri_live_source_smoke import parse_feed_xml

        xml = b"""<?xml version='1.0' encoding='UTF-8'?>
        <rss><channel><item><title>NVIDIA update</title>
        <link>https://blogs.nvidia.com/example</link>
        <description>with hands-on experiences [&#8230;]</description>
        <pubDate>Tue, 11 Aug 2026 01:00:00 GMT</pubDate>
        </item></channel></rss>"""
        parsed = parse_feed_xml(xml)
        self.assertEqual(parsed[0]["summary"], "with hands-on experiences")

    def test_failure_evidence_is_centered_and_carries_identity(self) -> None:
        payload = {
            "top_5_news": {
                "items": [
                    {
                        "source_id": "claim-live-nvidia-blog-9f10ae9fb1",
                        "summary": "x" * 90 + " 확인 불가 (…) " + "y" * 90,
                    }
                ]
            }
        }
        _repaired, fields = validate_and_repair_keysuri_visible_text_quality(payload)
        sample = fields["visible_text_quality_samples"][0]
        self.assertEqual(sample["rank"], 1)
        self.assertEqual(sample["source_id"], "claim-live-nvidia-blog-9f10ae9fb1")
        self.assertEqual(sample["validator_result"], "block")
        self.assertIn("U+2026", sample["unicode_codepoints"])
        self.assertIn("…", sample["sample"])

    def test_pass_diagnostics_separate_historical_block_from_terminal(self) -> None:
        merged = merge_visible_text_quality_fields(
            {
                "visible_text_quality_status": "pass",
                "visible_text_quality_issue_codes": [KEYSURI_DANGLING_QUOTED_TITLE_BLOCKED],
                "visible_text_dangling_quoted_title_blocked": False,
            }
        )
        self.assertEqual(merged["visible_text_quality_status"], "pass")
        self.assertEqual(merged["terminal_issue_codes"], [])
        self.assertNotIn(
            KEYSURI_DANGLING_QUOTED_TITLE_BLOCKED,
            merged["visible_text_quality_issue_codes"],
        )
        self.assertIn(KEYSURI_DANGLING_QUOTED_TITLE_BLOCKED, merged["pre_repair_findings"])


class PreflightRepresentativenessTests(unittest.TestCase):
    def _source_pack(self, path: Path, *, suffix: str = "a") -> dict:
        pack = {
            "program_id": "keysuri_global_tech",
            "generated_at": "2026-08-11T11:45:00+09:00",
            "sources": [
                {
                    "source_id": f"s{i}{suffix}",
                    "source_url": f"https://example.com/{i}{suffix}",
                    "published_at": "2026-08-11T10:00:00+09:00",
                    "title": f"Headline {i} {suffix}",
                    "snippet": f"Summary {i}",
                }
                for i in range(5)
            ],
            "claims": [],
            "global_top5_selection": {
                "selected_source_ids": [f"s{i}{suffix}" for i in range(5)]
            },
        }
        path.write_text(json.dumps(pack), encoding="utf-8")
        return pack

    def _smoke(self, path: Path) -> SimpleNamespace:
        return SimpleNamespace(
            ok=True,
            called_gemini=True,
            parse_status="parsed_valid",
            generated_briefing={"opening": "정상입니다."},
            validation_issues=[],
            error=None,
            generation_diagnostics={},
            generation_contract={
                "schema_fingerprint": "schema",
                "prompt_template_fingerprint": "prompt",
                "model_identifier": "gemini-test",
            },
            generation_attempt_count=1,
            source_pack_path=str(path),
        )

    def test_preflight_fetches_live_while_reliability_keeps_frozen_pack(self) -> None:
        from natural_run_reliability import run_keysuri_reliability_generation

        with tempfile.TemporaryDirectory() as td:
            pack_path = Path(td) / "pack.json"
            self._source_pack(pack_path)
            smoke = self._smoke(pack_path)
            with mock.patch(
                "keysuri_live_source_smoke.run_keysuri_live_source_smoke", return_value=smoke
            ) as runner:
                result = run_keysuri_reliability_generation(
                    "keysuri_global_tech", execution_class="preflight_canary"
                )
            self.assertTrue(result["ok"])
            self.assertEqual(result["input_mode"], "live_current_feed")
            self.assertEqual(len(result["selected_news_ids"]), 5)
            kwargs = runner.call_args.kwargs
            self.assertIsNone(kwargs["frozen_source_pack_path"])
            self.assertTrue(kwargs["allow_network"])

    def test_selection_drift_is_explicit_but_not_a_cancel_signal(self) -> None:
        from natural_run_reliability import (
            compare_natural_input_to_preflight,
            keysuri_input_fingerprint_fields,
        )

        with tempfile.TemporaryDirectory() as td:
            a_path = Path(td) / "a.json"
            b_path = Path(td) / "b.json"
            a = self._source_pack(a_path, suffix="a")
            b = self._source_pack(b_path, suffix="b")
            pre = keysuri_input_fingerprint_fields(a, {"model_identifier": "m"})
            natural = keysuri_input_fingerprint_fields(b, {"model_identifier": "m"})
            compared = compare_natural_input_to_preflight(
                natural,
                {
                    "preflight_source_snapshot_hash": pre["source_snapshot_hash"],
                    "preflight_selection_fingerprint": pre["selection_fingerprint"],
                },
            )
            self.assertTrue(compared["preflight_input_drift"])
            self.assertEqual(compared["preflight_input_diagnostic"], "PREFLIGHT_INPUT_DRIFT")
            self.assertNotIn("cancel", compared)

    def test_preflight_failure_alert_uses_supported_email_signature(self) -> None:
        from natural_run_reliability import run_natural_preflight

        failed = {
            "ok": False,
            "program_id": "keysuri_global_tech",
            "finished_at": "2026-08-11T11:46:00+09:00",
            "issue_codes": ["unsafe"],
            "called_gemini": True,
        }
        with mock.patch("natural_run_reliability.run_program_canary", return_value=failed), mock.patch(
            "email_sender.send_genie_email", return_value=True
        ) as sender:
            result = run_natural_preflight("keysuri_global_tech")
        self.assertTrue(result["alert_sent"])
        self.assertNotIn("to_addrs", sender.call_args.kwargs)
        self.assertIn("to_addrs_override", sender.call_args.kwargs)


class RecoverySignatureGuardTests(unittest.TestCase):
    def test_two_identical_failures_block_third_until_revision_changes(self) -> None:
        import natural_run_incident_store as store

        with tempfile.TemporaryDirectory() as td, mock.patch.object(
            store, "incidents_local_dir", return_value=Path(td)
        ), mock.patch.dict(os.environ, {"GENIE_ADMIN_ARTIFACT_BUCKET": "", "GENIE_ARTIFACT_BUCKET": "", "K_REVISION": "rev-a"}, clear=False):
            incident = store.new_incident(
                program_id="keysuri_global_tech",
                kst_date="2026-08-11",
                retry_verdict=store.RETRY_ALLOWED_WITH_WARNING,
            )
            incident["status"] = store.STATUS_REPORTED
            store.save_incident(incident)
            components = {
                "incident_id": incident["incident_id"],
                "revision": "rev-a",
                "stage": "validation",
                "issue_code": "keysuri_korean_connector_ellipsis_blocked",
                "structural_failure_class": "VISIBLE_TEXT_CONNECTOR_FAMILY",
                "selected_input_fingerprint": "selection-a",
            }
            for index in range(2):
                lease = store.acquire_recovery_lease(incident["incident_id"])
                self.assertTrue(lease)
                store.complete_recovery(
                    incident["incident_id"],
                    lease_token=str(lease),
                    success=False,
                    recovery_run_id=f"recovery-{index}",
                    failure_signature_components=components,
                )
            blocked = store.load_incident(incident["incident_id"])
            self.assertEqual(blocked["status"], store.STATUS_RETRY_BLOCKED_PENDING_PATCH)
            self.assertEqual(blocked["recovery_failure_signature_count"], 2)
            self.assertIsNone(store.acquire_recovery_lease(incident["incident_id"]))

            with mock.patch.dict(os.environ, {"K_REVISION": "rev-b"}, clear=False):
                self.assertTrue(store.acquire_recovery_lease(incident["incident_id"]))


if __name__ == "__main__":
    unittest.main()
