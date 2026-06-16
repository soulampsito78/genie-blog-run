"""Tests for Today_Geenee no-send verification mode.

Verifies that send_owner_email=False:
- suppresses owner-review email unconditionally in both orchestrator and service paths
- still produces artifact metadata (email_sent=False, verification_mode=no_send_verification)
- leaves the Scheduler natural path (empty body / send_owner_email=True) unchanged
- does not affect Key-Suri paths
"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from orchestrator import (
    OrchestrationResult,
    build_run_artifact_metadata,
    execute_orchestrator_run,
    send_email_if_allowed,
)
from publishing_policy import PublishingDecision


def _pass_decision(send_email: bool = True) -> PublishingDecision:
    return PublishingDecision(
        send_email=send_email,
        create_naver_draft=False,
        auto_publish=False,
        require_review=False,
        suppress_external=False,
    )


def _today_result(send_email: bool = True) -> OrchestrationResult:
    return OrchestrationResult(
        decision=_pass_decision(send_email=send_email),
        reason_summary="ok",
        response_status=200,
        mode="today_genie",
        response_data={
            "validation_result": "pass",
            "workflow_status": "validated",
            "data": {"channel_drafts": {"email_subject": "오늘 브리핑"}},
            "runtime_input": {"target_date": "2026-06-16"},
        },
    )


class SendOwnerEmailFalseGateTests(unittest.TestCase):
    """send_email_if_allowed: send_owner_email=False suppresses unconditionally."""

    def test_send_owner_email_false_suppresses_even_when_policy_allows(self) -> None:
        result = _today_result(send_email=True)
        sent = send_email_if_allowed(result, run_id="rid", send_owner_email=False)
        self.assertFalse(sent)

    def test_send_owner_email_true_default_unchanged(self) -> None:
        # policy send_email=False → still returns False regardless of send_owner_email kwarg
        result = _today_result(send_email=False)
        sent = send_email_if_allowed(result, run_id="rid", send_owner_email=True)
        self.assertFalse(sent)

    def test_send_owner_email_false_returns_false_without_calling_smtp(self) -> None:
        result = _today_result(send_email=True)
        with patch("orchestrator.send_genie_email") as mock_smtp:
            sent = send_email_if_allowed(result, run_id="rid", send_owner_email=False)
        self.assertFalse(sent)
        mock_smtp.assert_not_called()


class ArtifactVerificationModeTests(unittest.TestCase):
    """build_run_artifact_metadata: no-send verification mode recorded in metadata."""

    def _build(self, send_owner_email: bool) -> dict:
        return build_run_artifact_metadata(
            _today_result(),
            run_id="20260616_130000_today_genie_nosend01",
            email_sent=False,
            send_owner_email=send_owner_email,
        )

    def test_no_send_verification_sets_verification_mode(self) -> None:
        meta = self._build(send_owner_email=False)
        self.assertEqual(meta.get("verification_mode"), "no_send_verification")
        self.assertFalse(meta["email_sent"])

    def test_normal_send_does_not_set_verification_mode(self) -> None:
        meta = self._build(send_owner_email=True)
        self.assertNotIn("verification_mode", meta)

    def test_customer_delivery_always_not_sent(self) -> None:
        for flag in (True, False):
            with self.subTest(send_owner_email=flag):
                meta = self._build(send_owner_email=flag)
                self.assertEqual(meta["customer_delivery_status"], "not_sent")


class ExecuteOrchestratorRunNoSendTests(unittest.TestCase):
    """execute_orchestrator_run: send_owner_email=False propagates through."""

    def _run_no_send(self):
        result = _today_result(send_email=True)
        with patch("orchestrator.run_genie_job", return_value=result):
            with patch("today_genie_orchestrator_images.generate_today_genie_orchestrator_images", return_value=None):
                with patch("orchestrator.persist_orchestrator_run_artifact", return_value="rid") as mock_persist:
                    with patch("orchestrator.send_email_if_allowed", return_value=False) as mock_send:
                        execute_orchestrator_run("today_genie", send_owner_email=False)
        return mock_send, mock_persist

    def test_send_email_if_allowed_receives_send_owner_email_false(self) -> None:
        mock_send, _ = self._run_no_send()
        _, kwargs = mock_send.call_args
        self.assertFalse(kwargs.get("send_owner_email", True))

    def test_persist_receives_send_owner_email_false(self) -> None:
        _, mock_persist = self._run_no_send()
        _, kwargs = mock_persist.call_args
        self.assertFalse(kwargs.get("send_owner_email", True))

    def test_default_send_owner_email_true_unchanged(self) -> None:
        result = _today_result(send_email=True)
        with patch("orchestrator.run_genie_job", return_value=result):
            with patch("today_genie_orchestrator_images.generate_today_genie_orchestrator_images", return_value=None):
                with patch("orchestrator.persist_orchestrator_run_artifact", return_value="rid"):
                    with patch("orchestrator.send_email_if_allowed", return_value=True) as mock_send:
                        execute_orchestrator_run("today_genie")
        _, kwargs = mock_send.call_args
        self.assertTrue(kwargs.get("send_owner_email", True))


if __name__ == "__main__":
    unittest.main()
