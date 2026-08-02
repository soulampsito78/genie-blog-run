from __future__ import annotations

import io
import json
import logging
import os
import tempfile
import threading
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

from fastapi import FastAPI
from fastapi.testclient import TestClient

from admin_store import load_run_artifact, process_approval_timeouts, save_run_artifact, update_run_artifact
from business_watchdog import evaluate_business_success_deadlines
from delivery_status import (
    CustomerDeliveryStatus,
    accepted_recipient_status,
    is_customer_delivery_retryable,
    is_customer_delivery_terminal_failure,
    is_customer_delivery_terminal_success,
)
from execution_state import build_logical_execution_key
from internal_auth import verify_internal_request
from keysuri_customer_delivery import resolve_keysuri_inline_jpeg_parts
from keysuri_service_full_run import (
    keysuri_global_service_email_cid_token,
    keysuri_korea_bottom_service_email_cid_token,
    keysuri_korea_service_email_cid_token,
)
from main import app, secure_unhandled_exception
from orchestrator import run_genie_job
from owner_review_exposure_log_store import append_owner_review_exposure, load_owner_review_exposure_log
from run_metadata_index import list_recent_metadata, summary_from_artifact
from security_headers import SecurityHeadersMiddleware
from structured_events import configure_business_event_logger, emit_business_event

KST = ZoneInfo("Asia/Seoul")


class IsolatedContractTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.env = mock.patch.dict(
            os.environ,
            {
                "GENIE_ADMIN_ARTIFACT_ROOT": str(root / "artifacts"),
                "GENIE_EXECUTION_STATE_ROOT": str(root / "executions"),
                "GENIE_METADATA_INDEX_ROOT": str(root / "index"),
                "GENIE_OWNER_REVIEW_EXPOSURE_LOG_PATH": str(root / "owner.json"),
            },
            clear=False,
        )
        self.env.start()

    def tearDown(self) -> None:
        self.env.stop()
        self.tmp.cleanup()


class EndpointSecurityContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)

    def test_public_post_is_gone_before_model_and_runtime_input(self) -> None:
        with mock.patch("main.build_runtime_input") as runtime, mock.patch(
            "main.init_vertex"
        ) as vertex, mock.patch("main.call_gemini") as gemini:
            response = self.client.post(
                "/",
                json={"type": "today_genie", "runtime_input": {"secret": "x"}},
            )
        self.assertEqual(response.status_code, 410)
        self.assertNotIn("runtime_input", response.text)
        runtime.assert_not_called()
        vertex.assert_not_called()
        gemini.assert_not_called()

    def test_health_is_minimal_and_tomorrow_not_advertised(self) -> None:
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("model", response.json())
        self.assertNotIn("project_id", response.json())
        self.assertNotIn("tomorrow", response.text.lower())

    def test_security_headers_cover_normal_error_redirect_and_admin_html(self) -> None:
        for response in (
            self.client.get("/health"),
            self.client.get("/does-not-exist"),
            self.client.get("/admin/runs", follow_redirects=False),
            self.client.get("/admin"),
        ):
            self.assertEqual(response.headers["x-content-type-options"], "nosniff")
            self.assertEqual(response.headers["x-frame-options"], "DENY")
            self.assertIn("camera=()", response.headers["permissions-policy"])
            self.assertIn("max-age=", response.headers["strict-transport-security"])

    def test_unhandled_500_keeps_security_headers_and_hides_exception(self) -> None:
        mini = FastAPI()
        mini.add_middleware(SecurityHeadersMiddleware)
        mini.add_exception_handler(Exception, secure_unhandled_exception)

        @mini.get("/boom")
        def _boom():
            raise RuntimeError("sensitive exception detail")

        response = TestClient(mini, raise_server_exceptions=False).get("/boom")
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.headers["x-content-type-options"], "nosniff")
        self.assertNotIn("sensitive exception detail", response.text)

    def test_secure_cookie_on_https(self) -> None:
        with mock.patch.dict(os.environ, {"GENIE_ADMIN_PASSWORD": "pw"}, clear=False):
            client = TestClient(app, base_url="https://testserver")
            response = client.post(
                "/admin/login",
                data={"password": "pw"},
                follow_redirects=False,
            )
        cookie = response.headers.get("set-cookie", "").lower()
        self.assertIn("httponly", cookie)
        self.assertIn("secure", cookie)
        self.assertIn("samesite=lax", cookie)

    def test_today_generation_runs_in_process_without_loopback_http(self) -> None:
        payload = {
            "validation_result": "pass",
            "workflow_status": "approved",
            "issues": [],
            "runtime_input": {},
        }
        with mock.patch("main.generate_internal_payload", return_value=payload) as generate, mock.patch(
            "urllib.request.urlopen"
        ) as urlopen:
            result = run_genie_job("today_genie")
        self.assertEqual(result.response_status, 200)
        generate.assert_called_once()
        urlopen.assert_not_called()


