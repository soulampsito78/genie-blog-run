from __future__ import annotations

import ast
import json
import os
import unittest
from pathlib import Path
from unittest import mock

from admin_approval import build_current_approval_target
from admin_store import approve_run, can_approve_customer_send
from keysuri_briefing_content_quality import (
    BriefingContentIssue,
    BriefingContentQualityResult,
)
from keysuri_korea_longform_ux import (
    build_korea_one_line_checkpoint,
    sanitize_korea_customer_prose,
)
from keysuri_live_source_smoke import LiveSourceSmokeResult, SampleMarkerHit
from keysuri_quality_adjudication import (
    CUSTOMER_APPROVAL_UNAVAILABLE,
    CUSTOMER_WARNING_CONFIRMATION,
    EDITORIAL_POOR,
    EDITORIAL_READY,
    EDITORIAL_REVIEW,
    FINDING_REPAIRED,
    OWNER_HOLD_INCIDENT,
    OWNER_SEND_POOR_NOTICE,
    OWNER_SEND_WARNING,
    SAFETY_INCONCLUSIVE,
    SAFETY_SAFE,
    SAFETY_UNSAFE,
    adjudicate_keysuri_owner_surface,
    run_keysuri_graded_validation_no_send_proof,
)
from keysuri_service_full_run import (
    _adjudicate_and_send_owner_surface,
    _smoke_findings_for_canonical_adjudicator,
)
from keysuri_visible_text_quality import repair_keysuri_visible_text_fields


ROOT = Path(__file__).resolve().parents[1]


def _qa(*codes: str) -> BriefingContentQualityResult:
    issues = [
        BriefingContentIssue(code, f"{code} finding", section="top5", item_index=index)
        for index, code in enumerate(codes)
    ]
    return BriefingContentQualityResult(ok=not issues, issues=issues)


