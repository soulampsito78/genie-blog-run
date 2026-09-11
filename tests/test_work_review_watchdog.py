import json
from datetime import datetime, timezone

from ops.work_review_watchdog import inspect_slots, run_watchdog


def _manifest(*, monitor=True):
    return {
        "slots": [{
            "slot_id": "2026-09-11_keysuri_korea_tech",
            "product": "keysuri_korea_tech",
            "publication_date": "2026-09-11",
            "windows_kst": [
                "2026-09-11T18:33:00+09:00",
                "2026-09-11T18:48:00+09:00",
            ],
            "watchdog_monitor": monitor,
        }]
    }


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _pass():
    return {
        "slot_id": "2026-09-11_keysuri_korea_tech",
        "run_id": "20260911_183000_keysuri_korea_tech_aabbccdd",
        "observed_at": "2026-09-11T18:34:00+09:00",
        "overall_verdict": "PASS",
        "checks": {name: "PASS" for name in {
            "content", "sources", "images", "render", "customer_render",
            "run_identity", "delivery_readiness",
        }},
        "approval_authority": "NONE",
        "customer_send_authorized": False,
    }


def test_before_deadline_is_pending(tmp_path):
    result = inspect_slots(manifest=_manifest(), evidence_dir=tmp_path,
        now=datetime(2026, 9, 11, 9, 40, tzinfo=timezone.utc))
    assert result["pending_slots"] == ["2026-09-11_keysuri_korea_tech"]
    assert result["exceptions"] == []


def _waiting_hold_incomplete():
    return {
        "slot_id": "2026-09-11_keysuri_korea_tech",
        "run_id": "20260911_183300_keysuri_korea_tech_waiting",
        "observed_at": "2026-09-11T09:38:00+09:00",
        "overall_verdict": "HOLD_INCOMPLETE",
        "reason_codes": ["NO_MATCHING_OWNER_REVIEW_MAIL"],
        "customer_send_state": "WAITING",
        "checks": {name: "PASS" for name in {
            "content", "sources", "images", "render", "customer_render",
            "run_identity", "delivery_readiness",
        }},
    }


def test_waiting_hold_incomplete_before_deadline_is_pending(tmp_path):
    _write(tmp_path / "review.json", _waiting_hold_incomplete())
    result = inspect_slots(manifest=_manifest(), evidence_dir=tmp_path,
        now=datetime(2026, 9, 11, 9, 40, tzinfo=timezone.utc))
    assert result["pending_slots"] == ["2026-09-11_keysuri_korea_tech"]
    assert result["exceptions"] == []


def test_waiting_hold_incomplete_after_deadline_becomes_review_unavailable(tmp_path):
    _write(tmp_path / "review.json", _waiting_hold_incomplete())
    result = inspect_slots(manifest=_manifest(), evidence_dir=tmp_path,
        now=datetime(2026, 9, 11, 10, 0, tzinfo=timezone.utc))
    assert result["exceptions"][0]["verdict"] == "REVIEW_UNAVAILABLE"
    assert result["exceptions"][0]["problem_code"] == "NO_MATCHING_OWNER_REVIEW_MAIL"


def test_final_verdict_overrides_waiting_observation(tmp_path):
    _write(tmp_path / "waiting.json", _waiting_hold_incomplete())
    final = _pass()
    final.update(run_id="20260911_183700_keysuri_korea_tech_final")
    final.update(overall_verdict="HOLD_ANOMALY", reason_codes=["CUSTOMER_RENDER_MISSING"],
                 observed_at="2026-09-11T09:38:00+09:00")
    _write(tmp_path / "final.json", final)
    result = inspect_slots(manifest=_manifest(), evidence_dir=tmp_path,
        now=datetime(2026, 9, 11, 9, 40, tzinfo=timezone.utc))
    assert result["exceptions"][0]["verdict"] == "HOLD_ANOMALY"
    assert result["exceptions"][0]["problem_code"] == "CUSTOMER_RENDER_MISSING"


def test_complete_shadow_pass_is_silent(tmp_path):
    _write(tmp_path / "review.json", _pass())
    result = inspect_slots(manifest=_manifest(), evidence_dir=tmp_path,
        now=datetime(2026, 9, 11, 10, 0, tzinfo=timezone.utc))
    assert result["complete_slots"] == ["2026-09-11_keysuri_korea_tech"]
    assert result["exceptions"] == []


def test_incomplete_pass_fails_closed(tmp_path):
    row = _pass()
    del row["checks"]["customer_render"]
    _write(tmp_path / "review.json", row)
    result = inspect_slots(manifest=_manifest(), evidence_dir=tmp_path,
        now=datetime(2026, 9, 11, 10, 0, tzinfo=timezone.utc))
    assert result["exceptions"][0]["verdict"] == "HOLD_INCOMPLETE"
    assert result["exceptions"][0]["problem_code"] == "MALFORMED_PASS_EVIDENCE"


def test_missing_review_after_deadline_notifies_once(tmp_path):
    manifest = tmp_path / "manifest.json"
    _write(manifest, _manifest())
    notified = []
    kwargs = dict(
        manifest_path=manifest,
        evidence_dir=tmp_path / "evidence",
        state_path=tmp_path / "state.json",
        report_dir=tmp_path / "reports",
        now=datetime(2026, 9, 11, 10, 0, tzinfo=timezone.utc),
        notifier=notified.append,
    )
    first = run_watchdog(**kwargs)
    second = run_watchdog(**kwargs)
    assert first["new_exception_count"] == 1
    assert second["new_exception_count"] == 0
    assert len(notified) == 1
    assert len(list((tmp_path / "reports").glob("*.json"))) == 1


def test_non_pass_evidence_is_reported(tmp_path):
    row = _pass()
    row.update(overall_verdict="HOLD_ANOMALY", reason_codes=["SOURCE_CONTRADICTION"])
    _write(tmp_path / "review.json", row)
    result = inspect_slots(manifest=_manifest(), evidence_dir=tmp_path,
        now=datetime(2026, 9, 11, 9, 35, tzinfo=timezone.utc))
    assert result["exceptions"][0]["problem_code"] == "SOURCE_CONTRADICTION"


def test_explicitly_unmonitored_missed_slot_is_preserved_without_alert(tmp_path):
    result = inspect_slots(manifest=_manifest(monitor=False), evidence_dir=tmp_path,
        now=datetime(2026, 9, 12, 0, 0, tzinfo=timezone.utc))
    assert result["skipped_slots"] == ["2026-09-11_keysuri_korea_tech"]
    assert result["exceptions"] == []
