"""Unit tests for programs.registry foundation."""
from __future__ import annotations

import unittest

from programs.registry import (
    UnknownProgramError,
    get_program,
    list_programs,
    resolve_program_id,
)


class ProgramRegistryTests(unittest.TestCase):
    def test_today_geenee_exists(self) -> None:
        spec = get_program("today_geenee")
        self.assertEqual(spec.program_id, "today_geenee")
        self.assertEqual(spec.legacy_mode, "today_genie")

    def test_today_genie_resolves_to_today_geenee(self) -> None:
        self.assertEqual(resolve_program_id("today_genie"), "today_geenee")

    def test_keysuri_global_tech_exists(self) -> None:
        spec = get_program("keysuri_global_tech")
        self.assertEqual(spec.program_id, "keysuri_global_tech")
        self.assertEqual(spec.schedule_kst, "12:30")

    def test_keysuri_korea_tech_exists(self) -> None:
        spec = get_program("keysuri_korea_tech")
        self.assertEqual(spec.program_id, "keysuri_korea_tech")
        self.assertEqual(spec.schedule_kst, "18:30")

    def test_today_geenee_output_contract(self) -> None:
        spec = get_program("today_geenee")
        self.assertEqual(spec.output_contract, "genie_html_email_body_v1")

    def test_today_geenee_delivery_flags(self) -> None:
        spec = get_program("today_geenee")
        self.assertTrue(spec.inline_html_body_enabled)
        self.assertFalse(spec.paste_body_enabled)
        self.assertFalse(spec.html_attachment_enabled)
        self.assertFalse(spec.image_attachment_enabled)
        self.assertFalse(spec.naver_assets_enabled)
        self.assertFalse(spec.in_app_enabled)

    def test_keysuri_programs_output_contract(self) -> None:
        for program_id in ("keysuri_global_tech", "keysuri_korea_tech"):
            with self.subTest(program_id=program_id):
                spec = get_program(program_id)
                self.assertEqual(spec.output_contract, "keysuri_private_briefing_v1")

    def test_keysuri_programs_visual_profile(self) -> None:
        for program_id in ("keysuri_global_tech", "keysuri_korea_tech"):
            with self.subTest(program_id=program_id):
                spec = get_program(program_id)
                self.assertEqual(spec.visual_profile, "keysuri_v1")
                self.assertTrue(spec.source_gate_enabled)
                self.assertTrue(spec.in_app_enabled)

    def test_unknown_program_raises(self) -> None:
        with self.assertRaises(UnknownProgramError) as ctx:
            get_program("not_a_program")
        self.assertIn("Unknown program_id", str(ctx.exception))
        self.assertIn("not_a_program", str(ctx.exception))

    def test_unknown_alias_raises(self) -> None:
        with self.assertRaises(UnknownProgramError) as ctx:
            resolve_program_id("tomorrow_genie")
        self.assertIn("Unknown program reference", str(ctx.exception))

    def test_list_programs_returns_all_three(self) -> None:
        programs = list_programs()
        self.assertEqual(len(programs), 3)
        self.assertEqual(
            [spec.program_id for spec in programs],
            ["today_geenee", "keysuri_global_tech", "keysuri_korea_tech"],
        )


if __name__ == "__main__":
    unittest.main()
