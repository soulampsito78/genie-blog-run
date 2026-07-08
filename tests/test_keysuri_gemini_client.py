from __future__ import annotations

import os
import unittest
from unittest import mock

import keysuri_gemini_client
import main
import service_image_api


class KeysuriGeminiClientModelRoutingTests(unittest.TestCase):
    def _clear_model_env(self):
        return mock.patch.dict(
            os.environ,
            {
                "KEYSURI_BODY_GEMINI_MODEL": "",
                "KEE_SURI_BODY_MODEL": "",
                "VERTEX_MODEL": "",
                "VERTEX_IMAGE_MODEL": "",
                "KEYSURI_GLOBAL_TECH_BODY_GEMINI_MODEL": "",
                "KEYSURI_BODY_GEMINI_MODEL_GLOBAL": "",
                "KEYSURI_KOREA_TECH_BODY_GEMINI_MODEL": "",
                "KEYSURI_BODY_GEMINI_MODEL_KOREA": "",
            },
            clear=False,
        )

    def test_explicit_model_arg_wins(self) -> None:
        with self._clear_model_env():
            with mock.patch.dict(
                os.environ,
                {
                    "KEYSURI_BODY_GEMINI_MODEL": "gemini-3-flash",
                    "KEE_SURI_BODY_MODEL": "alias-model",
                    "VERTEX_MODEL": "shared-model",
                },
                clear=False,
            ):
                self.assertEqual(
                    keysuri_gemini_client.resolve_keysuri_body_model("explicit-model"),
                    "explicit-model",
                )

    def test_keysuri_body_gemini_model_env_wins_over_alias_and_vertex(self) -> None:
        with self._clear_model_env():
            with mock.patch.dict(
                os.environ,
                {
                    "KEYSURI_BODY_GEMINI_MODEL": "gemini-3-flash",
                    "KEE_SURI_BODY_MODEL": "alias-model",
                    "VERTEX_MODEL": "shared-model",
                },
                clear=False,
            ):
                self.assertEqual(
                    keysuri_gemini_client.resolve_keysuri_body_model(),
                    "gemini-3-flash",
                )

    def test_kee_suri_body_model_alias_wins_when_primary_absent(self) -> None:
        with self._clear_model_env():
            with mock.patch.dict(
                os.environ,
                {
                    "KEE_SURI_BODY_MODEL": "alias-model",
                    "VERTEX_MODEL": "shared-model",
                },
                clear=False,
            ):
                self.assertEqual(
                    keysuri_gemini_client.resolve_keysuri_body_model(),
                    "alias-model",
                )

    def test_vertex_model_fallback_preserves_existing_behavior(self) -> None:
        with self._clear_model_env():
            with mock.patch.dict(os.environ, {"VERTEX_MODEL": "shared-model"}, clear=False):
                self.assertEqual(
                    keysuri_gemini_client.resolve_keysuri_body_model(),
                    "shared-model",
                )

    def test_default_model_preserved_when_no_env_or_arg(self) -> None:
        with self._clear_model_env():
            self.assertEqual(
                keysuri_gemini_client.resolve_keysuri_body_model(),
                "gemini-2.5-flash",
            )

    def test_image_model_routing_is_unchanged(self) -> None:
        self.assertEqual(service_image_api.DEFAULT_VERTEX_IMAGE_MODEL, "gemini-2.5-flash-image")

    def test_today_geenee_does_not_share_keysuri_gemini_client(self) -> None:
        self.assertTrue(hasattr(main, "get_model"))
        self.assertIsNot(main.get_model, keysuri_gemini_client.call_keysuri_gemini_text)

    def test_global_program_prefers_global_specific_env_over_shared(self) -> None:
        with self._clear_model_env():
            with mock.patch.dict(
                os.environ,
                {
                    "KEYSURI_GLOBAL_TECH_BODY_GEMINI_MODEL": "gemini-3-flash-preview",
                    "KEYSURI_BODY_GEMINI_MODEL": "gemini-2.5-flash",
                },
                clear=False,
            ):
                self.assertEqual(
                    keysuri_gemini_client.resolve_keysuri_body_model(program_id="keysuri_global_tech"),
                    "gemini-3-flash-preview",
                )

    def test_global_program_falls_back_to_alias_env_name(self) -> None:
        with self._clear_model_env():
            with mock.patch.dict(
                os.environ,
                {
                    "KEYSURI_BODY_GEMINI_MODEL_GLOBAL": "gemini-3-flash-preview-alias",
                    "KEYSURI_BODY_GEMINI_MODEL": "gemini-2.5-flash",
                },
                clear=False,
            ):
                self.assertEqual(
                    keysuri_gemini_client.resolve_keysuri_body_model(program_id="keysuri_global_tech"),
                    "gemini-3-flash-preview-alias",
                )

    def test_korea_program_prefers_korea_specific_env_over_shared(self) -> None:
        with self._clear_model_env():
            with mock.patch.dict(
                os.environ,
                {
                    "KEYSURI_KOREA_TECH_BODY_GEMINI_MODEL": "gemini-2.5-flash",
                    "KEYSURI_BODY_GEMINI_MODEL": "gemini-3-flash-preview",
                },
                clear=False,
            ):
                self.assertEqual(
                    keysuri_gemini_client.resolve_keysuri_body_model(program_id="keysuri_korea_tech"),
                    "gemini-2.5-flash",
                )

    def test_korea_program_falls_back_to_alias_env_name(self) -> None:
        with self._clear_model_env():
            with mock.patch.dict(
                os.environ,
                {
                    "KEYSURI_BODY_GEMINI_MODEL_KOREA": "gemini-2.5-flash-alias",
                    "KEYSURI_BODY_GEMINI_MODEL": "gemini-3-flash-preview",
                },
                clear=False,
            ):
                self.assertEqual(
                    keysuri_gemini_client.resolve_keysuri_body_model(program_id="keysuri_korea_tech"),
                    "gemini-2.5-flash-alias",
                )

    def test_program_specific_env_absent_falls_back_to_shared_keysuri_body_model(self) -> None:
        with self._clear_model_env():
            with mock.patch.dict(
                os.environ, {"KEYSURI_BODY_GEMINI_MODEL": "gemini-3-flash-preview"}, clear=False
            ):
                self.assertEqual(
                    keysuri_gemini_client.resolve_keysuri_body_model(program_id="keysuri_global_tech"),
                    "gemini-3-flash-preview",
                )
                self.assertEqual(
                    keysuri_gemini_client.resolve_keysuri_body_model(program_id="keysuri_korea_tech"),
                    "gemini-3-flash-preview",
                )

    def test_explicit_model_arg_wins_even_with_program_id(self) -> None:
        with self._clear_model_env():
            with mock.patch.dict(
                os.environ,
                {
                    "KEYSURI_GLOBAL_TECH_BODY_GEMINI_MODEL": "gemini-3-flash-preview",
                },
                clear=False,
            ):
                self.assertEqual(
                    keysuri_gemini_client.resolve_keysuri_body_model(
                        "explicit-override", program_id="keysuri_global_tech"
                    ),
                    "explicit-override",
                )

    def test_vertex_model_fallback_still_applies_with_program_id_but_no_program_env(self) -> None:
        with self._clear_model_env():
            with mock.patch.dict(os.environ, {"VERTEX_MODEL": "shared-model"}, clear=False):
                self.assertEqual(
                    keysuri_gemini_client.resolve_keysuri_body_model(program_id="keysuri_korea_tech"),
                    "shared-model",
                )

    def test_unrelated_program_id_does_not_trigger_global_or_korea_routing(self) -> None:
        with self._clear_model_env():
            with mock.patch.dict(
                os.environ,
                {
                    "KEYSURI_GLOBAL_TECH_BODY_GEMINI_MODEL": "should-not-be-used",
                    "KEYSURI_KOREA_TECH_BODY_GEMINI_MODEL": "should-not-be-used",
                    "KEYSURI_BODY_GEMINI_MODEL": "shared-model",
                },
                clear=False,
            ):
                self.assertEqual(
                    keysuri_gemini_client.resolve_keysuri_body_model(program_id="today_genie"),
                    "shared-model",
                )


