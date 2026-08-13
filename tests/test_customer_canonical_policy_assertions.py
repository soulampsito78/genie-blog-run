"""Canonical-document invariants for customer IA, signup, and D-3.

These lock governance decisions that are easy to erode silently in prose. They
read the active canonical documents and the project constitution; no database
is needed, so they run in the ordinary suite.

Historical evidence reports are deliberately NOT asserted against - a dated
report describing a past state is allowed to describe that past state.
"""

import pathlib
import re

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
DOCS_WEB = REPO_ROOT / "docs" / "web"

CLAUDE_MD = REPO_ROOT / "CLAUDE.md"
WEB_SSOT = DOCS_WEB / "GENIE_KEYSURI_CUSTOMER_WEB_SSOT_v1.md"
UX_SPEC = DOCS_WEB / "FRONTEND_UX_SPEC_v1.md"
API_CONTRACT = DOCS_WEB / "FRONTEND_API_CONTRACT_v1.md"
LIFECYCLE = DOCS_WEB / "CUSTOMER_LIFECYCLE_BILLING_POLICY_v1.md"
AUTH_SPEC = DOCS_WEB / "CUSTOMER_AUTH_IDENTITY_SESSION_SPEC_v1.md"

#: Active policy documents. Excludes dated evidence reports on purpose.
ACTIVE_POLICY_DOCS = (WEB_SSOT, UX_SPEC, API_CONTRACT, LIFECYCLE, AUTH_SPEC)


def read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Constitution (CLAUDE.md)
# ---------------------------------------------------------------------------


def test_constitution_exists():
    assert CLAUDE_MD.is_file()


def test_constitution_declares_exactly_three_customer_areas():
    text = read(CLAUDE_MD)

    assert re.search(r"exactly\s+\*\*three\*\*|exactly\s+three", text, re.I)
    for area in ("Landing & Introduction", "Signup & Payment", "My Page"):
        assert area in text


def test_constitution_says_login_is_not_a_fourth_area():
    text = read(CLAUDE_MD).lower()

    assert "authentication entry surface" in text
    assert "not a fourth area" in text


def test_constitution_declares_admin_a_private_operator_surface():
    text = read(CLAUDE_MD).lower()

    assert "private operator surface" in text
    assert "0" in text and "admin destinations" in text


def test_constitution_declares_four_stage_signup():
    text = read(CLAUDE_MD)

    assert re.search(r"exactly\s+FOUR\s+stages", text, re.I)
    lowered = text.lower()
    assert "adult mobile identity verification" in lowered
    assert "own-name payment method registration" in lowered


def test_constitution_forbids_paid_plan_selection_at_signup():
    text = read(CLAUDE_MD).lower()

    assert "no paid-plan selection" in text
    assert "no future paid-plan name and no future paid price" in text


def test_constitution_declares_d3_the_first_paid_plan_selection_point():
    text = read(CLAUDE_MD)

    assert re.search(r"D-3 is the FIRST paid-plan selection point", text, re.I)
    lowered = text.lower()
    assert "no charge at d-3" in lowered
    assert "trial_end_at" in lowered


def test_constitution_forbids_pre_d3_future_plan_display():
    text = read(CLAUDE_MD).lower()

    assert "pre-d-3" in text
    assert "conversion_scheduled" in text


def test_constitution_retains_prior_rules():
    """Hardening must not have dropped earlier constitution sections."""
    text = read(CLAUDE_MD).lower()

    for required in (
        "authority order",
        "evidence before claim",
        "fail closed",
        "alembic",
        "supabase",
        "giant step",
        "unattended execution",
        "16,500",
        "06:30",
    ):
        assert required in text, required


# ---------------------------------------------------------------------------
# Customer information architecture
# ---------------------------------------------------------------------------


def test_web_ssot_declares_exactly_three_customer_areas():
    text = read(WEB_SSOT)

    assert "Exactly **three** customer-facing top-level areas" in text


