from __future__ import annotations

import io
import json
import logging
import logging.config
import os
import unittest
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, List
from unittest.mock import MagicMock, patch

from genie_schedule_policy import is_scheduled_trigger_source
from keysuri_live_source_smoke import LiveSourceSmokeResult, PROGRAM_GLOBAL
from keysuri_service_full_run import run_keysuri_service_full_run
from service_full_run_contract import IMAGE_SOURCE_GENERATED, ServiceImageOutcome
from owner_review_failure_events import (
    OWNER_REVIEW_FAILURE_EVENT_LOGGER,
    OWNER_REVIEW_RUN_FAILED_EVENT,
    build_owner_review_run_failed_payload,
    configure_owner_review_failure_event_logger,
    emit_owner_review_failure_from_artifact_meta,
    emit_owner_review_run_failed_once,
    infer_first_failed_stage,
    reset_owner_review_failure_event_dedupe_for_tests,
    should_emit_owner_review_failure_event,
)

_SCHEDULED_TRIGGER = "scheduled_owner_review"


@contextmanager
def capture_failure_events() -> Iterator[io.StringIO]:
    """Capture the exact bytes the structured event handler writes.

    ``assertLogs`` swaps the logger's handlers, so it cannot observe the real
    formatter. These tests care about the raw line, so the handler stream is
    redirected instead.
    """
    event_logger = configure_owner_review_failure_event_logger()
    buffer = io.StringIO()
    originals = [
        (handler, handler.stream)
        for handler in event_logger.handlers
        if isinstance(handler, logging.StreamHandler)
    ]
    for handler, _stream in originals:
        handler.stream = buffer
    try:
        yield buffer
    finally:
        for handler, stream in originals:
            handler.stream = stream


def emitted_lines(buffer: io.StringIO) -> List[str]:
    return [line for line in buffer.getvalue().splitlines() if line.strip()]


def emitted_events(buffer: io.StringIO) -> List[dict]:
    return [
        json.loads(line)
        for line in emitted_lines(buffer)
        if OWNER_REVIEW_RUN_FAILED_EVENT in line
    ]


def _minimal_contract_preview_document() -> str:
    return (
        '<!DOCTYPE html><html lang="ko"><head><meta charset="UTF-8"/>'
        "<style>.premium-briefing.theme-global{--g-accent:#3f7ecb;}</style>"
        '</head><body class="premium-briefing theme-global"><div class="briefing-shell">'
        '<header class="premium-hero" id="premium-hero">'
        '<h1 class="hero-title">키수리 글로벌 테크 브리핑</h1>'
        '<img src="cid:keysuri_topshot_global_20260611" class="top-shot-hero"/>'
        "</header></div></body></html>"
    )


def _mock_keysuri_watermark(source: Path, target: Path) -> Path:
    src = Path(source)
    dst = Path(target)
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(src.read_bytes() + b"MirAI:ON")
    return dst.resolve()