class KeysuriGeminiNoPartsSafeFailTests(unittest.TestCase):
    """finish_reason=MAX_TOKENS / no-parts responses must raise KeysuriGeminiError
    with a clear issue code — never a raw SDK ValueError."""

    class _FakeFinishReason:
        def __init__(self, name: str) -> None:
            self.name = name

    class _FakeContent:
        def __init__(self, parts) -> None:
            self.parts = parts

    class _FakeCandidate:
        def __init__(self, *, finish_reason: str, parts) -> None:
            self.finish_reason = KeysuriGeminiNoPartsSafeFailTests._FakeFinishReason(finish_reason)
            self.content = KeysuriGeminiNoPartsSafeFailTests._FakeContent(parts)

    class _FakeResponse:
        def __init__(self, *, candidates) -> None:
            self.candidates = candidates

        @property
        def text(self):
            raise ValueError("Cannot get the response text.")

    def test_max_tokens_with_no_parts_raises_keysuri_gemini_error_with_issue_code(self) -> None:
        candidate = self._FakeCandidate(finish_reason="MAX_TOKENS", parts=[])
        response = self._FakeResponse(candidates=[candidate])
        with self.assertRaises(keysuri_gemini_client.KeysuriGeminiError) as ctx:
            keysuri_gemini_client._extract_gemini_text_safe(response)
        self.assertIn("keysuri_gemini_max_tokens_no_text", str(ctx.exception))

    def test_no_parts_without_max_tokens_raises_generic_no_parts_issue_code(self) -> None:
        candidate = self._FakeCandidate(finish_reason="SAFETY", parts=[])
        response = self._FakeResponse(candidates=[candidate])
        with self.assertRaises(keysuri_gemini_client.KeysuriGeminiError) as ctx:
            keysuri_gemini_client._extract_gemini_text_safe(response)
        self.assertIn("keysuri_gemini_response_no_parts", str(ctx.exception))

    def test_no_candidates_at_all_raises_no_parts_issue_code(self) -> None:
        response = self._FakeResponse(candidates=[])
        with self.assertRaises(keysuri_gemini_client.KeysuriGeminiError) as ctx:
            keysuri_gemini_client._extract_gemini_text_safe(response)
        self.assertIn("keysuri_gemini_response_no_parts", str(ctx.exception))

    def test_text_property_raising_value_error_is_wrapped_not_propagated(self) -> None:
        """Reproduces the production incident: candidate.content.parts truthy but
        response.text itself raises ValueError inside the SDK property getter."""

        class _NonEmptyPartsButBrokenTextResponse:
            def __init__(self) -> None:
                self.candidates = [
                    KeysuriGeminiNoPartsSafeFailTests._FakeCandidate(
                        finish_reason="MAX_TOKENS", parts=["part"]
                    )
                ]

            @property
            def text(self):
                raise ValueError("Cannot get the response text.")

        with self.assertRaises(keysuri_gemini_client.KeysuriGeminiError) as ctx:
            keysuri_gemini_client._extract_gemini_text_safe(_NonEmptyPartsButBrokenTextResponse())
        self.assertIn("keysuri_gemini_max_tokens_no_text", str(ctx.exception))
        self.assertNotIsInstance(ctx.exception, ValueError)

    def test_healthy_response_with_text_returns_text_normally(self) -> None:
        class _HealthyResponse:
            def __init__(self) -> None:
                self.candidates = [
                    KeysuriGeminiNoPartsSafeFailTests._FakeCandidate(
                        finish_reason="STOP", parts=["part"]
                    )
                ]
                self.text = '{"ok": true}'

        result = keysuri_gemini_client._extract_gemini_text_safe(_HealthyResponse())
        self.assertEqual(result, '{"ok": true}')

    @mock.patch("keysuri_gemini_client.vertexai.init")
    @mock.patch("keysuri_gemini_client.GenerativeModel")
    def test_call_keysuri_gemini_text_converts_max_tokens_response_to_keysuri_error(
        self, mock_model_cls: mock.MagicMock, _mock_init: mock.MagicMock
    ) -> None:
        """End-to-end: call_keysuri_gemini_text must never let the raw SDK
        ValueError escape — this is the exact production failure path."""

        class _MaxTokensResponse:
            def __init__(self) -> None:
                self.candidates = [
                    KeysuriGeminiNoPartsSafeFailTests._FakeCandidate(
                        finish_reason="MAX_TOKENS", parts=[]
                    )
                ]

            @property
            def text(self):
                raise ValueError("Cannot get the response text.")

        mock_instance = mock.MagicMock()
        mock_instance.generate_content.return_value = _MaxTokensResponse()
        mock_model_cls.return_value = mock_instance

        with mock.patch.dict(os.environ, {"PROJECT_ID": "test-project"}, clear=False):
            with self.assertRaises(keysuri_gemini_client.KeysuriGeminiError) as ctx:
                keysuri_gemini_client.call_keysuri_gemini_text(
                    "prompt", program_id="keysuri_korea_tech"
                )
        self.assertIn("keysuri_gemini_max_tokens_no_text", str(ctx.exception))


