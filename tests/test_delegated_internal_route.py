import os
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from main import app


class DelegatedInternalRouteTests(unittest.TestCase):
    def test_route_requires_internal_transport_token(self):
        with mock.patch.dict(
            os.environ, {"GENIE_INTERNAL_JOB_TOKEN": "internal-test-token"}
        ):
            response = TestClient(app).post(
                "/internal/jobs/delegated-review", content=b"{}"
            )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json(), {"ok": False, "error": "forbidden"})

    def test_route_passes_exact_body_and_signature_headers(self):
        raw = b'{"event_id":"exact-event-body"}'
        outcome = {
            "verdict": "PASS",
            "reason_codes": ["AUTHENTICATED_SHADOW_ONLY"],
            "customer_send_authorized": False,
        }
        with mock.patch.dict(
            os.environ, {"GENIE_INTERNAL_JOB_TOKEN": "internal-test-token"}
        ), mock.patch(
            "delegated_gate.run_configured_review_event", return_value=outcome
        ) as run:
            response = TestClient(app).post(
                "/internal/jobs/delegated-review",
                content=raw,
                headers={
                    "X-Genie-Internal-Job-Token": "internal-test-token",
                    "X-Genie-Review-Key-Id": "reviewer-v1",
                    "X-Genie-Review-Signature": "a" * 64,
                },
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), outcome)
        called_raw, called_headers = run.call_args.args
        self.assertEqual(called_raw, raw)
        self.assertEqual(called_headers["x-genie-review-key-id"], "reviewer-v1")
        self.assertEqual(called_headers["x-genie-review-signature"], "a" * 64)


if __name__ == "__main__":
    unittest.main()
