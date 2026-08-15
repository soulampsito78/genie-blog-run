"""대한민국 공휴일 비발행 가드.

2026-08-17(월)은 광복절(2026-08-15 토) 대체공휴일이다. Scheduler cron은 평일
기준이므로 이 날에도 발화하지만, 애플리케이션이 비용 발생 전에 결정적으로
SKIPPED_HOLIDAY 를 반환해야 한다.

이 스킵은 콘텐츠 실패도 인프라 실패도 편집 HOLD 도 아니며 의도된 스케줄 상태다.
"""
from __future__ import annotations

import os
import unittest
from datetime import date, datetime
from typing import Any, Dict
from unittest import mock
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from genie_schedule_policy import (
    HOLIDAY_SKIP_REASON,
    KST,
    SKIPPED_HOLIDAY_STATUS,
    holiday_calendar_covers,
    is_korean_public_holiday,
    is_korean_publishing_day,
    korean_public_holiday_name,
    scheduled_holiday_skip_payload,
)
from korea_public_holidays import COVERAGE_END_YEAR, KOREA_PUBLIC_HOLIDAYS
from main import app

_TOKEN = "unit-test-internal-token"
_PREFLIGHT = "/internal/jobs/natural-run-preflight"
_TODAY_NATURAL = "/internal/jobs/create-owner-review"
_KEYSURI_NATURAL = "/internal/jobs/create-keysuri-owner-review"
_WATCHDOG = "/internal/jobs/natural-run-watchdog"

# 2026-08-17 KST 각 슬롯 시각.
HOLIDAY = date(2026, 8, 17)
NORMAL_WEEKDAY = date(2026, 8, 18)


def _frozen_kst(moment: datetime):
    """Inject the clock only — never patch the datetime class itself."""
    return mock.patch.multiple(
        "genie_schedule_policy",
        get_kst_now=lambda now=None: moment if now is None else now,
    ), mock.patch("internal_jobs.get_kst_now", lambda now=None: moment if now is None else now)


class _Clock:
    def __init__(self, moment: datetime) -> None:
        self._patches = list(_frozen_kst(moment))

    def __enter__(self):
        for p in self._patches:
            p.start()
        return self

    def __exit__(self, *exc):
        for p in reversed(self._patches):
            p.stop()
        return False


def _auth() -> Dict[str, str]:
    return {"X-Genie-Internal-Job-Token": _TOKEN}


def _at(day: date, hh: int, mm: int) -> datetime:
    return datetime(day.year, day.month, day.day, hh, mm, tzinfo=KST)