def test_web_ssot_excludes_admin_from_customer_areas():
    text = read(WEB_SSOT)

    assert "**Admin / Owner Review is NOT a customer-web top-level area.**" in text
    assert "MUST NOT** invent a fourth customer-facing top-level product category" in text


def test_ux_spec_excludes_admin_from_customer_screens():
    text = read(UX_SPEC)

    assert "Admin is **not** a customer top-level screen" in text


def test_no_active_document_claims_four_customer_top_level_areas():
    pattern = re.compile(r"(four|4)\s+(customer[- ])?top[- ]level", re.I)

    for path in ACTIVE_POLICY_DOCS:
        for line in read(path).splitlines():
            if pattern.search(line):
                # Only prohibition phrasing is acceptable.
                assert re.search(r"MUST NOT|not\b|never", line, re.I), (
                    "{0}: {1}".format(path.name, line.strip())
                )


# ---------------------------------------------------------------------------
# Signup contract
# ---------------------------------------------------------------------------


def test_ux_spec_declares_exactly_four_signup_stages():
    text = read(UX_SPEC)

    assert "Canonical signup has **exactly FOUR** stages" in text


def test_ux_spec_forbids_plan_selection_before_card_registration():
    text = read(UX_SPEC)

    assert "MUST NOT:** Require paid-plan selection before card registration" in text


def test_ux_spec_signup_confirmation_hides_future_plan_and_price():
    """Stage 4 must not name a future paid plan or its price."""
    text = read(UX_SPEC)
    section = text.split("## 7. Signup — Trial confirmation")[1].split("## 8.")[0]

    assert "selected future paid plan" in section
    assert "future paid plan price" in section
    assert "MUST NOT" in section


def test_lifecycle_declares_no_paid_plan_at_signup():
    text = read(LIFECYCLE)

    assert "paid-plan selection is **not** part of trial signup" in text


def test_web_ssot_declares_no_paid_plan_at_signup():
    text = read(WEB_SSOT)

    assert "**without** choosing a paid plan at signup" in text


# ---------------------------------------------------------------------------
# API contract - trial start must not require a paid plan
# ---------------------------------------------------------------------------


def test_api_contract_trial_start_forbids_plan_code():
    text = read(API_CONTRACT)

    assert "**MUST NOT** require `plan_code` / paid-plan selection" in text
    assert "requiring paid plan on `trial/start`" in text


def test_api_contract_puts_first_plan_selection_at_conversion_accept():
    text = read(API_CONTRACT)

    assert (
        "Initial D-3 paid-plan selection belongs to `conversion/accept`" in text
    )


def test_api_contract_keeps_package_two_validation_at_conversion():
    text = read(API_CONTRACT)

    assert "`selected_products` when `package_two`" in text


# ---------------------------------------------------------------------------
# D-3 and pre-D-3
# ---------------------------------------------------------------------------


def test_lifecycle_declares_d3_the_initial_plan_selection():
    text = read(LIFECYCLE)

    assert "**INITIAL paid-plan selection** occurs only in this D-3 conversion flow." in text


def test_lifecycle_forbids_charge_at_d3():
    text = read(LIFECYCLE)

    assert "**MUST NOT** charge at D-3" in text
    assert "**MUST** schedule first paid charge for `trial_end_at`" in text


def test_ux_spec_pre_d3_my_page_hides_future_plan_and_price():
    text = read(UX_SPEC)
    section = text.split("### 10.1 Trial before D-3")[1].split("### 10.2")[0]

    assert "MUST NOT" in section
    assert "selected future paid plan" in section
    assert "future paid price" in section


def test_ux_spec_shows_pending_plan_only_after_conversion_scheduled():
    text = read(UX_SPEC)
    section = text.split("### 10.3 After conversion confirmation")[1].split("## 11.")[0]

    assert "conversion_scheduled" in section
    assert "agreed pending price" in section


def test_lifecycle_forbids_automatic_conversion():
    text = read(LIFECYCLE)

    assert "Auto paid conversion" in text
    assert "**MUST NOT** occur" in text
