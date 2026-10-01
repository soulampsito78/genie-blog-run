from datetime import datetime, timezone
import pytest
from ops.work_review_watchdog import WatchdogError, inspect_slots


def _policy(**kw):
    cal = {"valid_from": "2026-10-01", "valid_through": "2026-10-31", "excluded_dates": []}
    cal.update(kw.pop("calendar", {}))
    p = {"timezone": "Asia/Seoul", "calendar": cal, "products": ["keysuri_korea_tech"]}
    p.update(kw)
    return {"recurring_policy": p}


def test_canonical_three_product_mapping(tmp_path):
    m = _policy(products=["today_genie", "keysuri_global_tech", "keysuri_korea_tech"])
    r = inspect_slots(manifest=m, evidence_dir=tmp_path, now=datetime(2026, 9, 30, 21, 20, tzinfo=timezone.utc))
    assert r["pending_slots"] == ["2026-10-01_today_genie", "2026-10-01_keysuri_global_tech", "2026-10-01_keysuri_korea_tech"]


def test_rollover_and_deadline_missing(tmp_path):
    m = _policy(products=["today_genie"])
    r1 = inspect_slots(manifest=m, evidence_dir=tmp_path, now=datetime(2026, 9, 30, 21, 20, tzinfo=timezone.utc))
    assert r1["pending_slots"] == ["2026-10-01_today_genie"]
    r2 = inspect_slots(manifest=m, evidence_dir=tmp_path, now=datetime(2026, 9, 30, 22, 0, tzinfo=timezone.utc))
    assert r2["exceptions"][0]["problem_code"] == "MISSING_REVIEW_EVIDENCE_AFTER_DEADLINE"


def test_weekend_holiday_calendar_expired(tmp_path):
    r_wk = inspect_slots(manifest=_policy(), evidence_dir=tmp_path, now=datetime(2026, 10, 3, 9, 0, tzinfo=timezone.utc))
    assert r_wk["pending_slots"] == [] and r_wk["exceptions"] == []
    m_hol = _policy(calendar={"valid_from": "2026-10-01", "valid_through": "2026-10-31", "excluded_dates": ["2026-10-09"]})
    r_hol = inspect_slots(manifest=m_hol, evidence_dir=tmp_path, now=datetime(2026, 10, 9, 9, 0, tzinfo=timezone.utc))
    assert r_hol["pending_slots"] == [] and r_hol["exceptions"] == []
    r_exp = inspect_slots(manifest=_policy(), evidence_dir=tmp_path, now=datetime(2026, 11, 1, 9, 0, tzinfo=timezone.utc))
    assert r_exp["exceptions"][0]["problem_code"] == "CALENDAR_COVERAGE_UNAVAILABLE"


def test_missing_excluded_dates_and_duplicates(tmp_path):
    m = {"recurring_policy": {"timezone": "Asia/Seoul", "calendar": {"valid_from": "2026-10-01", "valid_through": "2026-10-31"}, "products": ["today_genie"]}}
    with pytest.raises(WatchdogError):
        inspect_slots(manifest=m, evidence_dir=tmp_path, now=datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc))
    slot = {"slot_id": "s1", "product": "today_genie", "windows_kst": ["2026-10-01T06:33:00+09:00"]}
    with pytest.raises(WatchdogError):
        inspect_slots(manifest={"slots": [slot, slot]}, evidence_dir=tmp_path, now=datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc))


def test_stale_finite_and_empty_manifest(tmp_path):
    slot = {"slot_id": "s1", "product": "today_genie", "publication_date": "2026-09-11", "windows_kst": ["2026-09-11T06:48:00+09:00"]}
    r_stale = inspect_slots(manifest={"slots": [slot]}, evidence_dir=tmp_path, now=datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc))
    assert any(e["problem_code"] == "STALE_FINITE_MANIFEST" for e in r_stale["exceptions"])
    r_empty = inspect_slots(manifest={"slots": []}, evidence_dir=tmp_path, now=datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc))
    assert r_empty["exceptions"][0]["problem_code"] == "MANIFEST_COVERAGE_UNAVAILABLE"

def test_product_validation_and_all_disabled(tmp_path):
    with pytest.raises(WatchdogError):
        inspect_slots(manifest=_policy(products=[{"invalid": 1}]), evidence_dir=tmp_path, now=datetime(2026, 9, 30, 21, 20, tzinfo=timezone.utc))
    with pytest.raises(WatchdogError):
        inspect_slots(manifest=_policy(products=["unknown_product"]), evidence_dir=tmp_path, now=datetime(2026, 9, 30, 21, 20, tzinfo=timezone.utc))
    slot = {"slot_id": "s1", "product": "today_genie", "windows_kst": ["2026-10-01T06:33:00+09:00"], "watchdog_monitor": False}
    r = inspect_slots(manifest={"slots": [slot]}, evidence_dir=tmp_path, now=datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc))
    assert r["skipped_slots"] == ["s1"]
    assert r["exceptions"][0]["problem_code"] == "MANIFEST_COVERAGE_UNAVAILABLE"