class OidcContractTests(unittest.TestCase):
    @staticmethod
    def claims(**overrides) -> dict:
        claims = {
            "iss": "https://accounts.google.com",
            "aud": "https://service.example/internal",
            "email": "scheduler@example.iam.gserviceaccount.com",
            "email_verified": True,
        }
        claims.update(overrides)
        return claims

    def oidc_env(self) -> dict:
        return {
            "GENIE_INTERNAL_OIDC_AUDIENCE": "https://service.example/internal",
            "GENIE_INTERNAL_OIDC_SERVICE_ACCOUNTS": "scheduler@example.iam.gserviceaccount.com",
        }

    def test_valid_oidc_claims(self) -> None:
        with mock.patch.dict(os.environ, self.oidc_env(), clear=False):
            result = verify_internal_request(
                authorization="Bearer fake-token",
                header_token=None,
                oidc_verifier=lambda _token, _aud: self.claims(),
            )
        self.assertTrue(result.ok)
        self.assertEqual(result.method, "oidc")

    def test_oidc_wrong_audience_or_principal_fails_closed(self) -> None:
        with mock.patch.dict(os.environ, self.oidc_env(), clear=False):
            for claims in (
                self.claims(aud="wrong"),
                self.claims(email="other@example.com"),
            ):
                result = verify_internal_request(
                    authorization="Bearer fake-token",
                    header_token="fallback-must-not-win",
                    oidc_verifier=lambda _token, _aud, claims=claims: claims,
                )
                self.assertFalse(result.ok)
                self.assertEqual(result.status_code, 403)

    def test_token_fallback_has_method_but_never_returns_credential(self) -> None:
        with mock.patch.dict(
            os.environ,
            {"GENIE_INTERNAL_JOB_TOKEN": "secret-token"},
            clear=False,
        ):
            result = verify_internal_request(authorization="", header_token="secret-token")
        self.assertTrue(result.ok)
        self.assertEqual(result.method, "token_fallback")
        self.assertNotIn("secret-token", repr(result))

    def test_oidc_provider_transport_failure_is_503_without_fallback(self) -> None:
        from google.auth.exceptions import TransportError

        env = {**self.oidc_env(), "GENIE_INTERNAL_JOB_TOKEN": "fallback-token"}
        with mock.patch.dict(os.environ, env, clear=False):
            result = verify_internal_request(
                authorization="Bearer unavailable",
                header_token="fallback-token",
                oidc_verifier=lambda _token, _aud: (_ for _ in ()).throw(
                    TransportError("offline")
                ),
            )
        self.assertFalse(result.ok)
        self.assertEqual(result.status_code, 503)
        self.assertEqual(result.error, "oidc_verification_unavailable")

    def test_oidc_signature_failure_is_403_without_fallback(self) -> None:
        env = {**self.oidc_env(), "GENIE_INTERNAL_JOB_TOKEN": "fallback-token"}
        with mock.patch.dict(os.environ, env, clear=False):
            result = verify_internal_request(
                authorization="Bearer bad-signature",
                header_token="fallback-token",
                oidc_verifier=lambda _token, _aud: (_ for _ in ()).throw(
                    ValueError("bad signature")
                ),
            )
        self.assertFalse(result.ok)
        self.assertEqual(result.status_code, 403)
        self.assertEqual(result.method, "oidc")


