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
