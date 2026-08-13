"""Canonical vocabulary and catalog constants.

Pure in-memory checks against the approved policy documents. No database is
required, so these run in the ordinary test suite and will fail loudly if a
superseded price or a non-canonical state name is reintroduced.

Authorities:
  - docs/web/CUSTOMER_LIFECYCLE_BILLING_POLICY_v1.md sec. 1, 3, 8, 14
  - docs/web/CUSTOMER_DELIVERY_ENTITLEMENT_CONTRACT_v1.md sec. 2, 5, 17
  - docs/BUSINESS_BRAND_SSOT_v1.md sec. 7
"""

import pytest

from customer.domain import catalog
from customer.domain.enums import (
    DeliveryEmailStatus,
    DeliveryEventType,
    EntitlementSource,
    PlanCode,
    ProductCode,
    SubscriptionState,
    TERMINAL_SUBSCRIPTION_STATES,
    TRIAL_PHASE_SUBSCRIPTION_STATES,
)


def test_product_codes_are_the_three_canonical_briefings():
    assert set(ProductCode.values()) == {
        "today_genie",
        "keysuri_global",
        "keysuri_korea",
    }


def test_paid_plan_codes_match_the_canonical_catalog():
    assert set(PlanCode.values()) == {
        "today_genie",
        "keysuri_global",
        "keysuri_korea",
        "package_two",
        "full_set",
    }


def test_canonical_subscription_states_are_complete():
    """Lifecycle sec. 14 defines exactly these eleven states."""
    assert set(SubscriptionState.values()) == {
        "trialing",
        "renewal_pending",
        "conversion_scheduled",
        "trial_expired",
        "active",
        "past_due",
        "suspended",
        "cancellation_scheduled",
        "canceled",
        "withdrawal_scheduled",
        "withdrawn",
    }


@pytest.mark.parametrize("non_canonical", ["ended", "cancel_scheduled", "expired"])
def test_non_canonical_state_names_are_absent(non_canonical):
    assert non_canonical not in SubscriptionState.values()


def test_trial_phase_states_are_disjoint_from_terminal_states():
    assert not (TRIAL_PHASE_SUBSCRIPTION_STATES & TERMINAL_SUBSCRIPTION_STATES)


@pytest.mark.parametrize(
    "plan_code,expected_price",
    [
        ("today_genie", 6600),
        ("keysuri_global", 9900),
        ("keysuri_korea", 6600),
        ("package_two", 11000),
        ("full_set", 16500),
    ],
)
def test_current_vat_inclusive_prices(plan_code, expected_price):
    assert catalog.PLAN_PRICES_KRW[plan_code] == expected_price


def test_current_full_set_price_is_16500():
    """Owner decision (2026-08-11): Full Set is KRW 16,500 VAT included."""
    assert catalog.PLAN_PRICES_KRW["full_set"] == 16500


def test_historical_prices_are_not_current_policy():
    """14,300 and 29,900 are historical; neither may be a current price."""
    current = set(catalog.PLAN_PRICES_KRW.values())

    assert 14300 not in current
    assert 29900 not in current


def test_full_set_step_up_from_package_two_is_5500():
    step_up = (
        catalog.PLAN_PRICES_KRW["full_set"] - catalog.PLAN_PRICES_KRW["package_two"]
    )
    assert step_up == 5500


def test_full_set_price_composition_is_vat_inclusive():
    """Supply 15,000 + VAT 1,500 = 16,500."""
    assert catalog.PLAN_PRICES_KRW["full_set"] == 15000 + 1500


def test_package_two_requires_exactly_two_products():
    assert catalog.PLAN_PRODUCT_COUNT["package_two"] == 2


def test_full_set_requires_all_three_products():
    assert catalog.PLAN_PRODUCT_COUNT["full_set"] == 3
    assert set(catalog.PLAN_FIXED_PRODUCTS["full_set"]) == set(ProductCode.values())


def test_package_two_membership_is_a_customer_selection_not_a_catalog_fact():
    assert "package_two" not in catalog.PLAN_FIXED_PRODUCTS


def test_trial_entitlement_is_all_three_products():
    assert catalog.TRIAL_PRODUCTS == set(ProductCode.values())


def test_trial_is_fourteen_calendar_days():
    assert catalog.TRIAL_CALENDAR_DAYS == 14


def test_conversion_invitation_is_three_days_before_trial_end():
    assert catalog.CONVERSION_INVITE_LEAD_DAYS == 3


def test_paid_renewal_grace_and_retry_cadence():
    """Lifecycle sec. 8: 3-day grace, retries at Day 0 / +1 / +3."""
    assert catalog.PAID_RENEWAL_GRACE_DAYS == 3
    assert catalog.RENEWAL_RETRY_OFFSET_DAYS == (0, 1, 3)


def test_trial_eligibility_block_is_retained_for_one_year():
    assert catalog.TRIAL_ELIGIBILITY_BLOCK_DAYS == 365


def test_entitlement_sources_separate_trial_from_paid():
    assert set(EntitlementSource.values()) == {"trial", "paid"}


def test_delivery_email_statuses_support_verified_replacement():
    assert set(DeliveryEmailStatus.values()) == {
        "pending_verification",
        "active",
        "superseded",
        "suppressed",
    }


def test_delivery_vocabulary_separates_acceptance_from_receipt():
    values = set(DeliveryEventType.values())

    assert {"provider_accepted", "delivered_evidence"} <= values
    assert {"customer_contact_failure", "sender_incident"} <= values


def test_delivery_vocabulary_excludes_run_level_pipeline_stages():
    """generated / validated / owner_approved stay in the operational pipeline."""
    values = set(DeliveryEventType.values())

    assert not (values & {"generated", "validated", "owner_approved", "approved"})