class DeliveryStatusContractTests(IsolatedContractTestCase):
    def test_legacy_accepted_statuses_normalize(self) -> None:
        for value in (
            "smtp_accepted",
            "customer_sent_after_approval",
            "sent_after_owner_approval",
            "delivery_confirmed",
        ):
            self.assertTrue(is_customer_delivery_terminal_success(value), value)

    def test_vague_and_unknown_words_are_not_success(self) -> None:
        for value in ("sent", "success", "something_new"):
            self.assertFalse(is_customer_delivery_terminal_success(value), value)

    def test_pending_failure_and_retry_contracts(self) -> None:
        self.assertTrue(is_customer_delivery_terminal_failure("rejected"))
        self.assertTrue(is_customer_delivery_retryable("failed"))
        self.assertTrue(is_customer_delivery_retryable("partial_accepted"))

    def test_accepted_recipient_policy(self) -> None:
        self.assertIsNone(accepted_recipient_status(0, 2))
        self.assertEqual(
            accepted_recipient_status(1, 2),
            CustomerDeliveryStatus.PARTIAL_ACCEPTED,
        )
        self.assertEqual(
            accepted_recipient_status(2, 2),
            CustomerDeliveryStatus.SMTP_ACCEPTED,
        )


class MetadataIndexContractTests(IsolatedContractTestCase):
    def test_gcs_paging_returns_latest_100_of_150(self) -> None:
        class FakeBlob:
            def __init__(self, index: int) -> None:
                self.index = index
                self.name = f"metadata/object-{149 - index:03d}.json"
                self.updated = datetime(2026, 8, 1, tzinfo=ZoneInfo("UTC")) + timedelta(minutes=index)

            def download_as_text(self, encoding: str = "utf-8") -> str:
                return json.dumps({"run_id": f"run-{self.index:03d}"})

        class FakeIterator:
            def __init__(self, blobs) -> None:
                self._blobs = sorted(blobs, key=lambda blob: blob.name)

            @property
            def pages(self):
                for offset in range(0, len(self._blobs), 37):
                    yield self._blobs[offset : offset + 37]

        class FakeBucket:
            page_size = None

            def list_blobs(self, *, prefix: str, page_size: int):
                self.page_size = page_size
                return FakeIterator([FakeBlob(index) for index in range(150)])

        bucket = FakeBucket()
        with mock.patch.dict(
            os.environ,
            {"GENIE_METADATA_INDEX_ROOT": "", "GENIE_ADMIN_ARTIFACT_BUCKET": "fake-bucket"},
            clear=False,
        ), mock.patch(
            "admin_store.admin_artifact_bucket_name", return_value="fake-bucket"
        ), mock.patch("admin_store._get_gcs_bucket", return_value=bucket):
            rows = list_recent_metadata(limit=100)

        self.assertEqual(bucket.page_size, 250)
        self.assertEqual(len(rows), 100)
        self.assertEqual(
            {row["run_id"] for row in rows},
            {f"run-{index:03d}" for index in range(50, 150)},
        )

    def test_local_backend_has_the_same_latest_n_meaning(self) -> None:
        root = Path(os.environ["GENIE_METADATA_INDEX_ROOT"])
        root.mkdir(parents=True, exist_ok=True)
        for index in range(150):
            path = root / f"arbitrary-{149 - index:03d}.json"
            path.write_text(json.dumps({"run_id": f"run-{index:03d}"}), encoding="utf-8")
            os.utime(path, (1_700_000_000 + index, 1_700_000_000 + index))
        rows = list_recent_metadata(limit=100)
        self.assertEqual(
            {row["run_id"] for row in rows},
            {f"run-{index:03d}" for index in range(50, 150)},
        )

    def test_scheduled_metadata_derives_key_and_owner_acceptance(self) -> None:
        summary = summary_from_artifact(
            {
                "run_id": "20260803_063000_today_genie_aabbccdd",
                "program_id": "today_genie",
                "trigger_source": "scheduled_owner_review",
                "created_at": "2026-08-03T06:30:00+09:00",
                "email_sent": True,
            }
        )
        self.assertTrue(summary["logical_execution_key"].startswith("today_genie:"))
        self.assertTrue(summary["owner_review_accepted"])


