"""Regression coverage for the Admin live-truth hotfix projections."""
from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from admin_operational_status import OperationalStatusService
from admin_preview_assets import read_preview_asset, rewrite_customer_html_for_admin_preview
from admin_store import save_run_artifact
from admin_view_models import (
    incident_current_projection,
    preflight_projection,
    review_actionability_projection,
)
from main import app


def run(run_id: str, *, program: str = "keysuri_korea_tech", delivery: str = "not_sent", parent: str = "") -> dict:
    return {
        "run_id": run_id,
        "mode": program,
        "created_at": f"{run_id[:8][:4]}-{run_id[:8][4:6]}-{run_id[:8][6:]}T18:30:00+09:00",
        "validation_result": "pass",
        "owner_review_status": "pending_review",
        "customer_delivery_status": delivery,
        "parent_run_id": parent,
    }


class _Adapter:
    def __init__(self, rows):
        self.rows = rows

    def read_scheduler_jobs(self):
        return self.rows

    def read_cloud_run_service(self):
        return {"service": "test", "serving_revision": "rev", "health": "READY"}


class LiveTruthProjectionTests(unittest.TestCase):
    def test_enabled_scheduler_and_no_preflight_are_independent(self):
        service = OperationalStatusService(_Adapter([{
            "name": "KeeSuri_Korea_Tech", "state": "ENABLED", "schedule": "30 18 * * 1-5", "timezone": "Asia/Seoul", "last_attempt": "",
        }]))
        rows = {row["program_id"]: row for row in service.status(recent_evidence={})["programs"]}
        self.assertEqual(rows["keysuri_korea_tech"]["provenance"], "LIVE")
        self.assertEqual(rows["keysuri_korea_tech"]["state"], "ENABLED")
        preflight = preflight_projection({}, {"preflight_time": "17:45"}, now=datetime(2026, 8, 14, 17, 0))
        self.assertEqual(preflight["state"], "not_yet_run")
        self.assertEqual(preflight["detail"], "17:45 예정")

    def test_unavailable_scheduler_does_not_overwrite_preflight_pass(self):
        service = OperationalStatusService(_Adapter([]))
        row = {item["program_id"]: item for item in service.status(recent_evidence={})["programs"]}["today_genie"]
        self.assertEqual(row["state"], "UNAVAILABLE")
        preflight = preflight_projection({"status": "PRECHECK_PASS", "checked_at": "2026-08-14T05:45:00+09:00"}, {"preflight_time": "05:45"})
        self.assertEqual(preflight["label"], "사전점검 정상")

    def test_review_projection_keeps_only_current_safe_leaf(self):
        root = run("20260814_180000_keysuri_korea_tech_aaaaaaaa")
        child = run("20260814_180100_keysuri_korea_tech_bbbbbbbb", parent=root["run_id"])
        projected = review_actionability_projection([root, child], now=datetime(2026, 8, 14, 18, 10))
        self.assertEqual([item["run_id"] for item in projected["current"]], [child["run_id"]])
        self.assertEqual([item["run_id"] for item in projected["superseded"]], [root["run_id"]])

    def test_delivered_or_delivery_attention_is_never_editorial_review(self):
        delivered = run("20260814_120000_keysuri_global_tech_aaaaaaaa", program="keysuri_global_tech", delivery="accepted_all")
        partial = run("20260814_120100_keysuri_global_tech_bbbbbbbb", program="keysuri_global_tech", delivery="partial_refusal")
        unknown = run("20260814_120200_keysuri_global_tech_cccccccc", program="keysuri_global_tech", delivery="outcome_unknown")
        delivered.update({"customer_email_recipient_count": 1, "smtp_accepted_recipient_count": 1, "smtp_refused_recipient_count": 0})
        projected = review_actionability_projection([delivered, partial, unknown], now=datetime(2026, 8, 14, 13))
        self.assertEqual(projected["current"], [])
        self.assertEqual({item["run_id"] for item in projected["delivery_attention"]}, {partial["run_id"], unknown["run_id"]})

    def test_old_unproven_pending_is_history_not_primary_action(self):
        old = run("20260807_183000_keysuri_korea_tech_aaaaaaaa")
        projected = review_actionability_projection([old], now=datetime(2026, 8, 14, 13))
        self.assertEqual(projected["current"], [])
        self.assertEqual([item["run_id"] for item in projected["historical_unresolved"]], [old["run_id"]])

    def test_incident_projection_requires_explicit_resolution_or_direct_success(self):
        open_incident = {"incident_id": "inc_open", "program_id": "keysuri_global_tech", "status": "open"}
        dismissed = {"incident_id": "inc_dismissed", "program_id": "keysuri_global_tech", "status": "dismissed"}
        recovered = {"incident_id": "inc_recovered", "program_id": "keysuri_global_tech", "status": "open"}
        success = run("20260814_123100_keysuri_global_tech_aaaaaaaa", program="keysuri_global_tech", delivery="accepted_all")
        success.update({"original_incident_id": "inc_recovered", "customer_email_recipient_count": 1, "smtp_accepted_recipient_count": 1, "smtp_refused_recipient_count": 0})
        projected = incident_current_projection([open_incident, dismissed, recovered], [success])
        self.assertEqual([item["incident_id"] for item in projected["current"]], ["inc_open"])
        self.assertEqual({item["incident_id"] for item in projected["historical"]}, {"inc_dismissed", "inc_recovered"})

    def test_later_completed_natural_delivery_resolves_dated_incident_history_only(self):
        incident = {"incident_id": "inc_old", "program_id": "keysuri_global_tech", "status": "recovery_failed", "kst_date": "2026-08-11"}
        later = run("20260814_123000_keysuri_global_tech_aaaaaaaa", program="keysuri_global_tech", delivery="accepted_all")
        later.update({"trigger_source": "scheduled_service_full_run", "customer_email_recipient_count": 1, "smtp_accepted_recipient_count": 1, "smtp_refused_recipient_count": 0})
        projected = incident_current_projection([incident], [later])
        self.assertEqual(projected["current"], [])
        self.assertEqual([item["incident_id"] for item in projected["historical"]], ["inc_old"])


class PreviewAssetRouteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.run_dir = self.root / "output" / "admin_runs"
        self.run_dir.mkdir(parents=True)
        self.env = mock.patch.dict(os.environ, {"GENIE_ADMIN_PASSWORD": "test-admin-secret", "GENIE_ARTIFACT_BUCKET": "", "GENIE_ADMIN_ARTIFACT_BUCKET": ""}, clear=False)
        self.store = mock.patch("admin_store.admin_runs_dir", return_value=self.run_dir)
        self.preview_root = mock.patch("admin_preview_assets.repo_root", return_value=self.root)
        self.preview_run_dir = mock.patch("admin_preview_assets.admin_runs_dir", return_value=self.run_dir)
        self.env.start(); self.store.start(); self.preview_root.start(); self.preview_run_dir.start()
        self.client = TestClient(app)

    def tearDown(self):
        self.preview_run_dir.stop(); self.preview_root.stop(); self.store.stop(); self.env.stop(); self.tmp.cleanup()

    def _save(self):
        run_id = "20260814_183000_keysuri_korea_tech_aaaaaaaa"
        top = self.root / "output" / "top.jpg"; bottom = self.root / "output" / "bottom.jpg"
        top.parent.mkdir(parents=True, exist_ok=True); top.write_bytes(b"top-jpeg"); bottom.write_bytes(b"bottom-jpeg")
        html = '<html><body><img src="cid:top-cid"><img src="cid:bottom-cid"></body></html>'
        meta = run(run_id)
        meta.update({"top_image_cid": "top-cid", "bottom_image_cid": "bottom-cid", "generated_image_paths": {"top": "output/top.jpg", "bottom": "output/bottom.jpg"}})
        save_run_artifact(meta, email_html=html)
        return run_id, meta, html

    def test_customer_html_is_preserved_and_preview_rewrites_exact_cids(self):
        run_id, meta, html = self._save()
        preview = rewrite_customer_html_for_admin_preview(run_id, meta, html)
        self.assertIn(f"/admin/runs/{run_id}/preview-assets/top", preview)
        self.assertIn(f"/admin/runs/{run_id}/preview-assets/bottom", preview)
        self.assertIn('cid:top-cid', html)
        self.assertIn('cid:bottom-cid', html)

    def test_preview_frame_can_load_same_origin_assets_without_script_permission(self):
        run_id, _, _ = self._save()
        self.client.post("/admin/login", data={"password": "test-admin-secret"})
        response = self.client.get(f"/admin/runs/{run_id}")
        self.assertIn('sandbox="allow-same-origin"', response.text)
        self.assertNotIn("allow-scripts", response.text)

    def test_asset_requires_auth_and_streams_only_its_run_bound_slot(self):
        run_id, _, _ = self._save()
        self.assertEqual(self.client.get(f"/admin/runs/{run_id}/preview-assets/top", follow_redirects=False).status_code, 303)
        self.client.post("/admin/login", data={"password": "test-admin-secret"})
        response = self.client.get(f"/admin/runs/{run_id}/preview-assets/top")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "image/jpeg")
        self.assertEqual(response.content, b"top-jpeg")
        self.assertEqual(self.client.get(f"/admin/runs/{run_id}/preview-assets/../../secret", follow_redirects=False).status_code, 404)

    def test_missing_or_foreign_asset_has_controlled_fallback(self):
        run_id, meta, html = self._save()
        foreign = dict(meta); foreign["generated_image_paths"] = {"top": "../../etc/passwd"}
        preview = rewrite_customer_html_for_admin_preview(run_id, foreign, html)
        self.assertIn("admin-preview-image-unavailable", preview)
        payload, media_type = read_preview_asset(run_id, foreign, "top")
        self.assertIsNone(payload); self.assertIsNone(media_type)

    def test_system_never_relabels_preflight_evidence_as_scheduler_state(self):
        class RecentOnly:
            def status(self, *, recent_evidence):
                return {
                    "programs": [
                        {"program_id": pid, "name": pid, "state": "PRECHECK_PASS", "schedule": "", "timezone": "Asia/Seoul", "last_attempt": "", "provenance": "RECENT EVIDENCE"}
                        for pid in ("today_genie", "keysuri_global_tech", "keysuri_korea_tech")
                    ],
                    "cloud_run": {"provenance": "UNAVAILABLE", "health": "UNAVAILABLE", "serving_revision": "", "commit_sha": ""},
                }
        self.client.post("/admin/login", data={"password": "test-admin-secret"})
        with mock.patch("admin_routes.default_operational_status_service", return_value=RecentOnly()), mock.patch(
            "natural_run_reliability.load_readiness", return_value={"status": "PRECHECK_PASS", "checked_at": "2026-08-14T11:45:00+09:00"}
        ):
            response = self.client.get("/admin/system")
        self.assertIn("Scheduler 상태</span><strong>확인 불가", response.text)
        self.assertIn("오늘 사전점검</span><strong>사전점검 정상", response.text)