class StructuredEventLoggingTests(unittest.TestCase):
    """P1-1: the emitted line must be parseable by Cloud Logging as JSON."""

    def setUp(self) -> None:
        reset_owner_review_failure_event_dedupe_for_tests()

    def _apply_production_logging_config(self) -> None:
        """Reproduce `uvicorn main:app` startup logging exactly."""
        from uvicorn.config import LOGGING_CONFIG

        logging.config.dictConfig(LOGGING_CONFIG)
        import main  # noqa: F401  (import runs configure_application_logging)

        main.configure_application_logging()

    def test_event_line_is_bare_single_line_json(self) -> None:
        self._apply_production_logging_config()
        with capture_failure_events() as buffer:
            emitted = emit_owner_review_run_failed_once(
                program_id=PROGRAM_GLOBAL,
                run_id="raw-json-1",
                trigger_source=_SCHEDULED_TRIGGER,
                error_code="validation_blocked",
                issue_codes=["gemini_json_missing_required_keys"],
            )
        self.assertTrue(emitted)
        raw = buffer.getvalue()
        lines = emitted_lines(buffer)
        self.assertEqual(len(lines), 1)
        line = lines[0]
        # No asctime/level/name prefix, nothing trailing but the newline.
        self.assertTrue(line.startswith("{"))
        self.assertTrue(line.endswith("}"))
        self.assertEqual(raw, line + "\n")
        payload = json.loads(line)
        self.assertEqual(payload["event"], OWNER_REVIEW_RUN_FAILED_EVENT)
        self.assertEqual(payload["severity"], "ERROR")
        self.assertEqual(payload["trigger_source"], _SCHEDULED_TRIGGER)
        self.assertEqual(payload["first_failed_stage"], "generation_validation")

    def test_documented_textpayload_fallback_substring_matches_output(self) -> None:
        """The doc's fallback filter substring must match the real serializer."""
        self._apply_production_logging_config()
        with capture_failure_events() as buffer:
            emit_owner_review_run_failed_once(
                program_id=PROGRAM_GLOBAL,
                run_id="raw-json-fallback",
                trigger_source=_SCHEDULED_TRIGGER,
                error_code="validation_blocked",
            )
        self.assertIn('"event": "owner_review_run_failed"', buffer.getvalue())

    def test_application_logger_format_is_unchanged(self) -> None:
        self._apply_production_logging_config()
        app_logger = logging.getLogger("keysuri_service_full_run")
        buffer = io.StringIO()
        originals = [
            (handler, handler.stream)
            for handler in app_logger.handlers
            if isinstance(handler, logging.StreamHandler)
        ]
        for handler, _stream in originals:
            handler.stream = buffer
        try:
            app_logger.info("ordinary application line")
        finally:
            for handler, stream in originals:
                handler.stream = stream
        text = buffer.getvalue()
        if text:
            # App logs keep the human-readable prefixed format (not bare JSON).
            self.assertIn("ordinary application line", text)
            self.assertFalse(text.strip().startswith("{"))

    def test_repeated_configure_does_not_duplicate_handlers(self) -> None:
        for _ in range(3):
            event_logger = configure_owner_review_failure_event_logger()
        marked = [
            handler
            for handler in event_logger.handlers
            if getattr(handler, "_genie_owner_review_failure_event_handler", False)
        ]
        self.assertEqual(len(marked), 1)
        with capture_failure_events() as buffer:
            emit_owner_review_run_failed_once(
                program_id=PROGRAM_GLOBAL,
                run_id="no-dupe-handler",
                trigger_source=_SCHEDULED_TRIGGER,
                error_code="validation_blocked",
            )
        self.assertEqual(len(emitted_events(buffer)), 1)

    def test_event_logger_does_not_propagate(self) -> None:
        event_logger = configure_owner_review_failure_event_logger()
        self.assertFalse(event_logger.propagate)
        self.assertEqual(event_logger.name, OWNER_REVIEW_FAILURE_EVENT_LOGGER)

    def test_third_party_logger_levels_remain_quiet(self) -> None:
        self._apply_production_logging_config()
        for name in ("google", "urllib3", "httpx"):
            self.assertGreaterEqual(
                logging.getLogger(name).level, logging.WARNING
            )


