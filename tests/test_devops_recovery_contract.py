from __future__ import annotations

import os
import unittest
from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from internal_auth import verify_internal_request
from main import app, secure_unhandled_exception
from orchestrator import run_genie_job
from security_headers import SecurityHeadersMiddleware


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


if __name__ == "__main__":
    unittest.main()