class KeysuriGeminiUsageSinkTests(unittest.TestCase):
    """usage_sink (optional) must be populated with token usage for cost
    estimation, and must never affect text generation if populating fails."""

    class _FakeUsage:
        def __init__(self, **kwargs) -> None:
            for key, value in kwargs.items():
                setattr(self, key, value)

    class _HealthyResponseWithUsage:
        def __init__(self, *, usage) -> None:
            self.candidates = [
                KeysuriGeminiNoPartsSafeFailTests._FakeCandidate(
                    finish_reason="STOP", parts=["part"]
                )
            ]
            self.text = '{"ok": true}'
            self.usage_metadata = usage

    def test_extract_gemini_usage_metadata_reads_all_fields(self) -> None:
        usage = self._FakeUsage(
            prompt_token_count=12003,
            candidates_token_count=478,
            thoughts_token_count=11792,
            total_token_count=24273,
        )
        response = self._HealthyResponseWithUsage(usage=usage)
        result = keysuri_gemini_client.extract_gemini_usage_metadata(response)
        self.assertEqual(result["prompt_token_count"], 12003)
        self.assertEqual(result["candidates_token_count"], 478)
        self.assertEqual(result["thoughts_token_count"], 11792)
        self.assertEqual(result["total_token_count"], 24273)

    def test_extract_gemini_usage_metadata_missing_usage_returns_all_none(self) -> None:
        class _NoUsageResponse:
            pass

        result = keysuri_gemini_client.extract_gemini_usage_metadata(_NoUsageResponse())
        self.assertIsNone(result["prompt_token_count"])
        self.assertIsNone(result["thoughts_token_count"])

    @mock.patch("keysuri_gemini_client.vertexai.init")
    @mock.patch("keysuri_gemini_client.GenerativeModel")
    def test_call_keysuri_gemini_text_populates_usage_sink(
        self, mock_model_cls: mock.MagicMock, _mock_init: mock.MagicMock
    ) -> None:
        usage = self._FakeUsage(
            prompt_token_count=1000, candidates_token_count=200,
            thoughts_token_count=50, total_token_count=1250,
        )
        response = self._HealthyResponseWithUsage(usage=usage)
        mock_instance = mock.MagicMock()
        mock_instance.generate_content.return_value = response
        mock_model_cls.return_value = mock_instance

        sink: dict = {}
        with mock.patch.dict(os.environ, {"PROJECT_ID": "test-project"}, clear=False):
            text = keysuri_gemini_client.call_keysuri_gemini_text(
                "prompt", model="gemini-2.5-flash", usage_sink=sink
            )
        self.assertEqual(text, '{"ok": true}')
        self.assertEqual(sink.get("model"), "gemini-2.5-flash")
        self.assertEqual(sink.get("prompt_token_count"), 1000)
        self.assertEqual(sink.get("thoughts_token_count"), 50)

    @mock.patch("keysuri_gemini_client.vertexai.init")
    @mock.patch("keysuri_gemini_client.GenerativeModel")
    def test_usage_sink_none_is_safe_default(
        self, mock_model_cls: mock.MagicMock, _mock_init: mock.MagicMock
    ) -> None:
        usage = self._FakeUsage(prompt_token_count=1, candidates_token_count=1)
        response = self._HealthyResponseWithUsage(usage=usage)
        mock_instance = mock.MagicMock()
        mock_instance.generate_content.return_value = response
        mock_model_cls.return_value = mock_instance

        with mock.patch.dict(os.environ, {"PROJECT_ID": "test-project"}, clear=False):
            text = keysuri_gemini_client.call_keysuri_gemini_text("prompt")
        self.assertEqual(text, '{"ok": true}')

    @mock.patch("keysuri_gemini_client.vertexai.init")
    @mock.patch("keysuri_gemini_client.GenerativeModel")
    def test_usage_sink_populate_failure_does_not_break_generation(
        self, mock_model_cls: mock.MagicMock, _mock_init: mock.MagicMock
    ) -> None:
        """A usage_sink that raises on assignment (e.g. a broken mapping) must
        not prevent the text result from being returned."""

        class _BrokenSink(dict):
            def __setitem__(self, key, value):
                raise RuntimeError("sink is broken")

        usage = self._FakeUsage(prompt_token_count=1, candidates_token_count=1)
        response = self._HealthyResponseWithUsage(usage=usage)
        mock_instance = mock.MagicMock()
        mock_instance.generate_content.return_value = response
        mock_model_cls.return_value = mock_instance

        with mock.patch.dict(os.environ, {"PROJECT_ID": "test-project"}, clear=False):
            text = keysuri_gemini_client.call_keysuri_gemini_text(
                "prompt", usage_sink=_BrokenSink()
            )
        self.assertEqual(text, '{"ok": true}')


if __name__ == "__main__":
    unittest.main()
