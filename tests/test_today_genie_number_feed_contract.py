"""Unit tests: today_genie number table contract + accuracy validation (no-send)."""
from __future__ import annotations

import unittest

from validators import _today_number_table_contract_accuracy_issues


def _six_rows_source_missing() -> list[dict]:
    """A: full contract keys, aligned value strings, no external verification."""
    specs = [
        ("코스피", "KOSPI", 2587.12, -0.59, "2587.12 (-0.59%)"),
        ("코스닥", "KOSDAQ", 736.88, 0.56, "736.88 (+0.56%)"),
        ("S&P 500", "SPX", 6816.89, -0.1, "6816.89 (-0.1%)"),
        ("나스닥", "NASDAQ", 22902.89, 0.4, "22902.89 (+0.4%)"),
        ("니케이", "NIKKEI", 34721.5, -0.32, "34721.5 (-0.32%)"),
        ("다우존스", "DJI", 47916.57, -0.6, "47916.57 (-0.6%)"),
    ]
    out: list[dict] = []
    for label, sym, close, pct, value in specs:
        out.append(
            {
                "label": label,
                "value": value,
                "basis": "fact",
                "symbol": sym,
                "display_name": label,
                "close": close,
                "change_pct": pct,
                "as_of": "2026-04-10",
                "source_name": "",
                "source_url": "",
                "source_id": "",
                "fetched_at": "",
                "verified_at": "",
                "accuracy_status": "source_missing",
            }
        )
    return out


def _six_rows_verified() -> list[dict]:
    """B: externally verified metadata on every row."""
    rows = _six_rows_source_missing()
    for r in rows:
        r["accuracy_status"] = "verified"
        r["source_name"] = "fixture_exchange"
        r["source_url"] = "https://example.invalid/indices"
        r["source_id"] = ""
        r["fetched_at"] = "2026-04-10T00:00:00Z"
        r["verified_at"] = "2026-04-10T00:01:00Z"
    return rows


class TodayGenieNumberFeedContractTests(unittest.TestCase):
    def test_a_no_source_metadata_is_accuracy_not_verified(self) -> None:
        data = {"market_snapshot": _six_rows_source_missing()}
        ri: dict = {}
        issues = _today_number_table_contract_accuracy_issues(data, ri)
        codes = [i.code for i in issues]
        self.assertIn("number_table_accuracy_not_verified", codes)
        self.assertNotIn("number_table_contract_malformed", codes)
        self.assertNotIn("number_table_accuracy_fail", codes)

    def test_b_verified_metadata_passes_accuracy_gate(self) -> None:
        data = {"market_snapshot": _six_rows_verified()}
        ri: dict = {}
        issues = _today_number_table_contract_accuracy_issues(data, ri)
        codes = [i.code for i in issues]
        self.assertNotIn("number_table_accuracy_not_verified", codes)
        self.assertNotIn("number_table_contract_malformed", codes)
        self.assertNotIn("number_table_accuracy_fail", codes)

    def test_c_malformed_row_structure_fail(self) -> None:
        rows = _six_rows_source_missing()
        del rows[2]["close"]
        data = {"market_snapshot": rows}
        issues = _today_number_table_contract_accuracy_issues(data, runtime_input={})
        codes = [i.code for i in issues]
        self.assertIn("number_table_contract_malformed", codes)

    def test_d_value_close_mismatch_accuracy_fail(self) -> None:
        rows = _six_rows_source_missing()
        rows[0]["value"] = "99999.99 (-0.59%)"
        data = {"market_snapshot": rows}
        issues = _today_number_table_contract_accuracy_issues(data, runtime_input={})
        codes = [i.code for i in issues]
        self.assertIn("number_table_accuracy_fail", codes)


if __name__ == "__main__":
    unittest.main()