class KoreanHolidayAuthorityTests(unittest.TestCase):
    """단일 판정 권위 자체의 정확성."""

    def test_20260817_is_substitute_holiday(self) -> None:
        self.assertTrue(is_korean_public_holiday(HOLIDAY))
        self.assertEqual(korean_public_holiday_name(HOLIDAY), "광복절 대체 휴일")
        self.assertFalse(is_korean_publishing_day(HOLIDAY))

    def test_liberation_day_itself_is_a_holiday(self) -> None:
        self.assertEqual(korean_public_holiday_name(date(2026, 8, 15)), "광복절")

    def test_normal_weekday_is_publishing_day(self) -> None:
        self.assertTrue(is_korean_publishing_day(NORMAL_WEEKDAY))
        self.assertIsNone(korean_public_holiday_name(NORMAL_WEEKDAY))

    def test_weekend_is_non_publishing_but_not_a_holiday(self) -> None:
        saturday, sunday = date(2026, 8, 22), date(2026, 8, 23)
        for day in (saturday, sunday):
            with self.subTest(day=day):
                self.assertFalse(is_korean_publishing_day(day))
                self.assertFalse(is_korean_public_holiday(day))

    def test_other_statutory_holidays(self) -> None:
        for day, name in (
            (date(2026, 1, 1), "신정연휴"),
            (date(2026, 2, 17), "설날"),
            (date(2026, 5, 5), "어린이날"),
            (date(2026, 9, 25), "추석"),
            (date(2026, 12, 25), "기독탄신일"),
        ):
            with self.subTest(day=day):
                self.assertEqual(korean_public_holiday_name(day), name)
                self.assertFalse(is_korean_publishing_day(day))

    def test_other_substitute_holidays(self) -> None:
        """음력·주말 겹침에서 파생된 대체공휴일도 인식한다."""
        for day, name in (
            (date(2026, 3, 2), "삼일절 대체 휴일"),
            (date(2026, 5, 25), "부처님오신날 대체 휴일"),
            (date(2026, 10, 5), "개천절 대체 휴일"),
            (date(2027, 8, 16), "광복절 대체 휴일"),
            (date(2025, 3, 3), "삼일절 대체 휴일"),
        ):
            with self.subTest(day=day):
                self.assertEqual(korean_public_holiday_name(day), name)
                self.assertFalse(is_korean_publishing_day(day))

    def test_accepts_date_datetime_and_iso_string(self) -> None:
        for value in (HOLIDAY, _at(HOLIDAY, 18, 30), "2026-08-17"):
            with self.subTest(value=value):
                self.assertTrue(is_korean_public_holiday(value))

    def test_calendar_coverage_tripwire(self) -> None:
        """표가 만료되기 전에 실패해서 갱신을 강제한다."""
        next_year = datetime.now(KST).year + 1
        self.assertGreaterEqual(
            COVERAGE_END_YEAR,
            next_year,
            "한국 공휴일 표를 갱신해야 합니다 (korea_public_holidays.py).",
        )
        self.assertTrue(holiday_calendar_covers(HOLIDAY))

    def test_outside_coverage_does_not_halt_publishing(self) -> None:
        far = date(COVERAGE_END_YEAR + 5, 3, 4)  # 수요일이 아니어도 무방
        self.assertFalse(holiday_calendar_covers(far))
        self.assertFalse(is_korean_public_holiday(far))


class HolidaySkipPayloadTests(unittest.TestCase):
    def test_scheduled_trigger_is_gated(self) -> None:
        for trigger in (
            "scheduled_service_full_run",
            "scheduled_owner_review",
            "scheduled_preflight_canary",
            "cloud_scheduler",
            "internal_job",
        ):
            with self.subTest(trigger=trigger):
                payload = scheduled_holiday_skip_payload(
                    program_id="keysuri_korea_tech",
                    trigger_source=trigger,
                    now=_at(HOLIDAY, 18, 30),
                )
                self.assertIsNotNone(payload)
                assert payload is not None
                self.assertTrue(payload["ok"])
                self.assertTrue(payload["skipped"])
                self.assertEqual(payload["skipped_reason"], HOLIDAY_SKIP_REASON)
                self.assertEqual(payload["operational_status"], SKIPPED_HOLIDAY_STATUS)
                self.assertFalse(payload["publishing_day"])
                self.assertEqual(payload["target_date_kst"], "2026-08-17")
                self.assertEqual(payload["holiday_name"], "광복절 대체 휴일")
                self.assertFalse(payload["called_gemini"])
                self.assertFalse(payload["called_image_api"])
                self.assertFalse(payload["email_sent"])
                self.assertEqual(payload["customer_send"], 0)

    def test_manual_and_reissue_triggers_are_untouched(self) -> None:
        for trigger in (
            "manual_service_full_run",
            "manual",
            "admin_text_only_reissue",
            "admin_image_only_reissue",
            "admin_text_and_image_reissue",
            "",
            None,
        ):
            with self.subTest(trigger=trigger):
                self.assertIsNone(
                    scheduled_holiday_skip_payload(
                        program_id="keysuri_korea_tech",
                        trigger_source=trigger,
                        now=_at(HOLIDAY, 18, 30),
                    )
                )

    def test_no_skip_on_normal_weekday(self) -> None:
        self.assertIsNone(
            scheduled_holiday_skip_payload(
                program_id="keysuri_korea_tech",
                trigger_source="scheduled_service_full_run",
                now=_at(NORMAL_WEEKDAY, 18, 30),
            )
        )