class KeysuriGradedValidationTests(unittest.TestCase):
    def test_01_single_adjudicator_and_four_delivery_paths(self) -> None:
        adjudicator_source = (ROOT / "keysuri_quality_adjudication.py").read_text(encoding="utf-8")
        service_source = (ROOT / "keysuri_service_full_run.py").read_text(encoding="utf-8")
        tree = ast.parse(adjudicator_source)
        definitions = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "_canonical_delivery_matrix"
        ]
        self.assertEqual(len(definitions), 1)
        self.assertEqual(adjudicator_source.count("owner_review_suppressed ="), 1)
        self.assertEqual(service_source.count("_adjudicate_and_send_owner_surface("), 5)

    def test_02_detectors_have_no_direct_smtp_suppression(self) -> None:
        service_source = (ROOT / "keysuri_service_full_run.py").read_text(encoding="utf-8")
        self.assertNotIn("if not post_render_qa.ok:", service_source)
        self.assertNotIn('if visible_text_quality_fields.get("visible_text_ellipsis_blocked"):', service_source)
        self.assertNotIn("_visible_text_quality_block_code", service_source)
        self.assertNotIn("or not smoke.ok", service_source)

    def test_02b_intermediate_smoke_findings_are_exhaustive_and_graded(self) -> None:
        base = {
            "ok": False,
            "program_id": "keysuri_global_tech",
            "source_pack_path": "/tmp/pack.json",
            "html_path": "/tmp/preview.html",
            "fetched_item_count": 5,
            "feed_urls_used": [],
            "sample_marker_pass": True,
            "placeholder_gate_pass": True,
            "validation_status": "PASS",
            "called_gemini": True,
            "parse_status": "parsed_valid",
            "visible_body_quality_pass": True,
        }
        placeholder = LiveSourceSmokeResult(
            **{
                **base,
                "placeholder_gate_pass": False,
                "placeholder_gate_hits": [
                    SampleMarkerHit(
                        code="generation_pending",
                        marker="generation_pending",
                        context="generation_pending",
                    )
                ],
            }
        )
        placeholder_result = adjudicate_keysuri_owner_surface(
            program_id="keysuri_global_tech",
            subject="[운영자 검토] 제목",
            email_html="<html><body>본문</body></html>",
            extra_findings=_smoke_findings_for_canonical_adjudicator(placeholder),
        )
        self.assertEqual(placeholder_result["safety_verdict"], SAFETY_SAFE)
        self.assertEqual(placeholder_result["editorial_verdict"], EDITORIAL_REVIEW)

        sample = LiveSourceSmokeResult(
            **{
                **base,
                "sample_marker_pass": False,
                "sample_marker_hits": [
                    SampleMarkerHit(
                        code="sample_only",
                        marker="sample only",
                        context="sample only",
                    )
                ],
            }
        )
        sample_result = adjudicate_keysuri_owner_surface(
            program_id="keysuri_global_tech",
            subject="[운영자 검토] 제목",
            email_html="<html><body>본문</body></html>",
            extra_findings=_smoke_findings_for_canonical_adjudicator(sample),
        )
        self.assertEqual(sample_result["safety_verdict"], SAFETY_UNSAFE)

        unexplained = LiveSourceSmokeResult(**base)
        unexplained_result = adjudicate_keysuri_owner_surface(
            program_id="keysuri_global_tech",
            subject="[운영자 검토] 제목",
            email_html="<html><body>본문</body></html>",
            extra_findings=_smoke_findings_for_canonical_adjudicator(unexplained),
        )
        self.assertEqual(
            unexplained_result["safety_verdict"], SAFETY_INCONCLUSIVE
        )

    def test_03_repaired_finding_cannot_remain_terminal(self) -> None:
        result = adjudicate_keysuri_owner_surface(
            program_id="keysuri_korea_tech",
            subject="[운영자 검토] 제목",
            email_html="<html><body>정상 본문</body></html>",
            visible_quality_fields={
                "visible_text_quality_issue_codes": [
                    "keysuri_korean_connector_ellipsis_repaired"
                ],
                "repair_history": [
                    {
                        "field": "checkpoint",
                        "sample": "AI/로봇",
                        "repaired_sample": "AI와 로봇",
                    }
                ],
            },
        )
        self.assertEqual(result["safety_verdict"], SAFETY_SAFE)
        self.assertEqual(result["editorial_verdict"], EDITORIAL_READY)
        self.assertEqual(result["terminal_issue_codes"], [])
        self.assertTrue(result["repair_history"])
        self.assertEqual(result["repair_history"][0]["before"], "AI/로봇")
        self.assertEqual(result["repair_history"][0]["after"], "AI와 로봇")
        self.assertEqual(
            {row["finding_state"] for row in result["findings"]}, {FINDING_REPAIRED}
        )

    def test_04_safe_review_reaches_owner_with_exact_warning_surface(self) -> None:
        sent = []

        def sender(body: str, subject: str, **kwargs):
            sent.append((subject, body, kwargs))
            return True

        with mock.patch.dict(os.environ, {"GENIE_OWNER_REVIEW_SEND": "1"}, clear=False):
            result = _adjudicate_and_send_owner_surface(
                program_id="keysuri_global_tech",
                subject="[운영자 검토] 글로벌 브리핑",
                email_html="<html><body><p>완전한 안전 본문</p></body></html>",
                owner_review_url="https://admin.example/r/1",
                visible_quality_fields={},
                post_render_qa=_qa("global_visible_raw_english_prose_blocked"),
                send_owner_email=True,
                send_fn=sender,
            )
        self.assertEqual(result["safety_verdict"], SAFETY_SAFE)
        self.assertEqual(result["editorial_verdict"], EDITORIAL_REVIEW)
        self.assertEqual(result["owner_delivery_behavior"], OWNER_SEND_WARNING)
        self.assertEqual(result["customer_approval_policy"], CUSTOMER_WARNING_CONFIRMATION)
        self.assertTrue(result["email_sent"])
        self.assertEqual(sent[0][0], result["owner_email_subject"])
        self.assertEqual(sent[0][1], result["owner_email_html"])
        self.assertIn("[운영자 검토][주의]", sent[0][0])
        self.assertIn("고객 발송 전 확인", sent[0][1])

    def test_05_safe_poor_persists_candidate_and_sends_only_notice(self) -> None:
        codes = (
            "global_visible_raw_english_prose_blocked",
            "global_visible_internal_template_leak_blocked",
            "global_visible_repeated_template_skeleton_blocked",
            "global_visible_deep_dive_duplication_blocked",
            "global_visible_category_grounding_mismatch",
            "global_visible_korean_particle_defect",
        )
        sent = []
        with mock.patch.dict(os.environ, {"GENIE_OWNER_REVIEW_SEND": "1"}, clear=False):
            result = _adjudicate_and_send_owner_surface(
                program_id="keysuri_global_tech",
                subject="[운영자 검토] 후보",
                email_html="<html><body><article>전체 후보</article></body></html>",
                owner_review_url="https://admin.example/r/poor",
                visible_quality_fields={},
                post_render_qa=_qa(*codes),
                send_owner_email=True,
                send_fn=lambda body, subject, **kwargs: sent.append((subject, body)) or True,
            )
        self.assertEqual(result["editorial_verdict"], EDITORIAL_POOR)
        self.assertEqual(result["owner_delivery_behavior"], OWNER_SEND_POOR_NOTICE)
        self.assertEqual(result["customer_approval_policy"], CUSTOMER_APPROVAL_UNAVAILABLE)
        self.assertEqual(result["candidate_email_subject"], "[운영자 검토] 후보")
        self.assertIn("전체 후보", result["persisted_email_html"])
        self.assertNotIn("<article>전체 후보</article>", sent[0][1])
        self.assertIn("Admin에서 전체 후보 확인", sent[0][1])

    def test_06_unsafe_and_unknown_hold_both_owner_and_customer(self) -> None:
        unsafe = adjudicate_keysuri_owner_surface(
            program_id="keysuri_global_tech",
            subject="제목",
            email_html="<html><body>본문</body></html>",
            post_render_result=_qa("unsupported_claim"),
        )
        unknown = adjudicate_keysuri_owner_surface(
            program_id="keysuri_global_tech",
            subject="제목",
            email_html="<html><body>본문</body></html>",
            post_render_result=_qa("unregistered_future_detector"),
        )
        self.assertEqual(unsafe["safety_verdict"], SAFETY_UNSAFE)
        self.assertEqual(unknown["safety_verdict"], SAFETY_INCONCLUSIVE)
        for result in (unsafe, unknown):
            self.assertEqual(result["owner_delivery_behavior"], OWNER_HOLD_INCIDENT)
            self.assertEqual(result["customer_approval_policy"], CUSTOMER_APPROVAL_UNAVAILABLE)
            self.assertEqual(result["owner_email_html"], "")

    def test_07_slash_repair_is_idempotent_and_ready(self) -> None:
        source = "글로벌과 국내 AI/로봇 시장을 함께 확인합니다."
        once = sanitize_korea_customer_prose(source)
        twice = sanitize_korea_customer_prose(once)
        self.assertEqual(once, twice)
        self.assertNotIn("AI/로봇", once)
        checkpoint = build_korea_one_line_checkpoint([], existing=source)
        self.assertNotIn("AI/로봇", checkpoint)

    def test_08_producer_repair_lifecycle_is_bounded_and_idempotent(self) -> None:
        payload = {"checkpoint": "시장…변화를 확인합니다."}
        once, first = repair_keysuri_visible_text_fields(payload)
        twice, second = repair_keysuri_visible_text_fields(once)
        self.assertEqual(once, twice)
        self.assertTrue(first["visible_text_ellipsis_repaired"])
        self.assertFalse(second["visible_text_ellipsis_repaired"])

    def test_09_customer_approval_matrix(self) -> None:
        base = {
            "mode": "keysuri_global_tech",
            "validation_result": "pass",
            "owner_review_status": "pending_review",
            "customer_delivery_status": "not_sent",
            "artifact_status": "emailed",
            "safety_verdict": "SAFE",
        }
        with mock.patch("keysuri_customer_delivery.customer_delivery_config_ready", return_value=(True, "ok")):
            ready = {**base, "editorial_verdict": "READY"}
            review = {**base, "editorial_verdict": "REVIEW"}
            poor = {**base, "editorial_verdict": "POOR"}
            unsafe = {**base, "safety_verdict": "UNSAFE", "editorial_verdict": "READY"}
            self.assertEqual(can_approve_customer_send(ready, has_email_html=True), (True, "ok"))
            self.assertEqual(can_approve_customer_send(review, has_email_html=True), (True, "ok"))
            self.assertEqual(
                can_approve_customer_send(poor, has_email_html=True),
                (False, "keysuri_editorial_poor"),
            )
            self.assertEqual(
                can_approve_customer_send(unsafe, has_email_html=True),
                (False, "keysuri_safety_not_safe"),
            )

    def test_10_review_warning_requirement_is_snapshot_bound(self) -> None:
        meta = {
            "mode": "keysuri_global_tech",
            "safety_verdict": "SAFE",
            "editorial_verdict": "REVIEW",
            "review_issue_codes": ["global_visible_raw_english_prose_blocked"],
        }
        with (
            mock.patch(
                "admin_approval._prepare_content_and_images",
                return_value=("제목", "<html>고객 본문</html>", [("/tmp/x.jpg", "cid", "x.jpg")]),
            ),
            mock.patch("admin_approval._sha256_file", return_value="image-hash"),
            mock.patch(
                "admin_approval.resolve_customer_recipients",
                return_value={
                    "admin_config_ok": True,
                    "final_recipients": ["customer@example.com"],
                    "recipient_configuration_version": "v1",
                    "recipient_configuration_hash": "cfg",
                },
            ),
        ):
            target = build_current_approval_target(
                run_id="20260815_120000_keysuri_global_tech_abcdef12",
                meta=meta,
                saved_html="<html>owner</html>",
            )
        self.assertTrue(target.snapshot_fields["warning_confirmation_required"])
        self.assertEqual(target.snapshot_fields["safety_verdict"], "SAFE")
        self.assertEqual(target.snapshot_fields["editorial_verdict"], "REVIEW")

    def test_10b_review_approval_requires_explicit_bound_warning_confirmation(self) -> None:
        meta = {
            "run_id": "20260815_120000_keysuri_global_tech_abcdef12",
            "mode": "keysuri_global_tech",
            "safety_verdict": "SAFE",
            "editorial_verdict": "REVIEW",
        }
        snapshot = {
            "approval_snapshot_id": "aps_20260815_120000_abcdef12",
            "warning_confirmation_required": True,
        }
        prepared = mock.Mock(recipients=["customer@example.com"])
        with (
            mock.patch("admin_store.load_run_artifact", return_value=meta),
            mock.patch("admin_store.load_run_email_html", return_value="<html>owner</html>"),
            mock.patch("admin_store.can_approve_customer_send", return_value=(True, "ok")),
            mock.patch(
                "admin_approval.verify_approval_snapshot",
                return_value=(snapshot, prepared),
            ),
            mock.patch("admin_safety_store.append_operator_audit"),
            mock.patch(
                "admin_safety_store.reserve_delivery_command",
                return_value=(False, {}),
            ) as reserve,
        ):
            blocked, blocked_status = approve_run(
                meta["run_id"],
                approval_snapshot_id=snapshot["approval_snapshot_id"],
                operator_id="owner",
                review_warning_confirmed=False,
            )
            self.assertIsNone(blocked)
            self.assertEqual(
                blocked_status, "REVIEW_WARNING_CONFIRMATION_REQUIRED"
            )
            reserve.assert_not_called()

            accepted, accepted_status = approve_run(
                meta["run_id"],
                approval_snapshot_id=snapshot["approval_snapshot_id"],
                operator_id="owner",
                review_warning_confirmed=True,
            )
            self.assertIsNone(accepted)
            self.assertEqual(accepted_status, "DUPLICATE_DELIVERY_COMMAND")
            reserve.assert_called_once()

    def test_11_today_sources_are_outside_the_remediation_diff(self) -> None:
        # Guardrail against accidentally broadening this patch into Today.
        import subprocess

        changed = subprocess.run(
            ["git", "diff", "--name-only", "--", "today_*.py"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        self.assertEqual(changed, "")

    def test_12_production_corpus_shadow_matrix(self) -> None:
        corpus = json.loads(
            (
                ROOT
                / "tests"
                / "fixtures"
                / "keysuri_graded_validation_corpus_20260815.json"
            ).read_text(encoding="utf-8")
        )
        self.assertGreaterEqual(len(corpus), 20)
        self.assertTrue(any(row["kind"].startswith("successful_global") for row in corpus))
        self.assertTrue(any(row["kind"].startswith("successful_korea") for row in corpus))
        for row in corpus:
            with self.subTest(row=row["id"]):
                result = adjudicate_keysuri_owner_surface(
                    program_id=row["program_id"],
                    subject="[운영자 검토] 코퍼스",
                    email_html="<html><body>저장된 운영 코퍼스 표면</body></html>",
                    extra_findings=[
                        {"issue_code": code, "field": "production_surface"}
                        for code in row["findings"]
                    ],
                    owner_review_url="https://admin.invalid/corpus",
                )
                self.assertEqual(result["safety_verdict"], row["expected_safety"])
                self.assertEqual(result["editorial_verdict"], row["expected_editorial"])
                self.assertEqual(
                    result["owner_delivery_behavior"], row["expected_behavior"]
                )

    def test_13_deployed_no_send_proof_is_pure_and_complete(self) -> None:
        proof = run_keysuri_graded_validation_no_send_proof()
        self.assertTrue(proof["ok"], proof)
        self.assertEqual(
            proof["side_effects"],
            {
                "model": 0,
                "image": 0,
                "smtp": 0,
                "customer": 0,
                "natural_mutation": 0,
                "scheduler_mutation": 0,
            },
        )
        self.assertEqual(proof["customer_send"], 0)
        by_name = {row["name"]: row for row in proof["cases"]}
        self.assertEqual(by_name["good_global"]["editorial_verdict"], "READY")
        self.assertEqual(
            by_name["bad_global_20260814_1231"]["editorial_verdict"], "POOR"
        )
        self.assertEqual(
            by_name["safe_review_owner_path"]["owner_delivery_behavior"],
            "SEND_OWNER_REVIEW_WARNING",
        )
        self.assertEqual(
            by_name["ungrounded_semantic_truncation"]["safety_verdict"],
            "UNSAFE",
        )
        self.assertEqual(by_name["unsupported_claim"]["safety_verdict"], "UNSAFE")

    def test_14_deployed_no_send_proof_endpoint_is_internal_and_pure(self) -> None:
        from fastapi.testclient import TestClient
        from main import app

        with mock.patch.dict(
            os.environ, {"GENIE_INTERNAL_JOB_TOKEN": "graded-proof-test-token"}, clear=False
        ):
            client = TestClient(app)
            self.assertEqual(
                client.post("/internal/jobs/keysuri-graded-validation-proof").status_code,
                403,
            )
            response = client.post(
                "/internal/jobs/keysuri-graded-validation-proof",
                headers={"X-Genie-Internal-Job-Token": "graded-proof-test-token"},
            )
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["side_effects"]["smtp"], 0)
        self.assertEqual(payload["customer_send"], 0)


if __name__ == "__main__":
    unittest.main()
