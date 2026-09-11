import datetime as dt
import hashlib
import hmac
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import admin_beta_delegation as delegation
import admin_safety_store as store
import admin_store
import delegated_delivery_safety as safety
import delegated_gate as gate


NOW = dt.datetime(2026, 9, 14, 0, 30, tzinfo=dt.timezone.utc)
KEY = gate.ReviewerKey("work-reviewer", b"release-gate-test-key-material-1234567890")


class DelegatedGrantReleasePathTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.recipients = [f"beta-{index:02d}@example.test" for index in range(12)]
        config = {
            "recipients": self.recipients,
            "disabled_recipients": [],
            "version": 6,
            "load_ok": True,
        }
        patches = (
            mock.patch.object(store, "_uses_gcs_backend", return_value=False),
            mock.patch.dict(
                os.environ,
                {
                    "GENIE_ADMIN_SAFETY_LOCAL_DIR": str(
                        Path(self.temp.name) / "safety"
                    ),
                    "DELEGATED_SEND_MODE": "ON",
                },
                clear=False,
            ),
            mock.patch.object(admin_store, "load_beta_recipient_config", return_value=config),
            mock.patch("email_sender.parse_customer_to_addrs", return_value=[]),
        )
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.grant = delegation.activate_admin_beta_delegation(
            products=delegation.ALLOWED_MODES,
            operator_id="owner-one-time-delegation",
            now=NOW,
        )
        safety.record_delivery_cutover(
            starts_on=NOW.date(),
            inventory_sha256="a" * 64,
            evidence_refs=["release-gate-inventory"],
            operator_id="owner-one-time-delegation",
            all_writers_use_publication_guard=True,
        )

    def candidate(self, suffix="abcdef12"):
        authority = delegation.AdminBetaRecipientAuthority()
        plan = authority.prepare("keysuri_global_tech", NOW.date(), NOW)
        image = Path(self.temp.name) / f"{suffix}.jpg"
        image.write_bytes(b"release gate exact image")
        meta = {
            "run_id": f"20260914_090000_keysuri_global_tech_{suffix}",
            "mode": "keysuri_global_tech",
            "validation_result": "pass",
            "artifact_status": "emailed",
            "owner_review_status": "pending_review",
            "customer_surface_status": "CUSTOMER_SURFACE_PASS",
            "customer_delivery_status": "not_sent",
            "safety_verdict": "SAFE",
            "editorial_verdict": "READY",
            "reader_surface_enforced": True,
            "reader_surface_complete": True,
            "reader_surface_ready_count": 5,
        }

        def prepared(*args, **kwargs):
            return {
                "ok": True,
                "subject": "Exact reviewed briefing",
                "html_body": f'<p>{gate._DELEGATED_COPY}</p><a href="https://example.test/source">source</a>',
                "inline_jpeg_parts": [(str(image), "top", "top.jpg")],
                "recipients": kwargs["recipients_override"],
            }

        patcher = mock.patch(
            "keysuri_customer_delivery.prepare_keysuri_customer_delivery", prepared
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        received = {
            "mailbox_id": "review-mailbox",
            "message_id": "gmail-message-id",
            "internet_message_id": "message@example.test",
            "received_at": (NOW - dt.timedelta(minutes=10)).isoformat(),
            "raw_mime_sha256": "b" * 64,
            "render_capture_sha256": "c" * 64,
            "customer_render_capture_sha256": "d" * 64,
        }
        return gate.freeze_candidate(
            meta=meta,
            saved_html="<p>received briefing</p>",
            received_message=received,
            recipient_plan=plan,
        ), authority

    @staticmethod
    def signed(candidate, verdict="PASS", event_id="release_event_000001"):
        event = {
            "event_id": event_id,
            "run_id": candidate.binding["run_id"],
            "audience": "genie-delegated-review",
            "policy_version": gate.POLICY_VERSION,
            "issued_at": NOW.isoformat(),
            "candidate_sha256": candidate.candidate_sha256,
            "review": {
                **candidate.binding,
                "policy_version": gate.POLICY_VERSION,
                "reviewer_agent": KEY.principal,
                "reviewer_model": "gpt-5.3-codex-spark",
                "verdict": verdict,
                "reviewed_at": (NOW - dt.timedelta(minutes=1)).isoformat(),
                "checks": {key: "PASS" for key in gate.REQUIRED_CHECKS},
                "evidence": {key: [f"evidence://{key}"] for key in gate.REQUIRED_CHECKS},
                "critical_sources_checked": True,
                "anomalies": [],
            },
        }
        raw = gate.canonical(event).encode("utf-8")
        headers = {
            "x-genie-review-key-id": "runner-v1",
            "x-genie-review-signature": hmac.new(
                KEY.secret, raw, hashlib.sha256
            ).hexdigest(),
        }
        return raw, headers

    def settings(self, mode="ON"):
        return gate.GateSettings(
            mode=mode,
            authorized_policy=gate.POLICY_VERSION,
            reviewer_keys={"runner-v1": KEY},
        )

    def test_grant_to_signed_pass_to_truthful_send_and_replay_block(self):
        candidate, authority = self.candidate()
        raw, headers = self.signed(candidate)
        sent, rows = [], []

        def update(_run_id, mutate):
            row = dict(rows[-1] if rows else json.loads(candidate.meta_json))
            mutate(row)
            rows.append(row)
            return row

        def product_send(_saved_html, _meta, *, prepared_delivery):
            sent.append(prepared_delivery)
            return True

        class FixedDateTime(dt.datetime):
            @classmethod
            def now(cls, tz=None):
                return NOW if tz is not None else NOW.replace(tzinfo=None)

        with (
            mock.patch.object(gate, "datetime", FixedDateTime),
            mock.patch.object(admin_store, "update_run_artifact", side_effect=update),
            mock.patch(
                "keysuri_customer_delivery.send_keysuri_customer_final_email",
                side_effect=product_send,
            ),
            mock.patch(
                "email_sender.last_send_trace",
                return_value={
                    "smtp_submission_started": True,
                    "smtp_accepted_recipient_count": 12,
                },
            ),
            mock.patch("email_sender.last_send_diagnostic", return_value=""),
        ):
            result = gate.process_review_event(
                raw,
                headers,
                loader=type(
                    "Loader", (), {"load": lambda _, run_id, now: candidate}
                )(),
                recipient_authority=authority,
                now=NOW,
                settings=self.settings(),
            )
        self.assertEqual(result["verdict"], "PASS", result)
        self.assertTrue(result["customer_send_authorized"])
        self.assertEqual(result["approval_source"], "DELEGATED_WORK_REVIEW")
        self.assertEqual(result["approval_authority"], "ADMIN_BETA_DELEGATION")
        self.assertEqual(result["authority_grant_id"], self.grant["grant_id"])
        self.assertEqual(len(sent[0]["recipients"]), 12)
        self.assertEqual(sent[0]["html_body"], candidate.customer_html)
        self.assertEqual(rows[-1]["approval_authority"], "ADMIN_BETA_DELEGATION")
        replay = gate.process_review_event(
            raw,
            headers,
            loader=type("Loader", (), {"load": lambda _, run_id, now: candidate})(),
            recipient_authority=authority,
            now=NOW,
            settings=self.settings(),
            sender=lambda *args, **kwargs: self.fail("replay must not submit"),
        )
        self.assertEqual(replay["reason_codes"], ["REPLAYED_REVIEW_EVENT_RECONCILE"])

    def test_revocation_at_actual_submit_boundary_blocks_provider(self):
        candidate, inner_authority = self.candidate("abcdef14")
        raw, headers = self.signed(candidate, event_id="release_event_000004")
        sends = []

        class RevokeOnFinalBoundary:
            calls = 0

            def revalidate(self, plan, now):
                self.calls += 1
                if self.calls == 3:
                    delegation.revoke_admin_beta_delegation(
                        operator_id="release-gate-revoker",
                        reason="prove final provider boundary",
                        now=NOW,
                    )
                return inner_authority.revalidate(plan, now)

        def update(_run_id, mutate):
            row = json.loads(candidate.meta_json)
            mutate(row)
            return row

        with (
            mock.patch.object(
                admin_store,
                "update_run_artifact",
                side_effect=update,
            ),
            mock.patch(
                "keysuri_customer_delivery.send_keysuri_customer_final_email",
                side_effect=lambda *args, **kwargs: sends.append(True) or True,
            ),
        ):
            result = gate.process_review_event(
                raw,
                headers,
                loader=type(
                    "Loader", (), {"load": lambda _, run_id, now: candidate}
                )(),
                recipient_authority=RevokeOnFinalBoundary(),
                now=NOW,
                settings=self.settings(),
            )
        self.assertEqual(result["reason_codes"], ["ADMIN_BETA_DELEGATION_NOT_ACTIVE"])
        self.assertFalse(result["customer_send_authorized"])
        self.assertEqual(sends, [])

    def test_non_pass_and_off_mode_never_submit(self):
        candidate, authority = self.candidate("abcdef13")
        sent = []
        raw, headers = self.signed(
            candidate, verdict="HOLD_INCOMPLETE", event_id="release_event_000002"
        )
        hold = gate.process_review_event(
            raw,
            headers,
            loader=type("Loader", (), {"load": lambda _, run_id, now: candidate})(),
            recipient_authority=authority,
            now=NOW,
            settings=self.settings(),
            sender=lambda *args, **kwargs: sent.append(True),
        )
        self.assertFalse(hold["customer_send_authorized"])
        off = gate.process_review_event(
            *self.signed(candidate, event_id="release_event_000003"),
            loader=type("Loader", (), {"load": lambda _, run_id, now: candidate})(),
            recipient_authority=authority,
            now=NOW,
            settings=self.settings("OFF"),
            sender=lambda *args, **kwargs: sent.append(True),
        )
        self.assertEqual(off["reason_codes"], ["DELEGATED_SEND_MODE_OFF"])
        self.assertEqual(sent, [])


if __name__ == "__main__":
    unittest.main()
