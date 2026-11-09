from keysuri_service_full_run import _filter_global_stale_reissue_claims


def test_old_news_reissue_filters_old_unknown_and_future_but_retains_week():
    pack = {
        "sources": [
            {"source_id": "old", "published_at": "2026-10-23T00:00:02+09:00"},
            {"source_id": "recent", "published_at": "2026-11-06T05:00:00+09:00"},
            {"source_id": "future", "published_at": "2026-11-10T00:00:00+09:00"},
            {"source_id": "undated"},
        ],
        "claims": [{"source_ids": [name]} for name in ("old", "recent", "future", "undated")],
    }
    filtered, rejected = _filter_global_stale_reissue_claims(pack, as_of="2026-11-09T13:30:00+09:00")
    assert rejected == 3
    assert filtered["claims"] == [{"source_ids": ["recent"]}]
    assert len(pack["claims"]) == 4


def test_exact_seven_day_boundary_and_backfill_sources():
    pack = {
        "sources": [],
        "backfill_sources": [{"source_id": "edge", "published_at": "2026-11-02T13:30:00+09:00"}],
        "backfill_claims": [{"source_ids": ["edge"]}],
    }
    filtered, rejected = _filter_global_stale_reissue_claims(pack, as_of="2026-11-09T13:30:00+09:00")
    assert rejected == 0
    assert filtered["backfill_claims"] == pack["backfill_claims"]
