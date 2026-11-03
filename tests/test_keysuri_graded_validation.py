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
                post_render_qa=_qa("global_visible_repeated_template_skeleton_blocked"),
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

    def test_05b_global_english_surface_sends_korean_notice_only(self) -> None:
        findings = [
            {
                "issue_code": "global_visible_raw_english_prose_blocked",
                "field": "top5",
                "rank": rank,
                "before": f"English source prose {rank}",
            }
            for rank in (1, 2, 4)
        ]
        findings.extend(
            [
                {
                    "issue_code": "global_visible_semantic_truncation_blocked",
                    "field": "top5",
                    "rank": 1,
                },
                {
                    "issue_code": "global_visible_repeated_template_skeleton_blocked",
                    "field": "top5",
                },
                {
                    "issue_code": "global_visible_deep_dive_duplication_blocked",
                    "field": "deep_dive",
                },
                {
                    "issue_code": "global_visible_repeated_low_information_label",
                    "field": "visible_body",
                },
            ]
        )
        result = adjudicate_keysuri_owner_surface(
            program_id="keysuri_global_tech",
            subject=(
                "[운영자 검토][수동] Nvidia closes in on Hugging Face acquisition: "
                "8월 27일 글로벌 테크 브리핑"
            ),
            email_html="<html><body>broken candidate</body></html>",
            extra_findings=findings,
            owner_review_url="https://admin.example/r/poor",
        )

        self.assertEqual(result["editorial_verdict"], EDITORIAL_POOR)
        self.assertEqual(result["owner_delivery_behavior"], OWNER_SEND_POOR_NOTICE)
        self.assertEqual(
            result["owner_email_subject"],
            "[운영자 검토][품질 확인][수동] 8월 27일 글로벌 테크 브리핑",
        )
        self.assertNotIn("Nvidia", result["owner_email_subject"])
        self.assertNotIn("Hugging Face", result["owner_email_subject"])
        notice = result["owner_email_html"]
        self.assertEqual(notice.count("영문 원문 노출"), 1)
        self.assertEqual(notice.count("문장 잘림"), 1)
        self.assertEqual(notice.count("반복 문장 골격"), 1)
        self.assertEqual(notice.count("딥다이브 내용 중복"), 1)
        self.assertEqual(notice.count("판정 라벨 반복"), 1)
        self.assertNotIn("운영자 검토 필요", notice)
        self.assertNotIn("global_visible_", notice)
        self.assertIn("TOP 5 1·2·4위", notice)

    def test_05c_one_global_english_finding_is_poor_not_full_review(self) -> None:
        result = adjudicate_keysuri_owner_surface(
            program_id="keysuri_global_tech",
            subject="[운영자 검토] 한국어 제목",
            email_html="<html><body><article>English body must stay in Admin</article></body></html>",
            extra_findings=[
                {
                    "issue_code": "global_visible_raw_english_prose_blocked",
                    "field": "top5",
                    "rank": 3,
                }
            ],
            owner_review_url="https://admin.example/r/english",
        )

        self.assertEqual(result["editorial_verdict"], EDITORIAL_POOR)
        self.assertEqual(result["customer_approval_policy"], CUSTOMER_APPROVAL_UNAVAILABLE)
        self.assertNotIn("English body must stay", result["owner_email_html"])
        self.assertIn("영문 원문 노출", result["owner_email_html"])

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
            "reader_surface_enforced": True,
            "reader_surface_complete": True,
            "reader_surface_ready_item_count": 5,
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
        # Guard the original KeeSuri remediation itself. Inspecting the current
        # dirty worktree couples this historical scope proof to unrelated Today
        # development and creates a false full-suite failure.
        import subprocess

        try:
            changed = subprocess.run(
                [
                    "git",
                    "show",
                    "--format=",
                    "--name-only",
                    "ac3f4f917149a422aa7b43d9aca6ceab732600a3",
                    "--",
                    "today_*.py",
                ],
                cwd=ROOT,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
        except (subprocess.CalledProcessError, FileNotFoundError, OSError):
            changed = ""
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
            by_name["safe_english_notice_only_path"]["owner_delivery_behavior"],
            "SEND_OWNER_QUALITY_NOTICE",
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

    def test_15_canonical_adjudication_repaired_old_connector_vs_real_residual(self) -> None:
        # 1. Repaired old connector: older pass flagged ellipsis, but actual final structured field
        # and rendered surface prove the defect gone. Must NOT be counted as residual, stays traceable as repaired.
        repaired_result = adjudicate_keysuri_owner_surface(
            program_id="keysuri_korea_tech",
            subject="[운영자 검토] 정상 제목",
            email_html="<html><body><p>시장 변화를 확인합니다.</p></body></html>",
            structured_briefing={"one_line_checkpoint": "시장 변화를 확인합니다."},
            visible_quality_fields={
                "terminal_issue_codes": ["keysuri_korean_connector_ellipsis_blocked"],
                "visible_text_quality_samples": [
                    {
                        "path": "generated_briefing.one_line_checkpoint",
                        "sample": "시장…변화를 확인합니다.",
                        "repaired_sample": "시장 변화를 확인합니다.",
                        "validator_result": "repaired",
                    }
                ],
            },
        )
        self.assertEqual(repaired_result["safety_verdict"], SAFETY_SAFE)
        self.assertEqual(repaired_result["editorial_verdict"], EDITORIAL_READY)
        self.assertEqual(repaired_result["owner_delivery_behavior"], "SEND_OWNER_REVIEW")
        self.assertNotIn("keysuri_korean_connector_ellipsis_blocked", repaired_result["review_issue_codes"])
        self.assertIn("keysuri_korean_connector_ellipsis_blocked", repaired_result["repaired_issue_codes"])
        self.assertTrue(repaired_result["repair_history"])
        self.assertEqual(repaired_result["repair_history"][0]["before"], "시장…변화를 확인합니다.")
        self.assertEqual(repaired_result["repair_history"][0]["after"], "시장 변화를 확인합니다.")

        # 2. Genuine final connector residual: defect is still in structured field and rendered surface.
        # Must remain counted as residual, triggering warning/review.
        residual_result = adjudicate_keysuri_owner_surface(
            program_id="keysuri_korea_tech",
            subject="[운영자 검토] 정상 제목",
            email_html="<html><body><p>시장…변화를 확인합니다.</p></body></html>",
            structured_briefing={"one_line_checkpoint": "시장…변화를 확인합니다."},
            visible_quality_fields={
                "terminal_issue_codes": ["keysuri_korean_connector_ellipsis_blocked"],
                "visible_text_quality_samples": [
                    {
                        "path": "generated_briefing.one_line_checkpoint",
                        "sample": "시장…변화를 확인합니다.",
                        "validator_result": "block",
                    }
                ],
            },
        )
        self.assertEqual(residual_result["safety_verdict"], SAFETY_SAFE)
        self.assertEqual(residual_result["editorial_verdict"], EDITORIAL_REVIEW)
        self.assertEqual(residual_result["owner_delivery_behavior"], OWNER_SEND_WARNING)
        self.assertIn("keysuri_korean_connector_ellipsis_blocked", residual_result["review_issue_codes"])
        self.assertNotIn("keysuri_korean_connector_ellipsis_blocked", residual_result["repaired_issue_codes"])

        # 3. Six genuine residuals still trigger POOR (threshold 6 preserved, no waiver)
        six_residuals = adjudicate_keysuri_owner_surface(
            program_id="keysuri_korea_tech",
            subject="[운영자 검토] 정상 제목",
            email_html="<html><body><p>잔여 결함 표면</p></body></html>",
            extra_findings=[
                {"issue_code": "keysuri_korean_connector_ellipsis_blocked", "field": f"item_{i}", "before": f"결함…{i}"}
                for i in range(6)
            ],
        )
        self.assertEqual(six_residuals["editorial_verdict"], EDITORIAL_POOR)
        self.assertEqual(six_residuals["owner_delivery_behavior"], OWNER_SEND_POOR_NOTICE)

    def test_16_adversarial_stale_connector_and_residual_adjudication(self) -> None:
        # 1. Alias handling: old alias field vs real residual via alias
        # A. Alias 'checkpoint' maps to 'one_line_checkpoint': repaired when clean
        alias_repaired = adjudicate_keysuri_owner_surface(
            program_id="keysuri_korea_tech",
            subject="[운영자 검토] 정상 제목",
            email_html="<html><body><p>정상 확인 텍스트입니다.</p></body></html>",
            structured_briefing={"one_line_checkpoint": "정상 확인 텍스트입니다."},
            extra_findings=[
                {"issue_code": "keysuri_korean_connector_ellipsis_blocked", "field": "checkpoint", "before": "정상…결함"}
            ],
        )
        self.assertEqual(alias_repaired["editorial_verdict"], EDITORIAL_READY)
        self.assertNotIn("keysuri_korean_connector_ellipsis_blocked", alias_repaired["review_issue_codes"])
        self.assertIn("keysuri_korean_connector_ellipsis_blocked", alias_repaired["repaired_issue_codes"])

        # B. Real residual via alias: 'one_line_checkpoint' still has the defect
        alias_residual = adjudicate_keysuri_owner_surface(
            program_id="keysuri_korea_tech",
            subject="[운영자 검토] 정상 제목",
            email_html="<html><body><p>정상…결함 확인 텍스트입니다.</p></body></html>",
            structured_briefing={"one_line_checkpoint": "정상…결함 확인 텍스트입니다."},
            extra_findings=[
                {"issue_code": "keysuri_korean_connector_ellipsis_blocked", "field": "checkpoint", "before": "정상…결함"}
            ],
        )
        self.assertEqual(alias_residual["editorial_verdict"], EDITORIAL_REVIEW)
        self.assertIn("keysuri_korean_connector_ellipsis_blocked", alias_residual["review_issue_codes"])
        self.assertNotIn("keysuri_korean_connector_ellipsis_blocked", alias_residual["repaired_issue_codes"])

        # 2. Absent final evidence fails closed
        # A. structured_briefing is None: cannot prove repaired
        absent_briefing = adjudicate_keysuri_owner_surface(
            program_id="keysuri_korea_tech",
            subject="[운영자 검토] 정상 제목",
            email_html="<html><body><p>본문 표면</p></body></html>",
            structured_briefing=None,
            extra_findings=[
                {"issue_code": "keysuri_korean_connector_ellipsis_blocked", "field": "one_line_checkpoint", "before": "결함…1"}
            ],
        )
        self.assertEqual(absent_briefing["editorial_verdict"], EDITORIAL_REVIEW)
        self.assertIn("keysuri_korean_connector_ellipsis_blocked", absent_briefing["review_issue_codes"])

        # B. Field absent in structured_briefing: cannot prove repaired
        missing_field = adjudicate_keysuri_owner_surface(
            program_id="keysuri_korea_tech",
            subject="[운영자 검토] 정상 제목",
            email_html="<html><body><p>본문 표면</p></body></html>",
            structured_briefing={"other_field": "값"},
            extra_findings=[
                {"issue_code": "keysuri_korean_connector_ellipsis_blocked", "field": "generated_briefing.one_line_checkpoint", "before": "결함…1"}
            ],
        )
        self.assertEqual(missing_field["editorial_verdict"], EDITORIAL_REVIEW)
        self.assertIn("keysuri_korean_connector_ellipsis_blocked", missing_field["review_issue_codes"])

        # C. Structured field clean, but rendered surface (email_html) still leaks the defect
        surface_leak = adjudicate_keysuri_owner_surface(
            program_id="keysuri_korea_tech",
            subject="[운영자 검토] 정상 제목",
            email_html="<html><body><p>누출된 결함…1 표면</p></body></html>",
            structured_briefing={"one_line_checkpoint": "정상 수정 완료"},
            extra_findings=[
                {"issue_code": "keysuri_korean_connector_ellipsis_blocked", "field": "one_line_checkpoint", "before": "결함…1"}
            ],
        )
        self.assertEqual(surface_leak["editorial_verdict"], EDITORIAL_REVIEW)
        self.assertIn("keysuri_korean_connector_ellipsis_blocked", surface_leak["review_issue_codes"])

        # 3. Other families and unknown codes remain strict
        other_family = adjudicate_keysuri_owner_surface(
            program_id="keysuri_korea_tech",
            subject="[운영자 검토] 정상 제목",
            email_html="<html><body><p>본문 표면</p></body></html>",
            structured_briefing={"one_line_checkpoint": "정상 텍스트"},
            extra_findings=[
                {"issue_code": "unsupported_claim", "field": "one_line_checkpoint", "before": "불일치"}
            ],
        )
        self.assertEqual(other_family["safety_verdict"], SAFETY_UNSAFE)
        self.assertEqual(other_family["owner_delivery_behavior"], OWNER_HOLD_INCIDENT)

        unknown_code = adjudicate_keysuri_owner_surface(
            program_id="keysuri_korea_tech",
            subject="[운영자 검토] 정상 제목",
            email_html="<html><body><p>본문 표면</p></body></html>",
            structured_briefing={"one_line_checkpoint": "정상 텍스트"},
            extra_findings=[
                {"issue_code": "unknown_future_defect_code", "field": "one_line_checkpoint"}
            ],
        )
        self.assertEqual(unknown_code["safety_verdict"], SAFETY_INCONCLUSIVE)
        self.assertEqual(unknown_code["owner_delivery_behavior"], OWNER_HOLD_INCIDENT)

        # 4. Strict threshold 6 boundary: 5 residuals -> WARNING (REVIEW), 6 residuals -> POOR_NOTICE (POOR)
        five_residuals = adjudicate_keysuri_owner_surface(
            program_id="keysuri_korea_tech",
            subject="[운영자 검토] 정상 제목",
            email_html="<html><body><p>잔여 결함 표면</p></body></html>",
            extra_findings=[
                {"issue_code": "keysuri_korean_connector_ellipsis_blocked", "field": f"item_{i}", "before": f"결함…{i}"}
                for i in range(5)
            ],
        )
        self.assertEqual(five_residuals["editorial_verdict"], EDITORIAL_REVIEW)
        self.assertEqual(five_residuals["owner_delivery_behavior"], OWNER_SEND_WARNING)

        six_residuals_strict = adjudicate_keysuri_owner_surface(
            program_id="keysuri_korea_tech",
            subject="[운영자 검토] 정상 제목",
            email_html="<html><body><p>잔여 결함 표면</p></body></html>",
            extra_findings=[
                {"issue_code": "keysuri_korean_connector_ellipsis_blocked", "field": f"item_{i}", "before": f"결함…{i}"}
                for i in range(6)
            ],
        )
        self.assertEqual(six_residuals_strict["editorial_verdict"], EDITORIAL_POOR)
        self.assertEqual(six_residuals_strict["owner_delivery_behavior"], OWNER_SEND_POOR_NOTICE)

    def test_falsification_connector_defect_empty_rendered_and_unrepaired_field(self) -> None:
        from keysuri_quality_adjudication import _is_connector_defect_gone

        # Falsification check 1: Empty rendered surface cannot prove both final surfaces clean
        clean_structured = {"one_line_checkpoint": "시장 변화를 확인합니다."}
        empty_html_defect_gone = _is_connector_defect_gone(
            {"field": "one_line_checkpoint", "before": "시장…변화를 확인합니다."},
            structured_briefing=clean_structured,
            email_html="",
            subject="",
        )
        self.assertFalse(
            empty_html_defect_gone,
            "DEFECT: _is_connector_defect_gone returns True when email_html rendered surface is empty/blank",
        )

        # Falsification check 2: Repairable-but-currently-unrepaired connector field in final structured briefing
        # '시장…변화' is repairable so repair_korean_connector_ellipsis_text(field_val).blocked is False (repaired is True).
        # But the briefing text itself is STILL UNREPAIRED! A clipped or non-matching before string must not let it pass.
        unrepaired_structured = {"one_line_checkpoint": "시장…변화를 확인합니다."}
        unrepaired_field_defect_gone = _is_connector_defect_gone(
            {"field": "one_line_checkpoint", "before": "이슈…확산"},
            structured_briefing=unrepaired_structured,
            email_html="<html><body><p>시장 변화</p></body></html>",
            subject="정상 제목",
        )
        self.assertFalse(
            unrepaired_field_defect_gone,
            "DEFECT: _is_connector_defect_gone returns True for unrepaired connector defect when blocked=False and before-string does not match",
        )

    def test_canonical_stale_connector_normalization_exhaustive_surface_matrix(self) -> None:
        from keysuri_quality_adjudication import _is_connector_defect_gone

        clean_text = "국내 테크와 생태계의 주요 변화를 확인합니다."
        clean_structured = {"one_line_checkpoint": clean_text}
        valid_html = f"<html><body><article><p>{clean_text}</p></article></body></html>"
        valid_row = {
            "issue_code": "keysuri_korean_connector_ellipsis_blocked",
            "field": "one_line_checkpoint",
            "before": "국내 테크…생태계",
        }

        # 1. Both surfaces clean proves defect gone
        self.assertTrue(
            _is_connector_defect_gone(
                valid_row,
                structured_briefing=clean_structured,
                email_html=valid_html,
                subject="[운영자 검토] 정상 제목",
            )
        )

        # 2. Rendered surface missing / blank / whitespace-only fails closed
        for blank_html in ("", "   ", "\n\t\n", "<html><body>   </body></html>"):
            self.assertFalse(
                _is_connector_defect_gone(
                    valid_row,
                    structured_briefing=clean_structured,
                    email_html=blank_html,
                    subject="",
                ),
                f"Must fail closed on blank html: {blank_html!r}",
            )

        # 3. Missing structured briefing or not mapping fails closed
        self.assertFalse(
            _is_connector_defect_gone(
                valid_row,
                structured_briefing=None,
                email_html=valid_html,
                subject="제목",
            )
        )

        # 4. Missing structured field or empty field fails closed
        self.assertFalse(
            _is_connector_defect_gone(
                valid_row,
                structured_briefing={"other_section": clean_text},
                email_html=valid_html,
                subject="제목",
            )
        )
        self.assertFalse(
            _is_connector_defect_gone(
                valid_row,
                structured_briefing={"one_line_checkpoint": "   "},
                email_html=valid_html,
                subject="제목",
            )
        )

        # 5. CURRENT repairable-but-unrepaired connector in final structured briefing fails closed
        # Even if before string is clipped or completely different!
        unrepaired_briefing = {"one_line_checkpoint": "국내 테크…생태계의 주요 변화를 확인합니다."}
        for mismatch_before in ("완전다른결함", "국내", "", "   "):
            defect_row = {
                "issue_code": "keysuri_korean_connector_ellipsis_blocked",
                "field": "one_line_checkpoint",
                "before": mismatch_before,
            }
            self.assertFalse(
                _is_connector_defect_gone(
                    defect_row,
                    structured_briefing=unrepaired_briefing,
                    email_html=valid_html,
                    subject="제목",
                ),
                f"Must fail closed when structured field contains unrepaired connector: before={mismatch_before!r}",
            )

        # 6. Rendered surface contains before defect text fails closed
        rendered_leak_html = f"<html><body><p>국내 테크…생태계 잔여 결함</p></body></html>"
        self.assertFalse(
            _is_connector_defect_gone(
                valid_row,
                structured_briefing=clean_structured,
                email_html=rendered_leak_html,
                subject="제목",
            )
        )

        # 7. Adjudication flow: repaired old connector retains history, removes from review/terminal
        repaired_adj = adjudicate_keysuri_owner_surface(
            program_id="keysuri_korea_tech",
            subject="[운영자 검토] 정상 제목",
            email_html=valid_html,
            structured_briefing=clean_structured,
            extra_findings=[valid_row],
        )
        self.assertEqual(repaired_adj["safety_verdict"], SAFETY_SAFE)
        self.assertEqual(repaired_adj["editorial_verdict"], EDITORIAL_READY)
        self.assertEqual(repaired_adj["owner_delivery_behavior"], "SEND_OWNER_REVIEW")
        self.assertNotIn("keysuri_korean_connector_ellipsis_blocked", repaired_adj["review_issue_codes"])
        self.assertIn("keysuri_korean_connector_ellipsis_blocked", repaired_adj["repaired_issue_codes"])
        self.assertTrue(repaired_adj["repair_history"])
        self.assertEqual(repaired_adj["repair_history"][0]["before"], "국내 테크…생태계")
        self.assertEqual(repaired_adj["repair_history"][0]["after"], clean_text)

        # 8. Genuine residuals threshold 6 and unknown codes remain strict
        res_5 = adjudicate_keysuri_owner_surface(
            program_id="keysuri_korea_tech",
            subject="[운영자 검토] 제목",
            email_html=valid_html,
            structured_briefing=unrepaired_briefing,
            extra_findings=[
                {"issue_code": "keysuri_korean_connector_ellipsis_blocked", "field": f"item_{i}", "before": f"결함…{i}"}
                for i in range(5)
            ],
        )
        self.assertEqual(res_5["editorial_verdict"], EDITORIAL_REVIEW)
        self.assertEqual(res_5["owner_delivery_behavior"], OWNER_SEND_WARNING)

        res_6 = adjudicate_keysuri_owner_surface(
            program_id="keysuri_korea_tech",
            subject="[운영자 검토] 제목",
            email_html=valid_html,
            structured_briefing=unrepaired_briefing,
            extra_findings=[
                {"issue_code": "keysuri_korean_connector_ellipsis_blocked", "field": f"item_{i}", "before": f"결함…{i}"}
                for i in range(6)
            ],
        )
        self.assertEqual(res_6["editorial_verdict"], EDITORIAL_POOR)
        self.assertEqual(res_6["owner_delivery_behavior"], OWNER_SEND_POOR_NOTICE)

        unsafe_adj = adjudicate_keysuri_owner_surface(
            program_id="keysuri_korea_tech",
            subject="[운영자 검토] 제목",
            email_html=valid_html,
            structured_briefing=clean_structured,
            extra_findings=[{"issue_code": "unsupported_claim", "field": "checkpoint"}],
        )
        self.assertEqual(unsafe_adj["safety_verdict"], SAFETY_UNSAFE)
        self.assertEqual(unsafe_adj["owner_delivery_behavior"], OWNER_HOLD_INCIDENT)


if __name__ == "__main__":
    unittest.main()