@mock.patch.dict(os.environ, {"GENIE_INTERNAL_JOB_TOKEN": _TOKEN}, clear=False)
class HolidayEndpointMatrixTests(unittest.TestCase):
    """2026-08-17 여섯 개 예약 진입점 전부 SKIPPED_HOLIDAY."""

    def setUp(self) -> None:
        self.client = TestClient(app)

    def _assert_skipped(self, payload: Dict[str, Any]) -> None:
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["skipped"])
        self.assertEqual(payload["skipped_reason"], HOLIDAY_SKIP_REASON)
        self.assertEqual(payload["operational_status"], SKIPPED_HOLIDAY_STATUS)
        self.assertFalse(payload["publishing_day"])
        self.assertEqual(payload["target_date_kst"], "2026-08-17")
        self.assertFalse(payload["email_sent"])
        self.assertFalse(payload["called_gemini"])
        self.assertFalse(payload["called_image_api"])

    def _preflight(self, program_id: str, slot: str, hh: int, mm: int):
        with _Clock(_at(HOLIDAY, hh, mm)), mock.patch(
            "natural_run_reliability.run_natural_preflight"
        ) as ran:
            response = self.client.post(
                _PREFLIGHT,
                json={
                    "program_id": program_id,
                    "scheduled_slot": slot,
                    "execution_class": "preflight_canary",
                    "alert_on_fail": True,
                },
                headers=_auth(),
            )
        return response, ran

    def test_today_preflight_skipped(self) -> None:
        response, ran = self._preflight("today_genie", "06:30", 5, 45)
        self.assertEqual(response.status_code, 200)
        self._assert_skipped(response.json())
        ran.assert_not_called()

    def test_global_preflight_skipped(self) -> None:
        response, ran = self._preflight("keysuri_global_tech", "12:30", 11, 45)
        self.assertEqual(response.status_code, 200)
        self._assert_skipped(response.json())
        ran.assert_not_called()

    def test_korea_preflight_skipped(self) -> None:
        response, ran = self._preflight("keysuri_korea_tech", "18:30", 17, 45)
        self.assertEqual(response.status_code, 200)
        self._assert_skipped(response.json())
        ran.assert_not_called()

    def test_today_natural_skipped(self) -> None:
        with _Clock(_at(HOLIDAY, 6, 30)), mock.patch(
            "internal_jobs.list_run_artifacts"
        ) as artifacts, mock.patch(
            "internal_jobs.execute_orchestrator_run"
        ) as orchestrate:
            response = self.client.post(
                _TODAY_NATURAL,
                json={
                    "execution_class": "natural_scheduled",
                    "scheduled_slot": "06:30",
                    "trigger_source": "scheduled_owner_review",
                },
                headers=_auth(),
            )
        self.assertEqual(response.status_code, 200)
        self._assert_skipped(response.json())
        artifacts.assert_not_called()
        orchestrate.assert_not_called()

    def _keysuri_natural(self, program_id: str, hh: int, mm: int):
        with _Clock(_at(HOLIDAY, hh, mm)), mock.patch(
            "internal_jobs.create_keysuri_owner_review_job"
        ) as job:
            response = self.client.post(
                _KEYSURI_NATURAL,
                json={
                    "program_id": program_id,
                    "service_full_run": True,
                    "send_owner_email": True,
                    "dry_run": False,
                    "trigger_source": "scheduled_service_full_run",
                },
                headers=_auth(),
            )
        return response, job

    def test_global_natural_skipped(self) -> None:
        response, job = self._keysuri_natural("keysuri_global_tech", 12, 30)
        self.assertEqual(response.status_code, 200)
        self._assert_skipped(response.json())
        job.assert_not_called()

    def test_korea_natural_skipped(self) -> None:
        response, job = self._keysuri_natural("keysuri_korea_tech", 18, 30)
        self.assertEqual(response.status_code, 200)
        self._assert_skipped(response.json())
        job.assert_not_called()

    def test_skip_is_not_an_http_failure(self) -> None:
        """스킵은 500 이 아니며 실패 실행으로 해석되지 않는다."""
        response, _ = self._keysuri_natural("keysuri_korea_tech", 18, 30)
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertNotIn("error", body)
        self.assertNotEqual(body.get("validation_result"), "block")
        self.assertIsNot(body.get("ok"), False)


