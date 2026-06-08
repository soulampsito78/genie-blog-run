"""Tests for scripts/render_keysuri_contract_preview.py (design fixture only)."""
from __future__ import annotations

import json
import re
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

_REPO = Path(__file__).resolve().parent.parent
_SCRIPT = _REPO / "scripts" / "render_keysuri_contract_preview.py"

_DESIGN_FILENAME_RE = re.compile(
    r"^keysuri_(korea|global)_\d{4}_design_fixture_\d{8}_\d{6}(?:_\d+)?\.html$",
    re.IGNORECASE,
)

_FORBIDDEN_BLEED = (
    "Today_Geenee",
    "Tomorrow_Geenee",
    "테크 앵커",
    "뉴스 앵커",
    "해시태그",
    "#키수리",
    "static/email/",
)

DESIGN_BANNER = "DESIGN FIXTURE — NOT OWNER REVIEW"


def _html_test_dir(tmp: Path) -> Path:
    return tmp / "output" / "keysuri_preview" / "html_test"


def _run_script(tmp: Path, *extra_args: str) -> subprocess.CompletedProcess[str]:
    out_dir = _html_test_dir(tmp)
    cmd = [
        sys.executable,
        str(_SCRIPT),
        "--output-dir",
        str(out_dir),
        *extra_args,
    ]
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


class KeysuriContractPreviewScriptTests(unittest.TestCase):
    def test_korea_writes_design_fixture_file(self) -> None:
        with TemporaryDirectory() as tmpdir:
            proc = _run_script(
                Path(tmpdir),
                "--program",
                "keysuri_korea_tech",
                "--slot",
                "18:30",
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stderr or proc.stdout)
            payload = json.loads(proc.stdout)
            self.assertTrue(payload["design_fixture"])
            self.assertFalse(payload["owner_visual_review"])
            self.assertFalse(payload["visible_body_quality_pass"])
            path = Path(payload["output_path"])
            self.assertTrue(path.exists())
            self.assertRegex(path.name, _DESIGN_FILENAME_RE)
            self.assertIn("korea_1830", path.name)
            html = path.read_text(encoding="utf-8")
            self.assertIn(DESIGN_BANNER, html)

    def test_global_writes_design_fixture_file(self) -> None:
        with TemporaryDirectory() as tmpdir:
            proc = _run_script(
                Path(tmpdir),
                "--program",
                "keysuri_global_tech",
                "--slot",
                "12:30",
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stderr or proc.stdout)
            payload = json.loads(proc.stdout)
            self.assertTrue(payload["design_fixture"])
            self.assertFalse(payload["owner_visual_review"])
            path = Path(payload["output_path"])
            self.assertTrue(path.exists())
            self.assertRegex(path.name, _DESIGN_FILENAME_RE)
            self.assertIn("global_1230", path.name)

    def test_default_args_produce_korea_1830_design_fixture(self) -> None:
        with TemporaryDirectory() as tmpdir:
            proc = _run_script(Path(tmpdir))
            self.assertEqual(proc.returncode, 0, msg=proc.stderr or proc.stdout)
            payload = json.loads(proc.stdout)
            self.assertEqual(payload["program"], "keysuri_korea_tech")
            self.assertEqual(payload["slot"], "18:30")
            self.assertEqual(payload["review_state"], "preview_pending")
            self.assertEqual(payload["owner_visual_review_status"], "NOT_READY — design fixture only")
            path = Path(payload["output_path"])
            self.assertIn("design_fixture", path.name)
            self.assertIn("국내 테크 TOP 5", path.read_text(encoding="utf-8"))

    def test_review_state_review_passed_text(self) -> None:
        with TemporaryDirectory() as tmpdir:
            proc = _run_script(
                Path(tmpdir),
                "--review-state",
                "review_passed",
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stderr or proc.stdout)
            html = Path(json.loads(proc.stdout)["output_path"]).read_text(encoding="utf-8")
            self.assertIn("본 브리핑은 운영책임자의 직접 검수를 통과했습니다.", html)
            self.assertNotIn("발송되었습니다", html)

    def test_review_state_sent_archived_text(self) -> None:
        with TemporaryDirectory() as tmpdir:
            proc = _run_script(
                Path(tmpdir),
                "--review-state",
                "sent_archived",
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stderr or proc.stdout)
            html = Path(json.loads(proc.stdout)["output_path"]).read_text(encoding="utf-8")
            self.assertIn("발송되었습니다", html)

    def test_output_filename_uses_design_fixture_pattern(self) -> None:
        with TemporaryDirectory() as tmpdir:
            proc = _run_script(
                Path(tmpdir),
                "--program",
                "keysuri_global_tech",
                "--slot",
                "12:30",
            )
            self.assertEqual(proc.returncode, 0)
            filename = Path(json.loads(proc.stdout)["output_path"]).name
            self.assertRegex(filename, _DESIGN_FILENAME_RE)

    def test_script_exits_zero_and_reports_not_owner_ready(self) -> None:
        with TemporaryDirectory() as tmpdir:
            proc = _run_script(Path(tmpdir), "--pretty")
            self.assertEqual(proc.returncode, 0)
            payload = json.loads(proc.stdout)
            self.assertIn("output_path", payload)
            self.assertFalse(payload["owner_visual_review"])
            self.assertTrue(payload["design_fixture_banner_present"])

    def test_generated_file_is_utf8_with_rights_policy(self) -> None:
        with TemporaryDirectory() as tmpdir:
            proc = _run_script(Path(tmpdir))
            self.assertEqual(proc.returncode, 0)
            path = Path(json.loads(proc.stdout)["output_path"])
            html = path.read_text(encoding="utf-8")
            self.assertIn("Copyright Ⓒ MirAI:ON. All rights reserved.", html)
            self.assertIn("무단 전재, 재배포 및 AI학습 이용 절대 금지", html)

    def test_no_forbidden_bleed_markers(self) -> None:
        with TemporaryDirectory() as tmpdir:
            for program, slot in (
                ("keysuri_korea_tech", "18:30"),
                ("keysuri_global_tech", "12:30"),
            ):
                proc = _run_script(Path(tmpdir), "--program", program, "--slot", slot)
                self.assertEqual(proc.returncode, 0, msg=proc.stderr or proc.stdout)
                html = Path(json.loads(proc.stdout)["output_path"]).read_text(encoding="utf-8")
                for marker in _FORBIDDEN_BLEED:
                    with self.subTest(program=program, marker=marker):
                        self.assertNotIn(marker, html)
                self.assertNotIn("production_ready: true", html)
                self.assertNotIn("scheduler_ready: true", html)
                self.assertNotIn("email_ready: true", html)

    def test_script_does_not_write_outside_output_dir(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            out_dir = _html_test_dir(root)
            proc = _run_script(root, "--program", "keysuri_korea_tech")
            self.assertEqual(proc.returncode, 0)
            written = Path(json.loads(proc.stdout)["output_path"]).resolve()
            self.assertTrue(str(written).startswith(str(out_dir.resolve())))
            for path in root.rglob("*.html"):
                self.assertTrue(str(path.resolve()).startswith(str(out_dir.resolve())))


if __name__ == "__main__":
    unittest.main()