class WatchdogContractTests(IsolatedContractTestCase):
    def today_key(self) -> str:
        return build_logical_execution_key(
            program_id="today_genie",
            scheduled_date_kst="2026-08-03",
            scheduled_slot_kst="06:30",
            trigger_source="scheduled",
        )

    def success_row(self) -> dict:
        return {
            "logical_execution_key": self.today_key(),
            "program_id": "today_genie",
            "run_id": "20260803_063000_today_genie_aabbccdd",
            "selected_count": 3,
            "shortfall_count": 0,
            "validation_result": "pass",
            "artifact_manifest_state": "complete",
            "owner_review_accepted": True,
            "current_stage": "owner_review_emailed",
        }

    def test_before_deadline_has_no_alert(self) -> None:
        result = evaluate_business_success_deadlines(
            now=datetime(2026, 8, 3, 6, 45, tzinfo=KST),
            metadata_rows=[],
            claim_fn=lambda _key: True,
        )
        self.assertEqual(result["failure_event_count"], 0)

    def test_internal_watchdog_route_returns_metadata_summary(self) -> None:
        summary = {
            "ok": True,
            "metadata_only": True,
            "artifact_html_reads": "UNMEASURED",
            "failure_event_count": 0,
        }
        with mock.patch.dict(
            os.environ,
            {"GENIE_INTERNAL_JOB_TOKEN": "token"},
            clear=False,
        ), mock.patch(
            "business_watchdog.evaluate_business_success_deadlines",
            return_value=summary,
        ):
            response = TestClient(app).post(
                "/internal/jobs/watch-business-success",
                headers={"X-Genie-Internal-Job-Token": "token"},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["artifact_html_reads"], "UNMEASURED")

    def test_success_after_deadline_has_no_alert(self) -> None:
        result = evaluate_business_success_deadlines(
            now=datetime(2026, 8, 3, 7, 0, tzinfo=KST),
            metadata_rows=[self.success_row()],
            claim_fn=lambda _key: True,
        )
        self.assertEqual(result["failure_event_count"], 0)

    def test_missed_deadline_emits_once_and_reports_html_reads_unmeasured(self) -> None:
        claims = iter((True, False))
        kwargs = dict(
            now=datetime(2026, 8, 3, 7, 0, tzinfo=KST),
            metadata_rows=[],
            claim_fn=lambda _key: next(claims),
        )
        first = evaluate_business_success_deadlines(**kwargs)
        second = evaluate_business_success_deadlines(**kwargs)
        self.assertEqual(first["failure_event_count"], 1)
        self.assertEqual(second["failure_event_count"], 0)
        self.assertEqual(first["artifact_html_reads"], "UNMEASURED")
        self.assertEqual(first["events"][0]["status"], "missing")

    def test_terminal_failure_does_not_duplicate_stage_alert(self) -> None:
        row = self.success_row()
        row.update(
            owner_review_accepted=False,
            current_stage="failed_terminal",
            terminal_status="failed_terminal",
        )
        result = evaluate_business_success_deadlines(
            now=datetime(2026, 8, 3, 7, 0, tzinfo=KST),
            metadata_rows=[row],
            claim_fn=lambda _key: True,
        )
        self.assertEqual(result["failure_event_count"], 0)

    def test_business_event_is_one_bare_json_line(self) -> None:
        event_logger = configure_business_event_logger()
        buffer = io.StringIO()
        streams = []
        for handler in event_logger.handlers:
            if isinstance(handler, logging.StreamHandler) and getattr(
                handler,
                "_genie_business_event_handler",
                False,
            ):
                streams.append((handler, handler.stream))
                handler.stream = buffer
        try:
            emit_business_event(
                "business_success_deadline_missed",
                program_id="today_genie",
                logical_execution_key=self.today_key(),
            )
        finally:
            for handler, stream in streams:
                handler.stream = stream
        self.assertTrue(buffer.getvalue().strip().startswith("{"))
        self.assertFalse(event_logger.propagate)


