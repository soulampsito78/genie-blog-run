"""Minimal tests for owner admin routes and artifact listing."""
from __future__ import annotations

import json
import os
import re
import unittest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from admin_store import (
    EXECUTABLE_REISSUE_SCOPE,
    admin_runs_dir,
    apply_reissue_child_metadata,
    approve_run,
    build_customer_delivery_admin_panel,
    load_run_artifact,
    mask_customer_email,
    save_run_artifact,
)
from main import app


def post_customer_approve_with_confirm(
    client: TestClient,
    run_id: str,
    *,
    note: str = "ok",
    include_checkbox: bool = True,
    include_nonce: bool = True,
    nonce_override: str | None = None,
):
    confirm_resp = client.get(f"/admin/runs/{run_id}/approve-confirm")
    nonce = nonce_override
    if include_nonce and nonce is None:
        match = re.search(r'name="approve_nonce" value="([^"]+)"', confirm_resp.text)
        nonce = match.group(1) if match else ""
    data: dict[str, str] = {"approve_note": note}
    if include_nonce:
        data["approve_nonce"] = nonce or ""
    if include_checkbox:
        data["customer_send_confirm"] = "1"
    return client.post(f"/admin/runs/{run_id}/approve", data=data, follow_redirects=False)


class AdminRoutesTests(unittest.TestCase):
    def setUp(self) -> None:
        self._prev_pwd = os.environ.get("GENIE_ADMIN_PASSWORD")
        os.environ["GENIE_ADMIN_PASSWORD"] = "test-admin-secret"
        self.client = TestClient(app)

    def tearDown(self) -> None:
        if self._prev_pwd is None:
            os.environ.pop("GENIE_ADMIN_PASSWORD", None)
        else:
            os.environ["GENIE_ADMIN_PASSWORD"] = self._prev_pwd

    def test_admin_disabled_without_password(self) -> None:
        os.environ.pop("GENIE_ADMIN_PASSWORD", None)
        client = TestClient(app)
        resp = client.get("/admin")
        self.assertEqual(resp.status_code, 503)
        self.assertIn("GENIE_ADMIN_PASSWORD", resp.text)

    def test_wrong_password_rejected(self) -> None:
        resp = self.client.post("/admin/login", data={"password": "wrong"})
        self.assertEqual(resp.status_code, 401)

    def test_correct_password_sets_session(self) -> None:
        resp = self.client.post(
            "/admin/login",
            data={"password": "test-admin-secret"},
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 303)
        self.assertIn("genie_admin_session", resp.cookies)
        runs = self.client.get("/admin/runs")
        self.assertEqual(runs.status_code, 200)

    def test_run_list_reads_json_artifacts(self) -> None:
        self.client.post("/admin/login", data={"password": "test-admin-secret"})
        run_id = save_run_artifact(
            {
                "run_id": "20260530_120000_today_genie_aabbccdd",
                "mode": "today_genie",
                "created_at": "2026-05-30T12:00:00+09:00",
                "validation_result": "pass",
                "workflow_status": "validated",
                "email_sent": True,
                "response_status": 200,
                "reason_summary": "ok",
            },
            email_html="<p>test email</p>",
        )
        path = admin_runs_dir() / f"{run_id}.json"
        self.assertTrue(path.is_file())
        resp = self.client.get("/admin/runs")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(run_id, resp.text)

    def test_runs_list_shows_beta_recipients_nav_link(self) -> None:
        self.client.post("/admin/login", data={"password": "test-admin-secret"})
        resp = self.client.get("/admin/runs")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("베타 고객 수신자 관리", resp.text)
        self.assertIn('href="/admin/customer-recipients"', resp.text)
        self.assertIn('href="/admin/costs"', resp.text)

    def test_admin_costs_requires_login(self) -> None:
        resp = self.client.get("/admin/costs", follow_redirects=False)
        self.assertEqual(resp.status_code, 303)
        self.assertIn("/admin", resp.headers.get("location", ""))

    def test_admin_costs_page_and_csv_download(self) -> None:
        self.client.post("/admin/login", data={"password": "test-admin-secret"})
        run_id = "20260709_183000_keysuri_korea_tech_aabbccdd"
        save_run_artifact(
            {
                "run_id": run_id,
                "mode": "keysuri_korea_tech",
                "created_at": "2026-07-09T18:30:00+09:00",
                "validation_result": "pass",
                "workflow_status": "validated",
                "email_sent": True,
                "customer_delivery_status": "not_sent",
                "cost_estimate": {
                    "estimate_only": True,
                    "service_family": "keysuri",
                    "program_id": "keysuri_korea_tech",
                    "run_id": run_id,
                    "model": {"text_model": "gemini-2.5-flash", "image_model": None},
                    "usage": {
                        "prompt_token_count": 1000,
                        "candidates_token_count": 2000,
                        "generated_image_count": 0,
                    },
                    "components": {
                        "text_input_cost_usd": 0.0003,
                        "text_output_cost_usd": 0.005,
                        "text_total_cost_usd": 0.0053,
                    },
                    "total_cost_usd": 0.0053,
                    "total_cost_krw": None,
                    "cost_estimate_status": "partial",
                    "pricing_source": "env",
                    "price_env_configured": True,
                    "missing_price_env": ["GENIE_COST_GEMINI_2_5_FLASH_IMAGE_USD_PER_IMAGE"],
                    "pricing_note": "estimate only; text cost calculated; image cost not configured",
                },
            }
        )
        from admin_cost_ledger import save_cost_record_best_effort

        save_cost_record_best_effort(load_run_artifact(run_id) or {})
        page = self.client.get("/admin/costs")
        self.assertEqual(page.status_code, 200)
        self.assertIn(run_id, page.text)
        csv_resp = self.client.get("/admin/costs/ledger.csv?month=2026-07")
        self.assertEqual(csv_resp.status_code, 200)
        self.assertIn("text/csv", csv_resp.headers.get("content-type", ""))
        self.assertIn(run_id, csv_resp.text)
        self.assertIn("0.0053", csv_resp.text)
        target_rows = [
            line for line in csv_resp.text.splitlines() if run_id in line and "0.0053" in line
        ]
        self.assertTrue(target_rows)
        self.assertIn("GENIE_COST_GEMINI_2_5_FLASH_IMAGE_USD_PER_IMAGE", target_rows[-1])
        self.assertNotIn("GENIE_COST_KRW_PER_USD", target_rows[-1])

    def test_run_detail_cost_estimate_shows_usd_partial_labels(self) -> None:
        self.client.post("/admin/login", data={"password": "test-admin-secret"})
        run_id = "20260709_183100_keysuri_korea_tech_aabbccdd"
        save_run_artifact(
            {
                "run_id": run_id,
                "mode": "keysuri_korea_tech",
                "created_at": "2026-07-09T18:31:00+09:00",
                "validation_result": "pass",
                "workflow_status": "validated",
                "email_sent": True,
                "customer_delivery_status": "not_sent",
                "cost_estimate": {
                    "estimate_only": True,
                    "service_family": "keysuri",
                    "program_id": "keysuri_korea_tech",
                    "run_id": run_id,
                    "model": {
                        "text_model": "gemini-2.5-flash",
                        "image_model": "gemini-2.5-flash-image",
                    },
                    "usage": {
                        "prompt_token_count": 12404,
                        "candidates_token_count": 5651,
                        "thoughts_token_count": 3924,
                        "generated_image_count": 2,
                    },
                    "components": {
                        "text_input_cost_usd": 0.003721,
                        "text_output_cost_usd": 0.014128,
                        "text_thoughts_cost_usd": 0.009810,
                        "text_total_cost_usd": 0.027659,
                        "image_cost_usd": None,
                    },
                    "model_pricing": {
                        "image_pricing_status": "unsupported_or_unconfigured",
                    },
                    "total_cost_usd": 0.027659,
                    "total_cost_krw": None,
                    "cost_estimate_status": "partial",
                    "pricing_source": "env",
                    "price_env_configured": True,
                    "missing_price_env": ["GENIE_COST_GEMINI_2_5_FLASH_IMAGE_USD_PER_IMAGE"],
                    "pricing_note": "estimate only; text cost calculated; image cost not configured",
                },
            }
        )
        resp = self.client.get(f"/admin/runs/{run_id}")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Cost Estimate", resp.text)
        self.assertIn("Text input cost USD", resp.text)
        self.assertIn("Text total cost USD", resp.text)
        self.assertIn("Total known cost USD", resp.text)
        self.assertIn("unconfigured / not calculated", resp.text)
        self.assertIn("partial", resp.text)
        self.assertIn("0.027659", resp.text)

    def test_run_detail_shows_beta_recipients_nav_link(self) -> None:
        self.client.post("/admin/login", data={"password": "test-admin-secret"})
        run_id = "20260530_120100_today_genie_aabbccdd"
        save_run_artifact(
            {
                "run_id": run_id,
                "mode": "today_genie",
                "validation_result": "pass",
                "workflow_status": "validated",
                "email_sent": False,
                "response_status": 200,
                "reason_summary": "ok",
            }
        )
        resp = self.client.get(f"/admin/runs/{run_id}")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("베타 고객 수신자 관리", resp.text)
        self.assertIn('href="/admin/customer-recipients"', resp.text)

    def test_reissue_requires_login(self) -> None:
        run_id = "20260530_120000_today_genie_aabbccdd"
        save_run_artifact(
            {
                "run_id": run_id,
                "mode": "today_genie",
                "created_at": "2026-05-30T12:00:00+09:00",
                "validation_result": "pass",
                "workflow_status": "validated",
                "email_sent": False,
                "response_status": 200,
                "reason_summary": "ok",
            }
        )
        resp = self.client.post(
            f"/admin/runs/{run_id}/reissue",
            data={
                "reason_option": "기타",
                "reason_note": "",
                "reissue_scope": EXECUTABLE_REISSUE_SCOPE,
            },
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 303)
        self.assertIn("/admin", resp.headers.get("location", ""))

    def test_admin_detail_includes_reissue_scope_labels(self) -> None:
        self.client.post("/admin/login", data={"password": "test-admin-secret"})
        run_id = "20260530_121000_today_genie_aabbccdd"
        save_run_artifact(
            {
                "run_id": run_id,
                "mode": "today_genie",
                "created_at": "2026-05-30T12:10:00+09:00",
                "validation_result": "pass",
                "workflow_status": "validated",
                "email_sent": False,
                "response_status": 200,
                "reason_summary": "ok",
            }
        )
        resp = self.client.get(f"/admin/runs/{run_id}")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("본문만 재발행", resp.text)
        self.assertIn("이미지만 재발행", resp.text)
        self.assertIn("본문·이미지 모두 재발행", resp.text)
        self.assertIn("운영자 검토 메일", resp.text)
        self.assertIn("고객 이메일 발송 상태", resp.text)
        self.assertIn("선택한 범위만 서버에서 재발행합니다.", resp.text)
        self.assertIn("고객 최종 발송은 별도 승인 전까지 수행되지 않습니다.", resp.text)

    def test_today_reissue_scope_radios_match_backend_support(self) -> None:
        self.client.post("/admin/login", data={"password": "test-admin-secret"})
        run_id = "20260530_121100_today_genie_aabbccdd"
        save_run_artifact(
            {
                "run_id": run_id,
                "mode": "today_genie",
                "validation_result": "pass",
                "workflow_status": "validated",
                "email_sent": False,
                "response_status": 200,
                "reason_summary": "ok",
            }
        )
        resp = self.client.get(f"/admin/runs/{run_id}")
        self.assertEqual(resp.status_code, 200)
        self.assertRegex(resp.text, r'value="body_only"[^>]*\bdisabled\b')
        self.assertRegex(resp.text, r'value="image_only"[^>]*\bdisabled\b')
        self.assertRegex(resp.text, r'value="body_and_image"[^>]*\bchecked\b')
        self.assertIn('name="reissue_scope"', resp.text)
        self.assertIn('class="radio-scope"', resp.text)
        self.assertIn('class="radio-helper"', resp.text)

    def test_keysuri_reissue_scope_radios_enable_all_scopes(self) -> None:
        self.client.post("/admin/login", data={"password": "test-admin-secret"})
        run_id = "20260530_121101_keysuri_korea_tech_aabbccdd"
        save_run_artifact(
            {
                "run_id": run_id,
                "mode": "keysuri_korea_tech",
                "program_id": "keysuri_korea_tech",
                "validation_result": "pass",
                "workflow_status": "validated",
                "email_sent": False,
                "response_status": 200,
                "reason_summary": "ok",
            }
        )
        resp = self.client.get(f"/admin/runs/{run_id}")
        self.assertEqual(resp.status_code, 200)
        self.assertNotRegex(resp.text, r'value="body_only"[^>]*\bdisabled\b')
        self.assertNotRegex(resp.text, r'value="image_only"[^>]*\bdisabled\b')
        # No image_only fallback: full scope stays the default even though
        # image_only is also enabled for this mode.
        self.assertRegex(resp.text, r'value="body_and_image"[^>]*\bchecked\b')
        self.assertNotRegex(resp.text, r'value="image_only"[^>]*\bchecked\b')
        self.assertNotRegex(resp.text, r'value="body_and_image"[^>]*\bdisabled\b')
        self.assertIn("중복·부적합 뉴스를 제외하고 후보군의 다음 순위 뉴스로 본문을 다시 생성합니다. 기존 이미지는 유지됩니다.", resp.text)
        self.assertIn("이미지 prompt와 이미지 산출물만 다시 생성합니다", resp.text)
        self.assertIn("뉴스 수집부터 다시 수행하고, 본문과 이미지 산출물을 모두 새로 생성합니다.", resp.text)
        self.assertIn("이미지 품질 이슈", resp.text)
        self.assertIn("reissue-reason-select", resp.text)

    def test_reason_dropdown_body_only_default_is_news_duplicate(self) -> None:
        from admin_routes import REISSUE_REASON_OPTIONS_BY_SCOPE
        reasons = REISSUE_REASON_OPTIONS_BY_SCOPE["body_only"]
        self.assertEqual(reasons[0], "뉴스 중복 이슈")

    def test_reason_dropdown_image_only_default_is_image_quality(self) -> None:
        from admin_routes import REISSUE_REASON_OPTIONS_BY_SCOPE
        reasons = REISSUE_REASON_OPTIONS_BY_SCOPE["image_only"]
        self.assertEqual(reasons[0], "이미지 품질 이슈")

    def test_reason_dropdown_body_and_image_default_is_full_regen(self) -> None:
        from admin_routes import REISSUE_REASON_OPTIONS_BY_SCOPE
        reasons = REISSUE_REASON_OPTIONS_BY_SCOPE["body_and_image"]
        self.assertEqual(reasons[0], "전체 방향 수정 요청")

    def test_admin_pages_include_viewport_meta(self) -> None:
        login_resp = self.client.get("/admin")
        self.assertEqual(login_resp.status_code, 200)
        self.assertIn('name="viewport"', login_resp.text)
        self.assertIn("width=device-width", login_resp.text)
        self.client.post("/admin/login", data={"password": "test-admin-secret"})
        runs_resp = self.client.get("/admin/runs")
        self.assertEqual(runs_resp.status_code, 200)
        self.assertIn('name="viewport"', runs_resp.text)
        self.assertIn('class="table-wrap"', runs_resp.text)
        run_id = "20260530_121200_today_genie_aabbccdd"
        save_run_artifact(
            {
                "run_id": run_id,
                "mode": "today_genie",
                "validation_result": "pass",
                "workflow_status": "validated",
                "email_sent": False,
                "response_status": 200,
                "reason_summary": "ok",
            }
        )
        detail_resp = self.client.get(f"/admin/runs/{run_id}")
        self.assertEqual(detail_resp.status_code, 200)
        self.assertIn('name="viewport"', detail_resp.text)
        self.assertIn('class="page-head"', detail_resp.text)

    def test_admin_detail_labels_smtp_accepted_not_delivery_confirmed(self) -> None:
        self.client.post("/admin/login", data={"password": "test-admin-secret"})
        run_id = "20260530_122000_today_genie_aabbccdd"
        save_run_artifact(
            {
                "run_id": run_id,
                "mode": "today_genie",
                "validation_result": "pass",
                "workflow_status": "validated",
                "customer_delivery_status": "smtp_accepted",
                "customer_sent_at": "2026-05-30T12:20:00+09:00",
                "email_sent": True,
                "response_status": 200,
                "reason_summary": "ok",
            }
        )
        resp = self.client.get(f"/admin/runs/{run_id}")
        self.assertIn("고객 이메일 발송 상태", resp.text)
        self.assertIn("PASS", resp.text)
        self.assertIn("발송 접수 완료", resp.text)
        self.assertIn("SMTP 접수", resp.text)
        self.assertNotIn("전달 확인", resp.text)

    @patch("admin_routes.execute_orchestrator_run")
    def test_reissue_text_and_image_executes_and_persists_scope(self, mock_exec) -> None:
        child_id = "20260530_130000_today_genie_11223344"
        mock_exec.return_value = (child_id, object(), True)
        self.client.post("/admin/login", data={"password": "test-admin-secret"})
        parent_id = "20260530_120000_today_genie_aabbccdd"
        save_run_artifact(
            {
                "run_id": parent_id,
                "mode": "today_genie",
                "created_at": "2026-05-30T12:00:00+09:00",
                "validation_result": "pass",
                "workflow_status": "validated",
                "email_sent": True,
                "response_status": 200,
                "reason_summary": "ok",
            }
        )
        save_run_artifact(
            {
                "run_id": child_id,
                "mode": "today_genie",
                "parent_run_id": parent_id,
                "validation_result": "pass",
                "workflow_status": "validated",
                "email_sent": True,
                "response_status": 200,
                "reason_summary": "ok",
            }
        )
        resp = self.client.post(
            f"/admin/runs/{parent_id}/reissue",
            data={
                "reason_option": "구성 품질 이슈",
                "reason_note": "retry",
                "reissue_scope": EXECUTABLE_REISSUE_SCOPE,
            },
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 303)
        mock_exec.assert_called_once()
        kwargs = mock_exec.call_args.kwargs
        self.assertTrue(kwargs.get("admin_reissue"))
        self.assertEqual(kwargs.get("parent_run_id"), parent_id)
        child = load_run_artifact(child_id) or {}
        self.assertEqual(child.get("reissue_scope"), EXECUTABLE_REISSUE_SCOPE)
        self.assertTrue(child.get("reissue_scope_supported"))
        self.assertEqual(child.get("reissue_scope_status"), "executed")
        self.assertEqual(child.get("reissue_reason_code"), "구성 품질 이슈")
        self.assertEqual(child.get("reissue_reason_note"), "retry")
        parent = load_run_artifact(parent_id) or {}
        self.assertEqual(parent.get("last_reissue_scope_requested"), EXECUTABLE_REISSUE_SCOPE)
        self.assertEqual(parent.get("last_reissue_child_run_id"), child_id)

    @patch("admin_routes.execute_orchestrator_run")
    def test_reissue_body_only_blocked_for_today(self, mock_exec) -> None:
        self.client.post("/admin/login", data={"password": "test-admin-secret"})
        parent_id = "20260530_120100_today_genie_aabbccdd"
        save_run_artifact(
            {
                "run_id": parent_id,
                "mode": "today_genie",
                "validation_result": "pass",
                "workflow_status": "validated",
                "email_sent": True,
                "response_status": 200,
                "reason_summary": "ok",
                "reissue_count": 0,
            }
        )
        resp = self.client.post(
            f"/admin/runs/{parent_id}/reissue",
            data={
                "reason_option": "기타",
                "reason_note": "",
                "reissue_scope": "body_only",
            },
            follow_redirects=True,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn("invalid_reissue_scope", str(resp.url))
        self.assertIn("재발행 범위가 올바르지 않습니다", resp.text)
        self.assertNotIn("sent_archived", resp.text)
        mock_exec.assert_not_called()
        parent = load_run_artifact(parent_id) or {}
        self.assertEqual(parent.get("reissue_count", 0), 0)

    @patch("admin_routes.execute_orchestrator_run")
    def test_reissue_legacy_text_only_alias_blocked_for_today(self, mock_exec) -> None:
        # Backward compatibility: legacy "text_only" must still be accepted and
        # normalized to "body_only", which today_genie still does not execute.
        self.client.post("/admin/login", data={"password": "test-admin-secret"})
        parent_id = "20260530_120105_today_genie_aabbccdd"
        save_run_artifact(
            {
                "run_id": parent_id,
                "mode": "today_genie",
                "validation_result": "pass",
                "workflow_status": "validated",
                "email_sent": True,
                "response_status": 200,
                "reason_summary": "ok",
                "reissue_count": 0,
            }
        )
        resp = self.client.post(
            f"/admin/runs/{parent_id}/reissue",
            data={
                "reason_option": "기타",
                "reason_note": "",
                "reissue_scope": "text_only",
            },
            follow_redirects=True,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn("invalid_reissue_scope", str(resp.url))
        mock_exec.assert_not_called()
        parent = load_run_artifact(parent_id) or {}
        self.assertEqual(parent.get("reissue_count", 0), 0)

    @patch("admin_routes.execute_orchestrator_run")
    def test_reissue_image_only_blocked_for_today(self, mock_exec) -> None:
        self.client.post("/admin/login", data={"password": "test-admin-secret"})
        parent_id = "20260530_120200_today_genie_aabbccdd"
        save_run_artifact(
            {
                "run_id": parent_id,
                "mode": "today_genie",
                "validation_result": "pass",
                "workflow_status": "validated",
                "email_sent": True,
                "response_status": 200,
                "reason_summary": "ok",
                "reissue_count": 0,
            }
        )
        resp = self.client.post(
            f"/admin/runs/{parent_id}/reissue",
            data={
                "reason_option": "이미지 품질 이슈",
                "reason_note": "",
                "reissue_scope": "image_only",
            },
            follow_redirects=True,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn("invalid_reissue_scope", str(resp.url))
        self.assertIn("재발행 범위가 올바르지 않습니다", resp.text)
        mock_exec.assert_not_called()
        parent = load_run_artifact(parent_id) or {}
        self.assertEqual(parent.get("reissue_count", 0), 0)

    @patch("admin_routes.execute_orchestrator_run")
    @patch("admin_routes.run_keysuri_image_only_reissue")
    def test_reissue_image_only_executes_keysuri_helper_only(self, mock_image_only, mock_exec) -> None:
        child_id = "20260530_130100_keysuri_korea_tech_11223344"
        mock_image_only.return_value = {
            "ok": True,
            "run_id": child_id,
            "regen_type": "image_only",
            "email_sent": True,
        }
        self.client.post("/admin/login", data={"password": "test-admin-secret"})
        parent_id = "20260530_120201_keysuri_korea_tech_aabbccdd"
        save_run_artifact(
            {
                "run_id": parent_id,
                "mode": "keysuri_korea_tech",
                "program_id": "keysuri_korea_tech",
                "validation_result": "pass",
                "workflow_status": "validated",
                "email_sent": True,
                "response_status": 200,
                "reason_summary": "ok",
                "reissue_count": 0,
            },
            email_html='<html><body><p>original body</p><img src="cid:keysuri_topshot_korea_20260530"></body></html>',
        )
        resp = self.client.post(
            f"/admin/runs/{parent_id}/reissue",
            data={
                "reason_option": "이미지 품질 이슈",
                "reason_note": "replace only images",
                "reissue_scope": "image_only",
            },
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 303)
        self.assertIn(child_id, resp.headers.get("location", ""))
        mock_image_only.assert_called_once()
        self.assertEqual(mock_image_only.call_args.args[0], parent_id)
        self.assertEqual(mock_image_only.call_args.kwargs["reissue_reason_code"], "이미지 품질 이슈")
        self.assertEqual(mock_image_only.call_args.kwargs["reissue_reason_note"], "replace only images")
        mock_exec.assert_not_called()
        parent = load_run_artifact(parent_id) or {}
        self.assertEqual(parent.get("reissue_count", 0), 0)

    @patch("admin_routes.execute_orchestrator_run")
    @patch("admin_routes.run_keysuri_text_only_reissue")
    def test_reissue_body_only_executes_keysuri_helper_only(self, mock_text_only, mock_exec) -> None:
        child_id = "20260530_130101_keysuri_korea_tech_11223344"
        mock_text_only.return_value = {
            "ok": True,
            "run_id": child_id,
            "regen_type": "body_only",
            "email_sent": True,
        }
        self.client.post("/admin/login", data={"password": "test-admin-secret"})
        parent_id = "20260530_120202_keysuri_korea_tech_aabbccdd"
        save_run_artifact(
            {
                "run_id": parent_id,
                "mode": "keysuri_korea_tech",
                "program_id": "keysuri_korea_tech",
                "validation_result": "pass",
                "workflow_status": "validated",
                "email_sent": True,
                "response_status": 200,
                "reason_summary": "ok",
                "reissue_count": 0,
            },
            email_html="<html><body><p>original body</p></body></html>",
        )
        resp = self.client.post(
            f"/admin/runs/{parent_id}/reissue",
            data={
                "reason_option": "제목 수정 요청",
                "reason_note": "refresh copy",
                "reissue_scope": "body_only",
            },
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 303)
        self.assertIn(child_id, resp.headers.get("location", ""))
        mock_text_only.assert_called_once()
        self.assertEqual(mock_text_only.call_args.args[0], parent_id)
        self.assertEqual(mock_text_only.call_args.kwargs["reissue_reason_code"], "제목 수정 요청")
        self.assertEqual(mock_text_only.call_args.kwargs["reissue_reason_note"], "refresh copy")
        mock_exec.assert_not_called()

    @patch("admin_routes.execute_orchestrator_run")
    @patch("admin_routes.run_keysuri_text_only_reissue")
    def test_reissue_legacy_text_only_alias_executes_keysuri_helper_only(self, mock_text_only, mock_exec) -> None:
        # Backward compatibility: legacy "text_only" form value must still be
        # accepted and dispatched the same as canonical "body_only".
        child_id = "20260530_130103_keysuri_korea_tech_11223344"
        mock_text_only.return_value = {
            "ok": True,
            "run_id": child_id,
            "regen_type": "body_only",
            "email_sent": True,
        }
        self.client.post("/admin/login", data={"password": "test-admin-secret"})
        parent_id = "20260530_120204_keysuri_korea_tech_aabbccdd"
        save_run_artifact(
            {
                "run_id": parent_id,
                "mode": "keysuri_korea_tech",
                "program_id": "keysuri_korea_tech",
                "validation_result": "pass",
                "workflow_status": "validated",
                "email_sent": True,
                "response_status": 200,
                "reason_summary": "ok",
                "reissue_count": 0,
            },
            email_html="<html><body><p>original body</p></body></html>",
        )
        resp = self.client.post(
            f"/admin/runs/{parent_id}/reissue",
            data={
                "reason_option": "제목 수정 요청",
                "reason_note": "refresh copy",
                "reissue_scope": "text_only",
            },
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 303)
        self.assertIn(child_id, resp.headers.get("location", ""))
        mock_text_only.assert_called_once()
        mock_exec.assert_not_called()

    @patch("admin_routes.execute_orchestrator_run")
    @patch("admin_routes.run_keysuri_text_and_image_reissue")
    def test_reissue_body_and_image_executes_keysuri_helper_only(self, mock_text_and_image, mock_exec) -> None:
        child_id = "20260530_130102_keysuri_global_tech_11223344"
        mock_text_and_image.return_value = {
            "ok": True,
            "run_id": child_id,
            "regen_type": "body_and_image",
            "email_sent": True,
        }
        self.client.post("/admin/login", data={"password": "test-admin-secret"})
        parent_id = "20260530_120203_keysuri_global_tech_aabbccdd"
        save_run_artifact(
            {
                "run_id": parent_id,
                "mode": "keysuri_global_tech",
                "program_id": "keysuri_global_tech",
                "validation_result": "pass",
                "workflow_status": "validated",
                "email_sent": True,
                "response_status": 200,
                "reason_summary": "ok",
                "reissue_count": 0,
            },
            email_html="<html><body><p>original body</p></body></html>",
        )
        resp = self.client.post(
            f"/admin/runs/{parent_id}/reissue",
            data={
                "reason_option": "전체 방향 수정 요청",
                "reason_note": "reset package",
                "reissue_scope": "body_and_image",
            },
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 303)
        self.assertIn(child_id, resp.headers.get("location", ""))
        mock_text_and_image.assert_called_once()
        self.assertEqual(mock_text_and_image.call_args.args[0], parent_id)
        self.assertEqual(mock_text_and_image.call_args.kwargs["reissue_reason_code"], "전체 방향 수정 요청")
        self.assertEqual(mock_text_and_image.call_args.kwargs["reissue_reason_note"], "reset package")
        mock_exec.assert_not_called()

    @patch("admin_routes.execute_orchestrator_run")
    @patch("admin_routes.run_keysuri_text_and_image_reissue")
    def test_keysuri_reissue_value_error_returns_safe_failure_panel(self, mock_text_and_image, mock_exec) -> None:
        mock_text_and_image.side_effect = ValueError("raw internal detail")
        self.client.post("/admin/login", data={"password": "test-admin-secret"})
        parent_id = "20260530_120207_keysuri_global_tech_aabbccdd"
        save_run_artifact(
            {
                "run_id": parent_id,
                "mode": "keysuri_global_tech",
                "program_id": "keysuri_global_tech",
                "validation_result": "pass",
                "workflow_status": "validated",
                "email_sent": True,
                "response_status": 200,
                "reason_summary": "ok",
                "reissue_count": 0,
            },
            email_html="<html><body><p>original body</p></body></html>",
        )
        resp = self.client.post(
            f"/admin/runs/{parent_id}/reissue",
            data={
                "reason_option": "전체 방향 수정 요청",
                "reason_note": "reset package",
                "reissue_scope": "body_and_image",
            },
            follow_redirects=False,
        )

        self.assertEqual(resp.status_code, 200)
        self.assertIn("keysuri_reissue_execution", resp.text)
        # Raw exception type/message must not surface on the operator screen;
        # only a generic safe code is shown.
        self.assertIn("safe_error_code=keysuri_reissue_execution_error", resp.text)
        self.assertNotIn("ValueError", resp.text)
        self.assertNotIn("raw internal detail", resp.text)
        mock_text_and_image.assert_called_once()
        mock_exec.assert_not_called()

    @patch("admin_routes.execute_orchestrator_run")
    @patch("admin_routes.run_keysuri_text_and_image_reissue")
    def test_keysuri_reissue_result_validation_hides_raw_detail(self, mock_text_and_image, mock_exec) -> None:
        mock_text_and_image.return_value = {
            "ok": False,
            "program_id": "keysuri_global_tech",
            "error": (
                "Gemini parse failed (parsed_invalid): "
                "top_5_news.items must contain exactly 5 entries, got 2"
            ),
        }
        self.client.post("/admin/login", data={"password": "test-admin-secret"})
        parent_id = "20260530_120208_keysuri_global_tech_aabbccdd"
        save_run_artifact(
            {
                "run_id": parent_id,
                "mode": "keysuri_global_tech",
                "program_id": "keysuri_global_tech",
                "validation_result": "pass",
                "workflow_status": "validated",
                "email_sent": True,
                "response_status": 200,
                "reason_summary": "ok",
                "reissue_count": 0,
            },
            email_html="<html><body><p>original body</p></body></html>",
        )
        resp = self.client.post(
            f"/admin/runs/{parent_id}/reissue",
            data={
                "reason_option": "뉴스 중복 이슈",
                "reason_note": "",
                "reissue_scope": "body_and_image",
            },
            follow_redirects=False,
        )

        self.assertEqual(resp.status_code, 200)
        self.assertIn("keysuri_reissue_result_validation", resp.text)
        self.assertIn("safe_error_code=generated_briefing_contract_invalid", resp.text)
        self.assertNotIn("Gemini parse failed", resp.text)
        self.assertNotIn("top_5_news.items must contain exactly 5 entries", resp.text)
        mock_text_and_image.assert_called_once()
        mock_exec.assert_not_called()

    def test_reissue_form_shows_dry_run_checkbox_for_keysuri(self) -> None:
        self.client.post("/admin/login", data={"password": "test-admin-secret"})
        parent_id = "20260530_120210_keysuri_global_tech_aabbccdd"
        save_run_artifact(
            {
                "run_id": parent_id,
                "mode": "keysuri_global_tech",
                "program_id": "keysuri_global_tech",
                "validation_result": "pass",
                "workflow_status": "validated",
                "email_sent": True,
                "response_status": 200,
                "reason_summary": "ok",
            }
        )
        resp = self.client.get(f"/admin/runs/{parent_id}")
        self.assertEqual(resp.status_code, 200)
        self.assertIn('name="dry_run_no_send"', resp.text)
        self.assertIn("owner-review", resp.text)
        self.assertIn("발송하지 않습니다", resp.text)

    def test_reissue_form_hides_dry_run_checkbox_for_today_genie(self) -> None:
        self.client.post("/admin/login", data={"password": "test-admin-secret"})
        parent_id = "20260530_120211_today_genie_aabbccdd"
        save_run_artifact(
            {
                "run_id": parent_id,
                "mode": "today_genie",
                "validation_result": "pass",
                "workflow_status": "validated",
                "email_sent": True,
                "response_status": 200,
                "reason_summary": "ok",
            }
        )
        resp = self.client.get(f"/admin/runs/{parent_id}")
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn('name="dry_run_no_send"', resp.text)

    @patch("admin_routes.execute_orchestrator_run")
    @patch("admin_routes.run_keysuri_text_and_image_reissue")
    def test_body_and_image_dry_run_skips_owner_email(self, mock_text_and_image, mock_exec) -> None:
        child_id = "20260530_130200_keysuri_global_tech_11223344"
        mock_text_and_image.return_value = {
            "ok": True,
            "run_id": child_id,
            "regen_type": "body_and_image",
            "email_sent": False,
            "reissue_top5_repaired_from_parent": True,
            "reissue_top5_repair_source": "parent_generated_briefing_snapshot",
        }
        self.client.post("/admin/login", data={"password": "test-admin-secret"})
        parent_id = "20260530_120212_keysuri_global_tech_aabbccdd"
        save_run_artifact(
            {
                "run_id": parent_id,
                "mode": "keysuri_global_tech",
                "program_id": "keysuri_global_tech",
                "validation_result": "pass",
                "workflow_status": "validated",
                "email_sent": True,
                "response_status": 200,
                "reason_summary": "ok",
            },
            email_html="<html><body><p>original body</p></body></html>",
        )
        # The runner is mocked, so pre-save the child the dry-run markers attach to.
        save_run_artifact(
            {
                "run_id": child_id,
                "mode": "keysuri_global_tech",
                "program_id": "keysuri_global_tech",
                "validation_result": "pass",
                "workflow_status": "review_required",
                "email_sent": False,
                "customer_delivery_status": "not_sent",
                "response_status": 200,
                "reissue_top5_repaired_from_parent": True,
                "reissue_top5_repair_source": "parent_generated_briefing_snapshot",
            },
            email_html="<html><body><p>dry-run body</p></body></html>",
        )
        resp = self.client.post(
            f"/admin/runs/{parent_id}/reissue",
            data={
                "reason_option": "뉴스 중복 이슈",
                "reason_note": "",
                "reissue_scope": "body_and_image",
                "dry_run_no_send": "1",
            },
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 303)
        self.assertIn("reissue_dry_run=1", resp.headers.get("location", ""))
        self.assertIn(child_id, resp.headers.get("location", ""))
        mock_text_and_image.assert_called_once()
        self.assertEqual(mock_text_and_image.call_args.kwargs["send_owner_email"], False)
        mock_exec.assert_not_called()
        child = load_run_artifact(child_id) or {}
        self.assertTrue(child.get("admin_reissue_dry_run"))
        self.assertEqual(child.get("send_owner_email"), False)
        self.assertEqual(child.get("owner_review_email_sent"), False)
        self.assertEqual(child.get("customer_send"), False)
        self.assertEqual(child.get("approve_customer_final_send"), False)
        self.assertEqual(child.get("customer_delivery_status"), "not_sent")
        # repair metadata stays visible on the dry-run child
        self.assertTrue(child.get("reissue_top5_repaired_from_parent"))
        # dry-run result page banner is visible after the redirect
        detail = self.client.get(f"/admin/runs/{child_id}?reissue_dry_run=1")
        self.assertIn("dry-run", detail.text)
        self.assertIn("admin_reissue_dry_run", detail.text)

    @patch("admin_routes.execute_orchestrator_run")
    @patch("admin_routes.run_keysuri_text_only_reissue")
    def test_body_only_dry_run_skips_owner_email(self, mock_text_only, mock_exec) -> None:
        child_id = "20260530_130201_keysuri_korea_tech_11223344"
        mock_text_only.return_value = {
            "ok": True,
            "run_id": child_id,
            "regen_type": "body_only",
            "email_sent": False,
        }
        self.client.post("/admin/login", data={"password": "test-admin-secret"})
        parent_id = "20260530_120213_keysuri_korea_tech_aabbccdd"
        save_run_artifact(
            {
                "run_id": parent_id,
                "mode": "keysuri_korea_tech",
                "program_id": "keysuri_korea_tech",
                "validation_result": "pass",
                "workflow_status": "validated",
                "email_sent": True,
                "response_status": 200,
                "reason_summary": "ok",
            },
            email_html="<html><body><p>original body</p></body></html>",
        )
        save_run_artifact(
            {
                "run_id": child_id,
                "mode": "keysuri_korea_tech",
                "program_id": "keysuri_korea_tech",
                "validation_result": "pass",
                "workflow_status": "review_required",
                "email_sent": False,
                "customer_delivery_status": "not_sent",
                "response_status": 200,
            },
            email_html="<html><body><p>dry-run body</p></body></html>",
        )
        resp = self.client.post(
            f"/admin/runs/{parent_id}/reissue",
            data={
                "reason_option": "제목 수정 요청",
                "reason_note": "",
                "reissue_scope": "body_only",
                "dry_run_no_send": "1",
            },
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 303)
        self.assertIn("reissue_dry_run=1", resp.headers.get("location", ""))
        self.assertEqual(mock_text_only.call_args.kwargs["send_owner_email"], False)
        mock_exec.assert_not_called()
        child = load_run_artifact(child_id) or {}
        self.assertTrue(child.get("admin_reissue_dry_run"))
        self.assertEqual(child.get("send_owner_email"), False)

    @patch("admin_routes.execute_orchestrator_run")
    @patch("admin_routes.run_keysuri_text_and_image_reissue")
    def test_default_reissue_keeps_owner_email_send(self, mock_text_and_image, mock_exec) -> None:
        child_id = "20260530_130202_keysuri_global_tech_11223344"
        mock_text_and_image.return_value = {
            "ok": True,
            "run_id": child_id,
            "regen_type": "body_and_image",
            "email_sent": True,
        }
        self.client.post("/admin/login", data={"password": "test-admin-secret"})
        parent_id = "20260530_120214_keysuri_global_tech_aabbccdd"
        save_run_artifact(
            {
                "run_id": parent_id,
                "mode": "keysuri_global_tech",
                "program_id": "keysuri_global_tech",
                "validation_result": "pass",
                "workflow_status": "validated",
                "email_sent": True,
                "response_status": 200,
                "reason_summary": "ok",
            },
            email_html="<html><body><p>original body</p></body></html>",
        )
        save_run_artifact(
            {
                "run_id": child_id,
                "mode": "keysuri_global_tech",
                "program_id": "keysuri_global_tech",
                "validation_result": "pass",
                "workflow_status": "review_required",
                "email_sent": True,
                "customer_delivery_status": "not_sent",
                "response_status": 200,
            },
            email_html="<html><body><p>regen body</p></body></html>",
        )
        resp = self.client.post(
            f"/admin/runs/{parent_id}/reissue",
            data={
                "reason_option": "뉴스 중복 이슈",
                "reason_note": "",
                "reissue_scope": "body_and_image",
            },
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 303)
        # default (no dry-run) → normal send path, no dry-run query param
        self.assertNotIn("reissue_dry_run", resp.headers.get("location", ""))
        self.assertEqual(mock_text_and_image.call_args.kwargs["send_owner_email"], True)
        child = load_run_artifact(child_id) or {}
        self.assertFalse(child.get("admin_reissue_dry_run"))

    @patch("admin_routes.execute_orchestrator_run")
    @patch("admin_routes.run_keysuri_text_and_image_reissue")
    def test_dry_run_safe_failure_shows_no_send_note(self, mock_text_and_image, mock_exec) -> None:
        mock_text_and_image.return_value = {
            "ok": False,
            "program_id": "keysuri_global_tech",
            "error": (
                "Gemini parse failed (parsed_invalid): "
                "top_5_news.items must contain exactly 5 entries, got 2"
            ),
        }
        self.client.post("/admin/login", data={"password": "test-admin-secret"})
        parent_id = "20260530_120215_keysuri_global_tech_aabbccdd"
        save_run_artifact(
            {
                "run_id": parent_id,
                "mode": "keysuri_global_tech",
                "program_id": "keysuri_global_tech",
                "validation_result": "pass",
                "workflow_status": "validated",
                "email_sent": True,
                "response_status": 200,
            },
            email_html="<html><body><p>original body</p></body></html>",
        )
        resp = self.client.post(
            f"/admin/runs/{parent_id}/reissue",
            data={
                "reason_option": "뉴스 중복 이슈",
                "reason_note": "",
                "reissue_scope": "body_and_image",
                "dry_run_no_send": "1",
            },
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(mock_text_and_image.call_args.kwargs["send_owner_email"], False)
        self.assertIn("safe_error_code=generated_briefing_contract_invalid", resp.text)
        self.assertIn("dry-run", resp.text)
        self.assertNotIn("Gemini parse failed", resp.text)
        self.assertNotIn("Traceback", resp.text)
        mock_exec.assert_not_called()

    @patch("admin_routes.execute_orchestrator_run")
    @patch("admin_routes.run_keysuri_text_only_reissue")
    def test_body_only_exhausted_pool_renders_safe_panel(self, mock_text_only, mock_exec) -> None:
        # body_only with no reselect candidates left → graceful safe error, HTTP 200.
        mock_text_only.return_value = {
            "ok": False,
            "program_id": "keysuri_global_tech",
            "error": "text_only_reselect_candidate_pool_exhausted",
        }
        self.client.post("/admin/login", data={"password": "test-admin-secret"})
        parent_id = "20260530_120220_keysuri_global_tech_aabbccdd"
        save_run_artifact(
            {
                "run_id": parent_id,
                "mode": "keysuri_global_tech",
                "program_id": "keysuri_global_tech",
                "validation_result": "pass",
                "workflow_status": "validated",
                "email_sent": True,
                "response_status": 200,
            },
            email_html="<html><body><p>original body</p></body></html>",
        )
        resp = self.client.post(
            f"/admin/runs/{parent_id}/reissue",
            data={
                "reason_option": "뉴스 중복 이슈",
                "reason_note": "",
                "reissue_scope": "body_only",
            },
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn("safe_error_code=text_only_reselect_candidate_pool_exhausted", resp.text)
        self.assertNotIn("Traceback", resp.text)
        self.assertNotIn("ValueError", resp.text)
        mock_text_only.assert_called_once()
        mock_exec.assert_not_called()

    @patch("admin_routes.execute_orchestrator_run")
    @patch("admin_routes.run_keysuri_text_only_reissue")
    def test_reissue_unexpected_exception_hides_raw_type(self, mock_text_only, mock_exec) -> None:
        # An unexpected exception inside the runner must not leak the raw type
        # (e.g. "ValueError") or a traceback to the operator screen.
        mock_text_only.side_effect = ValueError(
            "prompt_input.top_5_news is required for generation prompt"
        )
        self.client.post("/admin/login", data={"password": "test-admin-secret"})
        parent_id = "20260530_120221_keysuri_global_tech_aabbccdd"
        save_run_artifact(
            {
                "run_id": parent_id,
                "mode": "keysuri_global_tech",
                "program_id": "keysuri_global_tech",
                "validation_result": "pass",
                "workflow_status": "validated",
                "email_sent": True,
                "response_status": 200,
            },
            email_html="<html><body><p>original body</p></body></html>",
        )
        resp = self.client.post(
            f"/admin/runs/{parent_id}/reissue",
            data={
                "reason_option": "뉴스 중복 이슈",
                "reason_note": "",
                "reissue_scope": "body_only",
            },
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn("keysuri_reissue_execution", resp.text)
        self.assertIn("safe_error_code=keysuri_reissue_execution_error", resp.text)
        self.assertNotIn("ValueError", resp.text)
        self.assertNotIn("top_5_news is required", resp.text)
        self.assertNotIn("Traceback", resp.text)
        mock_exec.assert_not_called()

    @patch("admin_routes.execute_orchestrator_run")
    def test_reissue_unknown_mode_returns_400_with_safe_error_fields(self, mock_exec) -> None:
        self.client.post("/admin/login", data={"password": "test-admin-secret"})
        # run_id must match the canonical mode pattern, but the stored "mode"
        # field itself can still be corrupted/unexpected independently of run_id.
        parent_id = "20260530_120206_today_genie_aabbccdd"
        save_run_artifact(
            {
                "run_id": parent_id,
                "mode": "totally_unknown_mode",
                "validation_result": "pass",
                "workflow_status": "validated",
                "email_sent": True,
                "response_status": 200,
                "reason_summary": "ok",
            }
        )
        resp = self.client.post(
            f"/admin/runs/{parent_id}/reissue",
            data={
                "reason_option": "기타",
                "reason_note": "",
                "reissue_scope": "body_and_image",
            },
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("totally_unknown_mode", resp.text)
        self.assertIn("mode_validation", resp.text)
        self.assertNotIn("Traceback", resp.text)
        mock_exec.assert_not_called()

    @patch("admin_routes.execute_orchestrator_run")
    def test_reissue_invalid_scope_rejected(self, mock_exec) -> None:
        self.client.post("/admin/login", data={"password": "test-admin-secret"})
        parent_id = "20260530_120300_today_genie_aabbccdd"
        save_run_artifact(
            {
                "run_id": parent_id,
                "mode": "today_genie",
                "validation_result": "pass",
                "workflow_status": "validated",
                "email_sent": True,
                "response_status": 200,
                "reason_summary": "ok",
            }
        )
        resp = self.client.post(
            f"/admin/runs/{parent_id}/reissue",
            data={"reason_option": "기타", "reason_note": "", "reissue_scope": "full_reset"},
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 303)
        self.assertIn("invalid_reissue_scope", resp.headers.get("location", ""))
        mock_exec.assert_not_called()


class AdminApprovalHardeningTests(unittest.TestCase):
    def setUp(self) -> None:
        self._prev_pwd = os.environ.get("GENIE_ADMIN_PASSWORD")
        self._prev_customer = os.environ.get("GENIE_CUSTOMER_EMAIL_TO")
        os.environ["GENIE_ADMIN_PASSWORD"] = "test-admin-secret"
        os.environ["GENIE_CUSTOMER_EMAIL_TO"] = "customer@example.com"
        os.environ["SMTP_HOST"] = "smtp.example.com"
        os.environ["SMTP_USER"] = "user@example.com"
        os.environ["SMTP_PASSWORD"] = "secret"
        self.client = TestClient(app)

    def tearDown(self) -> None:
        for key, prev in (
            ("GENIE_ADMIN_PASSWORD", self._prev_pwd),
            ("GENIE_CUSTOMER_EMAIL_TO", self._prev_customer),
        ):
            if prev is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = prev

    def _save_today_run(self, run_id: str) -> None:
        save_run_artifact(
            {
                "run_id": run_id,
                "mode": "today_genie",
                "validation_result": "pass",
                "workflow_status": "validated",
                "response_status": 200,
                "reason_summary": "ok",
                "owner_review_status": "pending_review",
                "customer_delivery_status": "not_sent",
            },
            email_html="<p>brief</p>",
        )

    @patch("today_geenee_customer_delivery.send_today_geenee_customer_final_email")
    def test_direct_post_approve_without_nonce_rejected(self, mock_send: MagicMock) -> None:
        mock_send.return_value = True
        run_id = "20260615_170000_today_genie_aabbccdd"
        self._save_today_run(run_id)
        self.client.post("/admin/login", data={"password": "test-admin-secret"})
        resp = self.client.post(
            f"/admin/runs/{run_id}/approve",
            data={"approve_note": "ok", "customer_send_confirm": "1"},
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 303)
        self.assertIn("missing_approval_nonce", resp.headers.get("location", ""))
        mock_send.assert_not_called()
        meta = load_run_artifact(run_id) or {}
        self.assertEqual(meta.get("customer_delivery_status"), "not_sent")

    @patch("today_geenee_customer_delivery.send_today_geenee_customer_final_email")
    def test_post_approve_without_checkbox_rejected(self, mock_send: MagicMock) -> None:
        mock_send.return_value = True
        run_id = "20260615_170100_today_genie_aabbccdd"
        self._save_today_run(run_id)
        self.client.post("/admin/login", data={"password": "test-admin-secret"})
        resp = post_customer_approve_with_confirm(
            self.client,
            run_id,
            include_checkbox=False,
        )
        self.assertEqual(resp.status_code, 303)
        self.assertIn("missing_customer_send_confirm", resp.headers.get("location", ""))
        mock_send.assert_not_called()

    @patch("today_geenee_customer_delivery.send_today_geenee_customer_final_email")
    def test_post_approve_with_valid_nonce_and_checkbox_sends_once(self, mock_send: MagicMock) -> None:
        mock_send.return_value = True
        run_id = "20260615_170200_today_genie_aabbccdd"
        self._save_today_run(run_id)
        self.client.post("/admin/login", data={"password": "test-admin-secret"})
        resp = post_customer_approve_with_confirm(self.client, run_id, note="browser ok")
        self.assertEqual(resp.status_code, 303)
        self.assertNotIn("approve_error", resp.headers.get("location", ""))
        mock_send.assert_called_once()
        meta = load_run_artifact(run_id) or {}
        self.assertEqual(meta.get("owner_review_status"), "approved")
        self.assertEqual(meta.get("approval_channel"), "browser_confirm")
        self.assertTrue(meta.get("approval_nonce_used"))
        self.assertEqual(meta.get("approval_note"), "browser ok")

    @patch("today_geenee_customer_delivery.send_today_geenee_customer_final_email")
    def test_approval_nonce_cannot_be_reused(self, mock_send: MagicMock) -> None:
        mock_send.return_value = True
        run_id = "20260615_170300_today_genie_aabbccdd"
        self._save_today_run(run_id)
        self.client.post("/admin/login", data={"password": "test-admin-secret"})
        confirm_resp = self.client.get(f"/admin/runs/{run_id}/approve-confirm")
        match = re.search(r'name="approve_nonce" value="([^"]+)"', confirm_resp.text)
        self.assertIsNotNone(match)
        nonce = match.group(1)
        first = self.client.post(
            f"/admin/runs/{run_id}/approve",
            data={
                "approve_note": "once",
                "approve_nonce": nonce,
                "customer_send_confirm": "1",
            },
            follow_redirects=False,
        )
        self.assertEqual(first.status_code, 303)
        mock_send.assert_called_once()
        second = self.client.post(
            f"/admin/runs/{run_id}/approve",
            data={
                "approve_note": "twice",
                "approve_nonce": nonce,
                "customer_send_confirm": "1",
            },
            follow_redirects=False,
        )
        self.assertEqual(second.status_code, 303)
        self.assertIn("approve_error", second.headers.get("location", ""))
        mock_send.assert_called_once()

    def test_approve_confirm_includes_checkbox_and_hidden_nonce(self) -> None:
        run_id = "20260615_170400_today_genie_aabbccdd"
        self._save_today_run(run_id)
        self.client.post("/admin/login", data={"password": "test-admin-secret"})
        resp = self.client.get(f"/admin/runs/{run_id}/approve-confirm")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("고객 이메일 발송을 승인합니다", resp.text)
        self.assertIn('name="approve_nonce"', resp.text)
        self.assertIn("genie_approve_nonce", resp.cookies)


class AdminStoreReissueMetadataTests(unittest.TestCase):
    def test_apply_reissue_child_metadata_persists_scope(self) -> None:
        child_id = "20260530_140000_today_genie_aabbccdd"
        save_run_artifact(
            {
                "run_id": child_id,
                "mode": "today_genie",
                "validation_result": "pass",
                "workflow_status": "validated",
                "response_status": 200,
                "reason_summary": "ok",
            }
        )
        updated = apply_reissue_child_metadata(
            child_id,
            reissue_scope=EXECUTABLE_REISSUE_SCOPE,
            reissue_reason_code="제목 수정 요청",
            reissue_reason_note="note",
        )
        assert updated is not None
        reloaded = load_run_artifact(child_id) or {}
        self.assertEqual(reloaded.get("reissue_scope"), EXECUTABLE_REISSUE_SCOPE)
        self.assertEqual(reloaded.get("reissue_scope_status"), "executed")


class CustomerDeliveryAdminPanelTests(unittest.TestCase):
    def setUp(self) -> None:
        self._prev_pwd = os.environ.get("GENIE_ADMIN_PASSWORD")
        os.environ["GENIE_ADMIN_PASSWORD"] = "test-admin-secret"
        self.client = TestClient(app)

    def tearDown(self) -> None:
        if self._prev_pwd is None:
            os.environ.pop("GENIE_ADMIN_PASSWORD", None)
        else:
            os.environ["GENIE_ADMIN_PASSWORD"] = self._prev_pwd

    def _login(self) -> None:
        self.client.post("/admin/login", data={"password": "test-admin-secret"})

    def test_mask_customer_email(self) -> None:
        self.assertEqual(mask_customer_email("tera9003@daum.net"), "t***3@daum.net")
        self.assertEqual(mask_customer_email("tomato3593@gmail.com"), "t***3@gmail.com")
        self.assertEqual(mask_customer_email("aegis001@naver.com"), "a***1@naver.com")
        self.assertEqual(mask_customer_email("kha6210@hanmail.com"), "k***0@hanmail.com")

    def test_panel_smtp_accepted_run(self) -> None:
        panel = build_customer_delivery_admin_panel(
            {
                "customer_delivery_status": "smtp_accepted",
                "customer_delivery_reason": "owner_approved",
                "mode": "today_genie",
            }
        )
        self.assertEqual(panel["status_grade"], "PASS")
        self.assertEqual(panel["status_detail"], "발송 접수 완료")
        self.assertEqual(panel["failure_reason_code"], "없음")

    def test_panel_uses_customer_email_trace_fields(self) -> None:
        panel = build_customer_delivery_admin_panel(
            {
                "customer_delivery_status": "smtp_accepted",
                "customer_email_recipient_count": 2,
                "customer_email_recipients_masked": ["su***gp@hanmail.net", "ph***ce@gmail.com"],
                "customer_email_subject": "[장전 브리핑] 테스트",
                "customer_email_mime_html_sha256": "html-sha",
                "customer_email_mime_html_bytes_len": 1234,
                "customer_email_inline_image_hashes": [{"cid": "top", "sha256": "top-sha"}],
            }
        )
        self.assertEqual(panel["recipient_count"], "2")
        self.assertEqual(panel["recipients_masked"], ["su***gp@hanmail.net", "ph***ce@gmail.com"])
        self.assertEqual(panel["subject"], "[장전 브리핑] 테스트")
        self.assertEqual(panel["mime_html_sha256"], "html-sha")
        self.assertEqual(panel["mime_html_bytes_len"], "1234")
        self.assertEqual(panel["inline_image_count"], "1")

    def test_panel_failed_run(self) -> None:
        panel = build_customer_delivery_admin_panel(
            {
                "customer_delivery_status": "failed",
                "customer_delivery_error_code": "send_failed",
                "customer_delivery_error_summary": "SMTPException: relay denied",
            }
        )
        self.assertEqual(panel["status_grade"], "FAIL")
        self.assertEqual(panel["failure_reason_code"], "send_failed")
        self.assertIn("relay denied", panel["failure_message"])

    def test_panel_blocked_run(self) -> None:
        panel = build_customer_delivery_admin_panel({"customer_delivery_status": "blocked"})
        self.assertEqual(panel["status_grade"], "BLOCKED")

    def test_panel_not_sent_run(self) -> None:
        panel = build_customer_delivery_admin_panel({"customer_delivery_status": "not_sent"})
        self.assertEqual(panel["status_grade"], "대기")
        self.assertEqual(panel["status_detail"], "미발송")

    def test_panel_five_recipients(self) -> None:
        recipients = [
            "tera9003@daum.net",
            "tomato3593@gmail.com",
            "aegis001@naver.com",
            "kha6210@hanmail.com",
            "beta5@example.com",
        ]
        panel = build_customer_delivery_admin_panel(
            {
                "customer_delivery_status": "smtp_accepted",
                "customer_recipients": recipients,
                "customer_recipient_count": 5,
            }
        )
        self.assertEqual(panel["recipient_count"], "5")
        self.assertEqual(len(panel["recipients_masked"]), 5)

    def test_panel_missing_metadata_is_safe(self) -> None:
        panel = build_customer_delivery_admin_panel({})
        self.assertEqual(panel["recipient_count"], "미기록")
        self.assertEqual(panel["smtp_message_id"], "미기록")
        self.assertEqual(panel["subject"], "미기록")

    def test_detail_page_shows_panel_for_modes(self) -> None:
        self._login()
        fixtures = (
            ("20260530_123000_today_genie_aabbccdd", "today_genie"),
            ("20260530_123100_keysuri_global_tech_aabbccdd", "keysuri_global_tech"),
            ("20260530_123200_keysuri_korea_tech_aabbccdd", "keysuri_korea_tech"),
        )
        for run_id, mode in fixtures:
            save_run_artifact(
                {
                    "run_id": run_id,
                    "mode": mode,
                    "validation_result": "pass",
                    "customer_delivery_status": "not_sent",
                }
            )
            resp = self.client.get(f"/admin/runs/{run_id}")
            self.assertEqual(resp.status_code, 200, msg=mode)
            self.assertIn("고객 이메일 발송 상태", resp.text, msg=mode)
            self.assertIn("미발송", resp.text, msg=mode)

    def test_detail_failed_and_double_send_blocked(self) -> None:
        self._login()
        run_id = "20260530_124000_today_genie_aabbccdd"
        save_run_artifact(
            {
                "run_id": run_id,
                "mode": "today_genie",
                "validation_result": "pass",
                "customer_delivery_status": "failed",
                "customer_delivery_error_code": "send_failed",
                "customer_delivery_error_summary": "timeout",
            }
        )
        resp = self.client.get(f"/admin/runs/{run_id}")
        self.assertIn("FAIL", resp.text)
        self.assertIn("send_failed", resp.text)

        approved_id = "20260530_124100_today_genie_aabbccdd"
        save_run_artifact(
            {
                "run_id": approved_id,
                "mode": "today_genie",
                "validation_result": "pass",
                "customer_delivery_status": "smtp_accepted",
                "owner_review_status": "approved",
            }
        )
        approved_resp = self.client.get(f"/admin/runs/{approved_id}")
        self.assertIn("재발송 차단", approved_resp.text)


if __name__ == "__main__":
    unittest.main()
