from datetime import datetime
from zoneinfo import ZoneInfo
import pytest

from publication_review_policy import source_scope_manual_review_eligible, is_harmless_editorial_code
from customer_review_confirmation import today_delegated_warning_eligible
from delegated_gate import validate_automatic_qa_producer, GateError

NOW = datetime(2026, 11, 26, 6, 20, tzinfo=ZoneInfo("Asia/Seoul"))
CODE = "customer_surface_session_causality_unverified"


def meta():
    return dict(run_id="20261126_060542_today_genie_0748f23f", mode="today_genie", target_date="2026-11-26",
        response_status=200, validation_result="pass", runtime_safety_status="RUNTIME_SAFETY_PASS",
        customer_surface_status="PRODUCT_REVIEW_REQUIRED", issue_codes=[CODE], product_surface_issue_codes=[CODE])


def test_source_warning_enters_independent_review_and_never_automatic_pass():
    row = meta()
    assert source_scope_manual_review_eligible(row, now=NOW)
    assert today_delegated_warning_eligible(row, now=NOW)
    assert not is_harmless_editorial_code(CODE)
    with pytest.raises(GateError):
        validate_automatic_qa_producer(row)


@pytest.mark.parametrize("code", ["unknown", "rights_unverified", "customer_surface_numeric_mismatch", "privacy_failure"])
def test_unrelated_unknown_and_security_findings_do_not_enter_source_review(code):
    row = meta()
    row["issue_codes"].append(code)
    assert not source_scope_manual_review_eligible(row, now=NOW)


def test_nested_unknown_cannot_hide_behind_ui_lists():
    row = meta()
    row["runtime_validation_check"] = {"issue_details": [{"code": "rights_unverified"}]}
    assert not source_scope_manual_review_eligible(row, now=NOW)


@pytest.mark.parametrize("field,value", [("runtime_safety_status", "RUNTIME_SAFETY_FAIL"),
    ("validation_result", "fail"), ("target_date", "2026-11-25")])
def test_safety_first_pass_and_freshness_remain_required(field, value):
    row = meta(); row[field] = value
    assert not source_scope_manual_review_eligible(row, now=NOW)