class ArtifactAndTimeoutContractTests(IsolatedContractTestCase):
    def test_manifest_finishes_only_after_required_email(self) -> None:
        run_id = "20260803_063000_today_genie_aabbccdd"
        save_run_artifact(
            {"run_id": run_id, "mode": "today_genie", "validation_result": "pass"},
            email_html="<p>owner</p>",
        )
        meta = load_run_artifact(run_id) or {}
        self.assertEqual(meta["artifact_manifest_state"], "complete")
        self.assertEqual(meta["required_artifacts"], ["metadata", "owner_email_html"])

    def test_concurrent_artifact_updates_do_not_lose_increment(self) -> None:
        run_id = "20260803_063000_today_genie_aabbccdd"
        save_run_artifact({"run_id": run_id, "mode": "today_genie", "counter": 0})
        barrier = threading.Barrier(2)

        def worker() -> None:
            barrier.wait()
            update_run_artifact(
                run_id,
                lambda meta: meta.update(counter=int(meta.get("counter") or 0) + 1),
            )

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual((load_run_artifact(run_id) or {})["counter"], 2)

    def test_retired_timeout_is_zero_io_noop(self) -> None:
        with mock.patch("admin_store.list_run_artifacts") as list_runs, mock.patch(
            "admin_store.load_run_email_html"
        ) as html, mock.patch(
            "today_geenee_customer_delivery.send_customer_timeout_draft_email"
        ) as send:
            result = process_approval_timeouts()
        self.assertTrue(result["retired"])
        self.assertEqual(result["scanned"], 0)
        list_runs.assert_not_called()
        html.assert_not_called()
        send.assert_not_called()


