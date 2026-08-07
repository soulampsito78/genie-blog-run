"""Permanent regression: Today forbidden surface cliche is scrubbed before hard gate."""

from __future__ import annotations

import unittest

from main import stabilize_today_genie_validation_fields
from validators import validate_today_genie


class TodaySurfaceClicheScrubTests(unittest.TestCase):
    def test_stabilize_scrubs_forbidden_surface_cliche_from_summary(self) -> None:
        data = {
            "summary": "미국 금리 경계를 보고 신중한 접근이 필요합니다",
            "market_setup": "코스피와 나스닥이 약세입니다.",
            "key_watchpoints": [{"title": "환율", "detail": "달러 강세 여부를 확인합니다."}],
            "risk_check": [
                {
                    "risk": "금리 급변",
                    "detail": "발표 직후 변동성 확대",
                    "basis": "fact",
                }
            ],
            "closing_message": "오늘은 CPI 이후 금리·환율 반응을 먼저 확인하겠습니다.",
            "hashtags": ["#금리", "#환율", "#수급"],
            "market_snapshot": [],
            "image_prompt": "morning desk chart soft light",
        }
        runtime = {"input_feed_status": "partial", "top3_items": []}
        fixed = stabilize_today_genie_validation_fields(data, runtime)
        self.assertNotIn("신중한 접근이 필요", fixed["summary"])
        self.assertIn("확인 순서로 보겠습니다", fixed["summary"])
        result = validate_today_genie(fixed, runtime_input=runtime)
        codes = {i.code for i in result.issues if i.severity == "error"}
        self.assertNotIn("forbidden_surface_cliche_phrase", codes)


if __name__ == "__main__":
    unittest.main()