@mock.patch.dict(os.environ, {"GENIE_INTERNAL_JOB_TOKEN": _TOKEN}, clear=False)
class HolidayWatchdogTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)

    def test_watchdog_opens_no_incident_on_holiday(self) -> None:
        with _Clock(_at(HOLIDAY, 18, 45)), mock.patch(
            "internal_jobs.list_run_artifacts"
        ) as artifacts, mock.patch(
            "natural_run_watchdog.run_watchdog_poll"
        ) as poll, mock.patch(
            "natural_run_watchdog.report_incident_once"
        ) as report:
            response = self.client.post(_WATCHDOG, json={}, headers=_auth())
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertFalse(body["expected_run"])
        self.assertFalse(body["publishing_day"])
        self.assertEqual(body["reason"], HOLIDAY_SKIP_REASON)
        self.assertEqual(body["holiday_name"], "광복절 대체 휴일")
        self.assertEqual(body["results"], [])
        # 비용/부작용 0
        artifacts.assert_not_called()
        poll.assert_not_called()
        report.assert_not_called()

    def test_watchdog_still_reconciles_on_normal_weekday(self) -> None:
        with _Clock(_at(NORMAL_WEEKDAY, 18, 45)), mock.patch(
            "natural_run_watchdog.watchdog_programs_due_for_reconciliation"
        ) as due:
            due.return_value = []
            response = self.client.post(_WATCHDOG, json={}, headers=_auth())
        self.assertEqual(response.status_code, 200)
        self.assertNotEqual(response.json().get("reason"), HOLIDAY_SKIP_REASON)
        due.assert_called_once()


class HolidayAdminProjectionTests(unittest.TestCase):
    def test_preflight_projection_labels_holiday_instead_of_stale(self) -> None:
        from admin_view_models import PROGRAM_BY_ID, preflight_projection

        projection = preflight_projection(
            None,
            PROGRAM_BY_ID["keysuri_korea_tech"],
            now=_at(HOLIDAY, 18, 45),
        )
        self.assertEqual(projection["state"], "skipped_holiday")
        self.assertEqual(projection["label"], "공휴일 비발행")
        self.assertEqual(projection["provenance"], SKIPPED_HOLIDAY_STATUS)

    def test_normal_weekday_projection_unchanged(self) -> None:
        from admin_view_models import PROGRAM_BY_ID, preflight_projection

        projection = preflight_projection(
            None,
            PROGRAM_BY_ID["keysuri_korea_tech"],
            now=_at(NORMAL_WEEKDAY, 18, 45),
        )
        self.assertEqual(projection["state"], "stale")
        self.assertEqual(projection["provenance"], "STALE")


class HolidayTableIntegrityTests(unittest.TestCase):
    def test_table_entries_are_valid_iso_dates(self) -> None:
        for key in KOREA_PUBLIC_HOLIDAYS:
            date.fromisoformat(key)

    def test_table_has_no_weekend_only_substitutes_missing(self) -> None:
        """광복절이 주말이면 대체공휴일이 반드시 존재한다."""
        for year in (2026, 2027):
            liberation = date(year, 8, 15)
            if liberation.weekday() >= 5:
                names = [
                    name
                    for key, name in KOREA_PUBLIC_HOLIDAYS.items()
                    if key.startswith(f"{year}-08-") and "광복절 대체" in name
                ]
                self.assertTrue(names, f"{year} 광복절 대체공휴일 누락")


if __name__ == "__main__":
    unittest.main()
