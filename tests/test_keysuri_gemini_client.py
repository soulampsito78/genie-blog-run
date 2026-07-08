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


if __name__ == "__main__":
    unittest.main()