class ScheduledTriggerPolicyTests(unittest.TestCase):
    """P1-2: the gate must follow the repo's canonical scheduled policy."""

    def setUp(self) -> None:
        reset_owner_review_failure_event_dedupe_for_tests()

    def test_canonical_scheduled_aliases_are_eligible(self) -> None:
        for trigger in (
            "scheduled_owner_review",
            "cloud_scheduler",
            "scheduler",
            "internal_job",
            "scheduled_service_full_run",
        ):
            with self.subTest(trigger=trigger):
                self.assertTrue(is_scheduled_trigger_source(trigger))
                self.assertTrue(
                    should_emit_owner_review_failure_event(trigger_source=trigger)
                )

    def test_manual_and_non_scheduled_triggers_are_rejected(self) -> None:
        for trigger in (
            "manual_service_full_run",
            "manual",
            "manual_korea_validation_20260709",
            "admin_text_only_reissue",
            "dry_run",
            "test",
            "local",
            "preview",
            "unknown",
            "",
            None,
        ):
            with self.subTest(trigger=trigger):
                self.assertFalse(
                    should_emit_owner_review_failure_event(trigger_source=trigger)
                )

    def test_dry_run_is_rejected_even_when_scheduled(self) -> None:
        self.assertFalse(
            should_emit_owner_review_failure_event(
                trigger_source=_SCHEDULED_TRIGGER, dry_run=True
            )
        )

    def test_gate_matches_central_policy_exactly(self) -> None:
        """No parallel allow-list: the gate is the central policy plus dry_run."""
        for trigger in (
            "scheduled_owner_review",
            "scheduled_service_full_run",
            "scheduled_anything_else",
            "cloud_scheduler",
            "scheduler",
            "internal_job",
            "manual_service_full_run",
            "admin_image_only_reissue",
            "dry_run",
            "test",
            "",
        ):
            with self.subTest(trigger=trigger):
                self.assertEqual(
                    should_emit_owner_review_failure_event(trigger_source=trigger),
                    is_scheduled_trigger_source(trigger),
                )


class FirstFailedStageTests(unittest.TestCase):
    def test_real_error_codes_map_to_documented_stages(self) -> None:
        cases = [
            ("validation_blocked", "block", "generation_validation"),
            ("gemini_or_smoke_failed", "block", "generation_validation"),
            ("IMAGE_GENERATION_FAILED", "pass", "image_generation"),
            ("keysuri_top_shot_watermark_failed", "pass", "image_generation"),
            ("keysuri_global_post_render_qa_blocked", "pass", "email_rendering"),
            ("keysuri_korea_post_render_qa_blocked", "pass", "email_rendering"),
            ("smtp_send_failed", "pass", "email_delivery"),
            ("artifact_persistence_failed", "pass", "artifact_persistence"),
            ("service_unexpected_exception", "pass", "service_exception"),
        ]
        for code, validation_result, expected in cases:
            with self.subTest(code=code):
                self.assertEqual(
                    infer_first_failed_stage(
                        error_code=code, validation_result=validation_result
                    ),
                    expected,
                )

    def test_source_shortage_hold_is_distinguished_from_a_contract_block(self) -> None:
        """Holds reach the finalizer as validation_result="block"; hold_reason decides."""
        self.assertEqual(
            infer_first_failed_stage(
                error_code="validation_blocked",
                validation_result="block",
                hold_reason="insufficient_fresh_candidates",
            ),
            "validation_hold",
        )
        self.assertEqual(
            infer_first_failed_stage(
                error_code="validation_blocked",
                validation_result="block",
                hold_reason="",
            ),
            "generation_validation",
        )


class OwnerReviewFailureEventUnitTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_owner_review_failure_event_dedupe_for_tests()

    def test_payload_has_required_fields_and_no_secrets(self) -> None:
        payload = build_owner_review_run_failed_payload(
            program_id="keysuri_global_tech",
            run_id="run-1",
            trigger_source=_SCHEDULED_TRIGGER,
            first_failed_stage="generation_validation",
            error_code="validation_blocked",
            issue_codes=["gemini_json_missing_required_keys"],
            email_sent=False,
            artifact_url="gs://bucket/run-1.json",
            revision="rev-abc",
        )
        self.assertEqual(payload["event"], OWNER_REVIEW_RUN_FAILED_EVENT)
        self.assertEqual(payload["severity"], "ERROR")
        self.assertEqual(payload["program_id"], "keysuri_global_tech")
        self.assertEqual(payload["run_id"], "run-1")
        self.assertEqual(payload["error_code"], "validation_blocked")
        self.assertTrue(payload["artifact_saved"])
        self.assertIn("gemini_json_missing_required_keys", payload["issue_codes"])
        serialized = json.dumps(payload)
        for banned in ("password", "smtp", "raw_response", "@example.com", "api_key"):
            self.assertNotIn(banned, serialized.lower())

    def test_failed_artifact_save_blanks_url_and_flags_payload(self) -> None:
        payload = build_owner_review_run_failed_payload(
            program_id="keysuri_global_tech",
            run_id="run-2",
            trigger_source=_SCHEDULED_TRIGGER,
            first_failed_stage="email_delivery",
            error_code="smtp_send_failed",
            artifact_url="gs://bucket/stale.json",
            artifact_saved=False,
        )
        self.assertFalse(payload["artifact_saved"])
        self.assertEqual(payload["artifact_url"], "")

    def test_duplicate_finalizer_emits_once(self) -> None:
        with capture_failure_events() as buffer:
            first = emit_owner_review_run_failed_once(
                program_id="keysuri_global_tech",
                run_id="run-dedupe",
                trigger_source=_SCHEDULED_TRIGGER,
                error_code="validation_blocked",
            )
            second = emit_owner_review_run_failed_once(
                program_id="keysuri_global_tech",
                run_id="run-dedupe",
                trigger_source=_SCHEDULED_TRIGGER,
                error_code="validation_blocked",
            )
        self.assertTrue(first)
        self.assertFalse(second)
        self.assertEqual(len(emitted_events(buffer)), 1)

    def test_dedupe_key_is_program_scoped(self) -> None:
        with capture_failure_events() as buffer:
            self.assertTrue(
                emit_owner_review_run_failed_once(
                    program_id="keysuri_global_tech",
                    run_id="shared-run-id",
                    trigger_source=_SCHEDULED_TRIGGER,
                    error_code="validation_blocked",
                )
            )
            self.assertTrue(
                emit_owner_review_run_failed_once(
                    program_id="keysuri_korea_tech",
                    run_id="shared-run-id",
                    trigger_source=_SCHEDULED_TRIGGER,
                    error_code="validation_blocked",
                )
            )
        self.assertEqual(len(emitted_events(buffer)), 2)

    def test_manual_and_dry_run_emit_nothing(self) -> None:
        with capture_failure_events() as buffer:
            self.assertFalse(
                emit_owner_review_run_failed_once(
                    program_id="keysuri_global_tech",
                    run_id="run-manual",
                    trigger_source="manual_service_full_run",
                    error_code="validation_blocked",
                )
            )
            self.assertFalse(
                emit_owner_review_run_failed_once(
                    program_id="keysuri_global_tech",
                    run_id="run-dry",
                    trigger_source=_SCHEDULED_TRIGGER,
                    error_code="validation_blocked",
                    dry_run=True,
                )
            )
        self.assertEqual(emitted_events(buffer), [])

    def test_meta_wrapper_honours_explicit_stage_and_error_code(self) -> None:
        with capture_failure_events() as buffer:
            emit_owner_review_failure_from_artifact_meta(
                {
                    "program_id": PROGRAM_GLOBAL,
                    "run_id": "meta-override",
                    "trigger_source": _SCHEDULED_TRIGGER,
                    "error_code": "validation_blocked",
                },
                first_failed_stage="email_delivery",
                error_code="smtp_send_failed",
            )
        events = emitted_events(buffer)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["first_failed_stage"], "email_delivery")
        self.assertEqual(events[0]["error_code"], "smtp_send_failed")


class OwnerReviewFailureServiceIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_owner_review_failure_event_dedupe_for_tests()

    def _failed_smoke(self) -> LiveSourceSmokeResult:
        return LiveSourceSmokeResult(
            ok=False,
            program_id=PROGRAM_GLOBAL,
            source_pack_path="/tmp/global-pack.json",
            html_path="",
            fetched_item_count=3,
            feed_urls_used=[],
            sample_marker_pass=False,
            called_gemini=True,
            use_gemini=True,
            parse_status="parsed_invalid",
            validation_issues=["gemini_json_missing_required_keys"],
            generation_diagnostics={
                "global_recovery_attempted": True,
                "global_recovery_result": "failed",
                "generation_recovery_attempted": True,
                "generation_recovery_result": "failed",
            },
            error="Gemini parse failed",
        )

    @patch("keysuri_service_full_run.save_run_artifact")
    def test_scheduled_final_failure_emits_one_error_event(
        self, _save: MagicMock
    ) -> None:
        smoke = self._failed_smoke()
        with capture_failure_events() as buffer:
            result = run_keysuri_service_full_run(
                PROGRAM_GLOBAL,
                trigger_source=_SCHEDULED_TRIGGER,
                smoke_runner=lambda **_kwargs: smoke,
                image_canary_runner=MagicMock(),
                send_fn=MagicMock(),
            )
        self.assertFalse(result["ok"])
        events = emitted_events(buffer)
        self.assertEqual(len(events), 1)
        payload = events[0]
        self.assertEqual(payload["event"], OWNER_REVIEW_RUN_FAILED_EVENT)
        self.assertEqual(payload["trigger_source"], _SCHEDULED_TRIGGER)
        self.assertEqual(payload["error_code"], "validation_blocked")
        self.assertEqual(payload["first_failed_stage"], "generation_validation")
        self.assertTrue(payload["artifact_saved"])
        self.assertFalse(payload["email_sent"])

    @patch("keysuri_service_full_run.save_run_artifact")
    def test_source_shortage_hold_emits_validation_hold_stage(
        self, _save: MagicMock
    ) -> None:
        smoke = self._failed_smoke()
        smoke.hold_reason = "insufficient_fresh_candidates"
        with capture_failure_events() as buffer:
            result = run_keysuri_service_full_run(
                PROGRAM_GLOBAL,
                trigger_source=_SCHEDULED_TRIGGER,
                smoke_runner=lambda **_kwargs: smoke,
                image_canary_runner=MagicMock(),
                send_fn=MagicMock(),
            )
        self.assertFalse(result["ok"])
        events = emitted_events(buffer)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["first_failed_stage"], "validation_hold")

    @patch("keysuri_service_full_run.save_run_artifact")
    def test_manual_failure_emits_no_event(self, _save: MagicMock) -> None:
        smoke = self._failed_smoke()
        with capture_failure_events() as buffer:
            result = run_keysuri_service_full_run(
                PROGRAM_GLOBAL,
                trigger_source="manual_service_full_run",
                smoke_runner=lambda **_kwargs: smoke,
                image_canary_runner=MagicMock(),
                send_fn=MagicMock(),
            )
        self.assertFalse(result["ok"])
        self.assertEqual(emitted_events(buffer), [])

    def test_dry_run_emits_no_event(self) -> None:
        with capture_failure_events() as buffer:
            result = run_keysuri_service_full_run(
                PROGRAM_GLOBAL,
                trigger_source=_SCHEDULED_TRIGGER,
                dry_run=True,
            )
        self.assertTrue(result.get("dry_run"))
        self.assertEqual(emitted_events(buffer), [])

    def test_intermediate_recovery_failure_alone_does_not_emit(self) -> None:
        """Recovery diagnostics without a scheduled finalizer emit nothing."""
        with capture_failure_events() as buffer:
            self.assertFalse(
                should_emit_owner_review_failure_event(
                    trigger_source="keysuri_global_contract_repair"
                )
            )
        self.assertEqual(emitted_events(buffer), [])

    @patch("keysuri_service_full_run.save_run_artifact")
    def test_artifact_save_failure_still_emits_and_keeps_failure(
        self, mock_save: MagicMock
    ) -> None:
        mock_save.side_effect = OSError("bucket unavailable")
        smoke = self._failed_smoke()
        with capture_failure_events() as buffer:
            result = run_keysuri_service_full_run(
                PROGRAM_GLOBAL,
                trigger_source=_SCHEDULED_TRIGGER,
                smoke_runner=lambda **_kwargs: smoke,
                image_canary_runner=MagicMock(),
                send_fn=MagicMock(),
            )
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "validation_blocked")
        events = emitted_events(buffer)
        self.assertEqual(len(events), 1)
        self.assertFalse(events[0]["artifact_saved"])
        self.assertEqual(events[0]["artifact_url"], "")
        # Primary failure is preserved; the storage fault is only a flag.
        self.assertEqual(events[0]["first_failed_stage"], "generation_validation")

    @patch("keysuri_service_full_run.save_run_artifact")
    @patch("keysuri_service_full_run.emit_owner_review_failure_from_artifact_meta")
    def test_emitter_failure_does_not_mask_run_failure(
        self, mock_emit: MagicMock, _save: MagicMock
    ) -> None:
        mock_emit.side_effect = RuntimeError("logging backend down")
        smoke = self._failed_smoke()
        result = run_keysuri_service_full_run(
            PROGRAM_GLOBAL,
            trigger_source=_SCHEDULED_TRIGGER,
            smoke_runner=lambda **_kwargs: smoke,
            image_canary_runner=MagicMock(),
            send_fn=MagicMock(),
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "validation_blocked")
        mock_emit.assert_called()

    def test_unexpected_exception_emits_event_and_reraises(self) -> None:
        def _boom(**_kwargs):
            raise RuntimeError("smoke runner exploded")

        with capture_failure_events() as buffer:
            with self.assertRaises(RuntimeError):
                run_keysuri_service_full_run(
                    PROGRAM_GLOBAL,
                    trigger_source=_SCHEDULED_TRIGGER,
                    smoke_runner=_boom,
                )
        events = emitted_events(buffer)
        self.assertEqual(len(events), 1)
        payload = events[0]
        self.assertEqual(payload["first_failed_stage"], "service_exception")
        self.assertEqual(payload["error_code"], "service_unexpected_exception")
        self.assertEqual(payload["program_id"], PROGRAM_GLOBAL)
        self.assertTrue(payload["run_id"])
        serialized = json.dumps(payload)
        for banned in ("traceback", "smoke runner exploded", "password", "api_key"):
            self.assertNotIn(banned, serialized.lower())

    def test_unexpected_exception_on_manual_run_emits_nothing(self) -> None:
        def _boom(**_kwargs):
            raise RuntimeError("smoke runner exploded")

        with capture_failure_events() as buffer:
            with self.assertRaises(RuntimeError):
                run_keysuri_service_full_run(
                    PROGRAM_GLOBAL,
                    trigger_source="manual_service_full_run",
                    smoke_runner=_boom,
                )
        self.assertEqual(emitted_events(buffer), [])


