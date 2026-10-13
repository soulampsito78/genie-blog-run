from __future__ import annotations

import os
import unittest
import io
import urllib.error
from unittest import mock

from fastapi.testclient import TestClient
from fastapi import HTTPException

from main import app, _verify_root_internal_job_token
from natural_run_reliability import _model_call_status_from_response


class GenieRootAuthTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)

    def test_root_generation_fails_closed_when_token_is_unconfigured(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            with mock.patch("main._generate_impl") as generate:
                response = self.client.post(
                    "/",
                    json={"type": "today_genie"},
                    headers={"X-Genie-Internal-Job-Token": "synthetic"},
                )
        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.json()["detail"]["reason"],
            "internal_job_token_not_configured",
        )
        generate.assert_not_called()

    def test_root_generation_rejects_missing_or_wrong_token_before_work(self) -> None:
        with mock.patch.dict(os.environ, {"GENIE_INTERNAL_JOB_TOKEN": "synthetic-secret"}, clear=True):
            with mock.patch("main._generate_impl") as generate:
                missing = self.client.post("/", json={"type": "today_genie"})
                wrong = self.client.post(
                    "/",
                    json={"type": "today_genie"},
                    headers={"X-Genie-Internal-Job-Token": "wrong"},
                )
        self.assertEqual(missing.status_code, 403)
        self.assertEqual(wrong.status_code, 403)
        generate.assert_not_called()

    def test_direct_python_call_without_explicit_token_fails_closed(self) -> None:
        from main import JobRequest, generate

        with mock.patch.dict(os.environ, {"GENIE_INTERNAL_JOB_TOKEN": "synthetic-secret"}, clear=True):
            with mock.patch("main._generate_impl") as generate_impl:
                with self.assertRaises(HTTPException) as raised:
                    generate(JobRequest(type="today_genie"))
        self.assertEqual(raised.exception.status_code, 403)
        self.assertEqual(raised.exception.detail["reason"], "forbidden")
        generate_impl.assert_not_called()

    def test_root_generation_rejects_non_ascii_token_as_forbidden(self) -> None:
        with mock.patch.dict(os.environ, {"GENIE_INTERNAL_JOB_TOKEN": "synthetic-secret"}, clear=True):
            with self.assertRaises(HTTPException) as raised:
                _verify_root_internal_job_token("sëcret")
        self.assertEqual(raised.exception.status_code, 403)
        self.assertEqual(raised.exception.detail["reason"], "forbidden")

    def test_root_generation_accepts_only_the_shared_internal_token(self) -> None:
        with mock.patch.dict(os.environ, {"GENIE_INTERNAL_JOB_TOKEN": "synthetic-secret"}, clear=True):
            with mock.patch("main._generate_impl", return_value={"validation_result": "block"}) as generate:
                response = self.client.post(
                    "/",
                    json={"type": "today_genie"},
                    headers={"X-Genie-Internal-Job-Token": "synthetic-secret"},
                )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["validation_result"], "block")
        generate.assert_called_once()

    def test_wrong_token_rejected_before_invalid_JSON_parsing(self) -> None:
        with mock.patch.dict(os.environ, {"GENIE_INTERNAL_JOB_TOKEN": "synthetic-secret"}, clear=True):
            response = self.client.post("/", content=b"not-json", headers={"X-Genie-Internal-Job-Token": "wrong", "Content-Type": "application/json"})
        self.assertEqual(response.status_code, 403)

    def test_root_declared_oversize_rejected_before_receive(self) -> None:
        import asyncio
        from main import _RootPreparseBoundary
        receive = mock.AsyncMock(side_effect=AssertionError("BODY_MUST_NOT_BE_READ"))
        downstream = mock.AsyncMock()
        send = mock.AsyncMock()
        scope = {"type": "http", "method": "POST", "path": "/", "headers": [(b"x-genie-internal-job-token", b"synthetic-secret"), (b"content-length", b"1048577")]}
        with mock.patch.dict(os.environ, {"GENIE_INTERNAL_JOB_TOKEN": "synthetic-secret"}, clear=True):
            asyncio.run(_RootPreparseBoundary(downstream)(scope, receive, send))
        receive.assert_not_called(); downstream.assert_not_called()
        self.assertEqual(send.call_args_list[0].args[0]["status"], 413)

    def test_root_chunked_oversize_stops_before_app_work(self) -> None:
        import asyncio
        from main import _RootPreparseBoundary
        messages = [{"type": "http.request", "body": b"a" * 524288, "more_body": True}, {"type": "http.request", "body": b"b" * 524289, "more_body": True}]
        receive = mock.AsyncMock(side_effect=messages)
        downstream = mock.AsyncMock(); send = mock.AsyncMock()
        scope = {"type": "http", "method": "POST", "path": "/", "headers": [(b"x-genie-internal-job-token", b"synthetic-secret")]}
        with mock.patch.dict(os.environ, {"GENIE_INTERNAL_JOB_TOKEN": "synthetic-secret"}, clear=True):
            asyncio.run(_RootPreparseBoundary(downstream)(scope, receive, send))
        self.assertEqual(receive.call_count, 2); downstream.assert_not_called()
        self.assertEqual(send.call_args_list[0].args[0]["status"], 413)

    def test_unauthenticated_root_never_reads_body(self) -> None:
        import asyncio
        from main import _RootPreparseBoundary
        receive = mock.AsyncMock(side_effect=AssertionError("BODY_MUST_NOT_BE_READ")); downstream = mock.AsyncMock(); send = mock.AsyncMock()
        scope = {"type": "http", "method": "POST", "path": "/", "headers": []}
        with mock.patch.dict(os.environ, {"GENIE_INTERNAL_JOB_TOKEN": "synthetic-secret"}, clear=True):
            asyncio.run(_RootPreparseBoundary(downstream)(scope, receive, send))
        receive.assert_not_called(); downstream.assert_not_called()
        self.assertEqual(send.call_args_list[0].args[0]["status"], 403)

    def test_preparse_preserves_normal_frozen_news_selection(self) -> None:
        frozen = [{"title": "PUBLIC_FROZEN_NEWS", "url": "https://example.com/" + str(i), "summary": "public " * 2000} for i in range(5)]
        with mock.patch.dict(os.environ, {"GENIE_INTERNAL_JOB_TOKEN": "synthetic-secret"}, clear=True):
            with mock.patch("main._generate_impl", return_value={"status": "ok"}) as generate:
                response = self.client.post("/", json={"type": "today_genie", "frozen_top_market_news": frozen, "frozen_parent_run_id": "PUBLIC_PARENT"}, headers={"X-Genie-Internal-Job-Token": "synthetic-secret"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(generate.call_args.args[0].frozen_top_market_news, frozen)
        self.assertEqual(generate.call_args.args[0].frozen_parent_run_id, "PUBLIC_PARENT")

    def test_unexpected_provider_error_does_not_escape_RPC_server(self) -> None:
        with mock.patch.dict(os.environ, {"GENIE_INTERNAL_JOB_TOKEN": "synthetic-secret"}, clear=True):
            with mock.patch("main._generate_impl", side_effect=RuntimeError("PUBLIC_PRIVATE_PROVIDER_SENTINEL")):
                response = self.client.post("/", json={"type": "today_genie"}, headers={"X-Genie-Internal-Job-Token": "synthetic-secret"})
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()["detail"]["reason"], "internal_processing_failed")
        self.assertNotIn("PUBLIC_PRIVATE_PROVIDER_SENTINEL", response.text)

    def test_unclassified_transient_error_does_not_escape_RPC_server(self) -> None:
        from google.api_core.exceptions import ServiceUnavailable
        with mock.patch.dict(os.environ, {"GENIE_INTERNAL_JOB_TOKEN": "synthetic-secret"}, clear=True):
            with mock.patch("main._generate_impl", side_effect=ServiceUnavailable("PUBLIC_PRIVATE_TRANSIENT_SENTINEL")):
                response = self.client.post("/", json={"type": "today_genie"}, headers={"X-Genie-Internal-Job-Token": "synthetic-secret"})
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()["detail"]["reason"], "vertex_transient_unclassified")
        self.assertNotIn("PUBLIC_PRIVATE_TRANSIENT_SENTINEL", response.text)

    def test_public_static_hides_internal_image_manifest_but_serves_public_image(self) -> None:
        manifest = self.client.get(
            "/static/email/GENIE_EMAIL_today_genie_latest_manifest.json"
        )
        image = self.client.get("/static/email/GENIE_EMAIL_today_genie_top_latest.jpg")
        self.assertEqual(manifest.status_code, 404)
        self.assertEqual(image.status_code, 200)

    def test_orchestrator_forwards_shared_token_without_retrying_auth_failure(self) -> None:
        import orchestrator

        requests = []
        class RejectingOpener:
            def open(self, request, timeout):
                requests.append(request)
                raise urllib.error.HTTPError(
                    request.full_url,
                    403,
                    "Forbidden",
                    {},
                    io.BytesIO(b'{"detail":{"reason":"forbidden"}}'),
                )

        with mock.patch.dict(
            os.environ, {"GENIE_INTERNAL_JOB_TOKEN": "synthetic-secret"}, clear=True
        ):
            with mock.patch("urllib.request.build_opener", return_value=RejectingOpener()) as build_opener:
                result = orchestrator.run_genie_job("today_genie", transport_retries=0)
        self.assertEqual(len(requests), 1)
        self.assertEqual(
            requests[0].get_header("X-genie-internal-job-token"),
            "synthetic-secret",
        )
        self.assertEqual(build_opener.call_count, 1)
        self.assertEqual(result.response_status, 403)

    def test_internal_token_never_redirects_to_another_host_or_relative_target(self) -> None:
        import urllib.request
        import orchestrator

        handler = orchestrator._NoRedirectHandler()
        request = urllib.request.Request(
            "https://original.invalid/private", headers={"X-Genie-Internal-Job-Token": "synthetic"}
        )
        for target in (
            "https://different.invalid/collect",
            "/relative-target",
            "https://original.invalid/same-origin-target",
        ):
            self.assertIsNone(handler.redirect_request(request, None, 302, "Found", {}, target))

    def test_model_call_status_stays_unknown_without_direct_evidence(self) -> None:
        self.assertIsNone(_model_call_status_from_response(200, {"validation_result": "block"}))
        self.assertIsNone(_model_call_status_from_response(500, {"error": "provider_error"}))
        self.assertIsNone(_model_call_status_from_response(422, {"detail": "malformed"}))
        self.assertIsNone(_model_call_status_from_response(None, {}))

    def test_model_call_status_false_requires_proven_pre_model_auth_rejection(self) -> None:
        self.assertIs(
            _model_call_status_from_response(403, {"detail": {"reason": "forbidden"}}),
            False,
        )
        self.assertIs(
            _model_call_status_from_response(
                503, {"detail": {"reason": "internal_job_token_not_configured"}}
            ),
            False,
        )
        self.assertIs(
            _model_call_status_from_response(200, {"model_call_evidence": [{"model": "test"}]}),
            True,
        )


if __name__ == "__main__":
    unittest.main()
