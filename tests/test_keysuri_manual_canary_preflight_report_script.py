"""Tests for Kee-Suri R5B-I manual canary preflight report script (offline)."""
from __future__ import annotations

import importlib.util
import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

_REPO = Path(__file__).resolve().parent.parent
_SCRIPT_PATH = _REPO / "scripts" / "build_keysuri_manual_canary_preflight_report.py"


def _load_script_module():
    spec = importlib.util.spec_from_file_location(
        "build_keysuri_manual_canary_preflight_report",
        _SCRIPT_PATH,
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class KeysuriManualCanaryPreflightReportScriptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.script = _load_script_module()

    def test_script_file_exists_and_imports_safely(self) -> None:
        self.assertTrue(_SCRIPT_PATH.is_file())
        self.assertTrue(hasattr(self.script, "main"))
        self.assertTrue(hasattr(self.script, "build_report_text"))

    def test_default_invocation_exit_code_zero(self) -> None:
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = self.script.main([])
        self.assertEqual(code, 0)

    def test_default_stdout_contains_expected_fields(self) -> None:
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.script.main([])
        out = buf.getvalue()
        self.assertIn("KEYSURI R5B-I Manual Canary Preflight Report", out)
        self.assertIn("status: BLOCK_LIVE_CALL", out)
        self.assertIn("target date: 2026-06-04", out)
        self.assertIn("program id: keysuri_global_tech", out)
        self.assertIn("profile_01_charcoal_ivory", out)
        self.assertIn("No image API was called.", out)
        self.assertIn(
            "This report does not authorize Scheduler, production wiring, automatic retry, or batch generation.",
            out,
        )

    def test_2026_06_05_invocation(self) -> None:
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = self.script.main(
                ["--wardrobe-date-kst", "2026-06-05", "--program-id", "keysuri_global_tech"]
            )
        out = buf.getvalue()
        self.assertEqual(code, 0)
        self.assertIn("profile_03_graphite_champagne", out)
        self.assertIn("new_visual_qa_required: true", out)

    def test_invalid_program_returns_non_zero(self) -> None:
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = self.script.main(["--program-id", "today_geenee"])
        out = buf.getvalue()
        self.assertNotEqual(code, 0)
        self.assertTrue("status: FAIL" in out or "forbidden_program_id" in out)

    def test_no_forbidden_imports_in_script_source(self) -> None:
        source = _SCRIPT_PATH.read_text(encoding="utf-8")
        forbidden_modules = (
            "keysuri_image_api_canary_client",
            "keysuri_image_api_gate",
            "keysuri_image_provider_contract",
            "vertex",
            "gemini",
            "google.cloud",
        )
        import_lines = [
            line.strip()
            for line in source.splitlines()
            if line.startswith("import ") or line.startswith("from ")
        ]
        for mod in forbidden_modules:
            with self.subTest(module=mod):
                self.assertFalse(
                    any(mod in line for line in import_lines),
                    msg=f"forbidden import of {mod!r} in report script",
                )

    def test_script_does_not_write_output_files(self) -> None:
        with patch("pathlib.Path.write_text") as write_text, patch(
            "pathlib.Path.mkdir"
        ) as mkdir:
            buf = io.StringIO()
            with redirect_stdout(buf):
                code = self.script.main([])
            self.assertEqual(code, 0)
            write_text.assert_not_called()
            mkdir.assert_not_called()

    def test_main_callable_without_terminal(self) -> None:
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = self.script.main(
                ["--wardrobe-date-kst", "2026-06-04", "--program-id", "keysuri_global_tech"]
            )
        self.assertEqual(code, 0)
        self.assertIn("status: BLOCK_LIVE_CALL", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