class OwnerReviewSmtpFailureEventTests(unittest.TestCase):
    """P1-3: a terminal SMTP failure is still a final scheduled safe-fail."""

    def setUp(self) -> None:
        reset_owner_review_failure_event_dedupe_for_tests()

    @patch("keysuri_service_full_run.apply_keysuri_mirai_on_watermark")
    @patch("keysuri_service_full_run.build_keysuri_prompt_input")
    @patch("keysuri_service_full_run.save_run_artifact")
    @patch("keysuri_service_full_run._render_service_html")
    @patch("keysuri_service_full_run._reload_generated_briefing")
    @patch("keysuri_service_full_run._generate_keysuri_service_image")
    def _run_until_smtp(
        self,
        send_result: bool,
        trigger_source: str,
        mock_image: MagicMock,
        mock_reload: MagicMock,
        mock_render: MagicMock,
        mock_save: MagicMock,
        mock_prompt_input: MagicMock,
        mock_watermark: MagicMock,
    ):
        repo = Path(__file__).resolve().parents[1]
        pack_path = repo / "output" / "keysuri_preview" / "test_pack_alert_smtp.json"
        pack_path.parent.mkdir(parents=True, exist_ok=True)
        pack_path.write_text(
            json.dumps({"sources": [], "program_id": PROGRAM_GLOBAL}), encoding="utf-8"
        )
        raw_path = repo / "output" / "keysuri_preview" / "raw_alert_smtp.txt"
        raw_path.write_text("{}", encoding="utf-8")

        def _smoke(**_kwargs):
            return LiveSourceSmokeResult(
                ok=True,
                program_id=PROGRAM_GLOBAL,
                source_pack_path=str(pack_path),
                html_path=str(repo / "output" / "keysuri_preview" / "h.html"),
                fetched_item_count=5,
                feed_urls_used=["https://x"],
                sample_marker_pass=True,
                called_gemini=True,
                use_gemini=True,
                contract_preview=True,
                parse_status="parsed_valid",
                raw_response_path=str(raw_path),
                preview_overall_status="PASS_OWNER_REVIEW_READY",
                validation_status="PASS",
                side_effects={"called_gemini": True, "called_image_api": False},
            )

        mock_image.return_value = ServiceImageOutcome(
            called_image_api=True,
            image_generation_status="generated",
            image_source=IMAGE_SOURCE_GENERATED,
            generated_image_path="output/images/keysuri_global_canary.jpg",
        )
        img_file = repo / "output" / "images" / "keysuri_global_canary.jpg"
        img_file.parent.mkdir(parents=True, exist_ok=True)
        img_file.write_bytes(b"\xff\xd8\xff" + b"\x00" * 64)
        mock_watermark.side_effect = _mock_keysuri_watermark
        mock_prompt_input.return_value = {
            "program_id": PROGRAM_GLOBAL,
            "prompt_status": "ready_for_generation",
        }
        mock_reload.return_value = {"title": "t", "summary": "s", "top_5_news": []}
        mock_render.side_effect = lambda *_a, **_k: (
            _minimal_contract_preview_document(),
            "output/admin_runs/keysuri_service/x.html",
        )
        send_fn = MagicMock(return_value=send_result)

        with capture_failure_events() as buffer:
            with patch.dict(
                os.environ,
                {
                    "GENIE_OWNER_REVIEW_SEND": "1",
                    "GENIE_ADMIN_PUBLIC_BASE_URL": "https://ex.com",
                },
                clear=False,
            ):
                payload = run_keysuri_service_full_run(
                    PROGRAM_GLOBAL,
                    trigger_source=trigger_source,
                    smoke_runner=_smoke,
                    send_fn=send_fn,
                )
        return payload, emitted_events(buffer), send_fn, mock_save

    def test_smtp_failure_emits_email_delivery_event(self) -> None:
        payload, events, send_fn, mock_save = self._run_until_smtp(
            False, _SCHEDULED_TRIGGER
        )
        self.assertFalse(payload["ok"])
        self.assertTrue(payload["smtp_attempted"])
        self.assertFalse(payload["email_sent"])
        send_fn.assert_called_once()
        mock_save.assert_called_once()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["first_failed_stage"], "email_delivery")
        self.assertEqual(events[0]["error_code"], "smtp_send_failed")
        self.assertFalse(events[0]["email_sent"])
        self.assertTrue(events[0]["artifact_saved"])

    def test_successful_send_emits_no_event(self) -> None:
        payload, events, _send_fn, _save = self._run_until_smtp(
            True, _SCHEDULED_TRIGGER
        )
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["email_sent"])
        self.assertEqual(events, [])

    def test_manual_smtp_failure_emits_no_event(self) -> None:
        payload, events, _send_fn, _save = self._run_until_smtp(
            False, "manual_service_full_run"
        )
        self.assertFalse(payload["ok"])
        self.assertEqual(events, [])


if __name__ == "__main__":
    unittest.main()