class OwnerExposureAtomicContractTests(IsolatedContractTestCase):
    def test_concurrent_distinct_runs_do_not_lose_rows(self) -> None:
        barrier = threading.Barrier(2)

        def worker(run_id: str, url: str) -> None:
            barrier.wait()
            append_owner_review_exposure(
                run_id=run_id,
                program_id="keysuri_global_tech",
                exposure_kind="owner_review_email",
                selected_items=[{"title": run_id, "url": url, "source": "Example"}],
            )

        threads = [
            threading.Thread(target=worker, args=("run-a", "https://example.com/a")),
            threading.Thread(target=worker, args=("run-b", "https://example.com/b")),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(len(load_owner_review_exposure_log()), 2)


class CidCompatibilityContractTests(IsolatedContractTestCase):
    def test_cids_are_run_and_slot_specific(self) -> None:
        run_a = "20260803_123000_keysuri_korea_tech_aabbccdd"
        run_b = "20260803_123001_keysuri_korea_tech_eeff0011"
        self.assertNotEqual(
            keysuri_korea_service_email_cid_token(run_a),
            keysuri_korea_service_email_cid_token(run_b),
        )
        self.assertNotEqual(
            keysuri_korea_service_email_cid_token(run_a),
            keysuri_korea_bottom_service_email_cid_token(run_a),
        )
        self.assertNotEqual(
            keysuri_global_service_email_cid_token(run_a),
            keysuri_korea_service_email_cid_token(run_a),
        )

    def test_legacy_date_cids_are_preserved_for_global_and_korea(self) -> None:
        root = Path(self.tmp.name)
        top = root / "top.jpg"
        bottom = root / "bottom.jpg"
        top.write_bytes(b"top")
        bottom.write_bytes(b"bottom")
        cases = (
            (
                "keysuri_global_tech",
                "20260803_123000_keysuri_global_tech_aabbccdd",
                '<img src="cid:keysuri_topshot_global_20260803">',
                {"generated_image_path": str(top)},
                ["keysuri_topshot_global_20260803"],
            ),
            (
                "keysuri_korea_tech",
                "20260803_183000_keysuri_korea_tech_aabbccdd",
                '<img src="cid:keysuri_topshot_korea_20260803">'
                '<img src="cid:keysuri_bottomshot_korea_20260803">',
                {
                    "generated_image_path": str(top),
                    "korea_bottom_shot_path": str(bottom),
                    "bottom_shot_image_path": str(bottom),
                    "bottom_shot_source": "fixed_105936_fallback",
                },
                ["keysuri_topshot_korea_20260803", "keysuri_bottomshot_korea_20260803"],
            ),
        )
        for program_id, run_id, saved_html, fields, expected in cases:
            with self.subTest(program_id=program_id):
                meta = {
                    "run_id": run_id,
                    "mode": program_id,
                    "program_id": program_id,
                    "service_full_run": True,
                    **fields,
                }
                parts = resolve_keysuri_inline_jpeg_parts(saved_html, meta)
                self.assertEqual([part[1] for part in parts or []], expected)

    def test_new_artifacts_use_run_scoped_cids(self) -> None:
        root = Path(self.tmp.name)
        top = root / "new-top.jpg"
        bottom = root / "new-bottom.jpg"
        top.write_bytes(b"top")
        bottom.write_bytes(b"bottom")
        global_run = "20260803_123000_keysuri_global_tech_ccddeeff"
        global_parts = resolve_keysuri_inline_jpeg_parts(
            "<html></html>",
            {
                "run_id": global_run,
                "mode": "keysuri_global_tech",
                "service_full_run": True,
                "generated_image_path": str(top),
            },
        )
        korea_run = "20260803_183000_keysuri_korea_tech_ccddeeff"
        korea_parts = resolve_keysuri_inline_jpeg_parts(
            "<html></html>",
            {
                "run_id": korea_run,
                "mode": "keysuri_korea_tech",
                "service_full_run": True,
                "generated_image_path": str(top),
                "korea_bottom_shot_path": str(bottom),
                "bottom_shot_source": "fixed_105936_fallback",
            },
        )
        self.assertEqual(
            (global_parts or [])[0][1],
            keysuri_global_service_email_cid_token(global_run),
        )
        self.assertEqual(
            (korea_parts or [])[0][1],
            keysuri_korea_service_email_cid_token(korea_run),
        )
        self.assertEqual(
            (korea_parts or [])[1][1],
            keysuri_korea_bottom_service_email_cid_token(korea_run),
        )

    def test_stored_legacy_cid_metadata_is_preserved_without_html_reference(self) -> None:
        top = Path(self.tmp.name) / "metadata-top.jpg"
        top.write_bytes(b"top")
        parts = resolve_keysuri_inline_jpeg_parts(
            "<html><body>pending artifact</body></html>",
            {
                "run_id": "20260803_123000_keysuri_global_tech_aabbcc04",
                "mode": "keysuri_global_tech",
                "service_full_run": True,
                "generated_image_path": str(top),
                "top_image_cid": "keysuri_topshot_global_20260803",
            },
        )
        self.assertEqual((parts or [])[0][1], "keysuri_topshot_global_20260803")


if __name__ == "__main__":
    unittest.main()
