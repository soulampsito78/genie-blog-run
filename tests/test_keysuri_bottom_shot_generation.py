from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from keysuri_bottom_shot_generation import generate_keysuri_korea_bottom_v6


class KeysuriBottomShotGenerationTests(unittest.TestCase):
    def test_multi_ref_generation_contract_and_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            anchor = root / "anchor.jpg"
            secondary = root / "asset01.png"
            output = root / "bottom.jpg"
            anchor.write_bytes(b"anchor")
            secondary.write_bytes(b"secondary")

            def fake_generate(**kwargs):
                self.assertEqual(kwargs["primary_reference_path"], anchor)
                self.assertEqual(kwargs["secondary_reference_path"], secondary)
                kwargs["output_path"].write_bytes(b"generated")
                return kwargs["output_path"]

            def fake_watermark(source: Path, target: Path) -> Path:
                target.write_bytes(source.read_bytes() + b"-watermarked")
                return target

            result = generate_keysuri_korea_bottom_v6(
                repo_root=root,
                output_path=output,
                primary_reference_path=anchor,
                secondary_reference_path=secondary,
                weather_condition="clear",
                temperature_c=12.0,
                wardrobe_variant=1,
                pose_variant=2,
                apply_watermark=True,
                watermark_fn=fake_watermark,
                generate_fn=fake_generate,
            )

            self.assertTrue(result.ok)
            self.assertTrue(result.image_path and result.image_path.is_file())
            self.assertEqual(result.metadata["bottom_shot_source"], "generated_v6_multi_ref")
            self.assertTrue(result.metadata["bottom_shot_generated"])
            self.assertEqual(result.metadata["bottom_anchor_slot"], 0)
            self.assertEqual(result.metadata["secondary_reference_slot"], 1)
            self.assertEqual(result.metadata["bottom_shot_model"], "gemini-2.5-flash-image")
            self.assertEqual(result.metadata["bottom_shot_weather_key"], "clear_cool")
            self.assertEqual(result.metadata["bottom_shot_wardrobe_variant"], 1)
            self.assertTrue(result.metadata["bottom_shot_pose_variant"])

    def test_generation_error_returns_failed_result_without_api_retry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            anchor = root / "anchor.jpg"
            secondary = root / "asset01.png"
            anchor.write_bytes(b"anchor")
            secondary.write_bytes(b"secondary")
            generate = MagicMock(side_effect=RuntimeError("mock API failure"))

            result = generate_keysuri_korea_bottom_v6(
                repo_root=root,
                output_path=root / "bottom.jpg",
                primary_reference_path=anchor,
                secondary_reference_path=secondary,
                weather_condition="cloudy",
                generate_fn=generate,
            )

            self.assertFalse(result.ok)
            self.assertEqual(result.error_code, "bottom_v6_generation_failed")
            self.assertEqual(result.metadata["bottom_shot_generation_status"], "failed")
            self.assertEqual(generate.call_count, 1)


if __name__ == "__main__":
    unittest.main()
