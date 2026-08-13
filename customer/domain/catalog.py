"""Canonical product / plan catalog constants.

Source of truth: docs/web/CUSTOMER_LIFECYCLE_BILLING_POLICY_v1.md sec. 1,
corroborated by docs/BUSINESS_BRAND_SSOT_v1.md sec. 7 and
docs/web/GENIE_KEYSURI_CUSTOMER_WEB_SSOT_v1.md sec. 3.

IMPORTANT - these constants are the *current catalog only*. They are NOT the
billing authority. Lifecycle sec. 1.1 forbids billing an existing contract by
reading the live catalog price: every paid contract carries its own frozen
`price_krw` + `price_version` (see `conversion_snapshot` and `subscription`).
The catalog rows exist so that a *new* selection can be priced and versioned;
changing a price means inserting a new `plan_catalog` row with a new
`price_version` and closing the old row's `effective_to`, never UPDATEing a
historical price.
"""

from typing import Dict, FrozenSet, Tuple

from customer.domain.enums import PlanCode, ProductCode

#: Version of the price list seeded by the initial migration. Bump by adding
#: new plan_catalog rows; never by editing existing ones.
INITIAL_PRICE_VERSION = 1

CURRENCY_KRW = "KRW"

#: Monthly, VAT-inclusive prices in KRW (Lifecycle sec. 1).
#:
#: NOTE ON full_set: the CURRENT price is 16,500 KRW, set by explicit owner
#: decision (2026-08-11) which outranks the earlier 14,300 KRW figure. 14,300
#: is HISTORICAL and MUST NOT be used as current customer policy.
#: Composition: supply 15,000 + VAT 1,500 = 16,500. Step-up from
#: `package_two` is 5,500.
PLAN_PRICES_KRW: Dict[str, int] = {
    PlanCode.TODAY_GENIE.value: 6600,
    PlanCode.KEYSURI_GLOBAL.value: 9900,
    PlanCode.KEYSURI_KOREA.value: 6600,
    PlanCode.PACKAGE_TWO.value: 11000,
    PlanCode.FULL_SET.value: 16500,
}

#: How many products a plan's product set must contain. `package_two` is
#: customer-selected (exactly two distinct products); the others are fixed.
PLAN_PRODUCT_COUNT: Dict[str, int] = {
    PlanCode.TODAY_GENIE.value: 1,
    PlanCode.KEYSURI_GLOBAL.value: 1,
    PlanCode.KEYSURI_KOREA.value: 1,
    PlanCode.PACKAGE_TWO.value: 2,
    PlanCode.FULL_SET.value: 3,
}

#: Plans whose product membership is fixed by the catalog rather than chosen by
#: the customer. `package_two` is absent precisely because it is a selection.
PLAN_FIXED_PRODUCTS: Dict[str, Tuple[str, ...]] = {
    PlanCode.TODAY_GENIE.value: (ProductCode.TODAY_GENIE.value,),
    PlanCode.KEYSURI_GLOBAL.value: (ProductCode.KEYSURI_GLOBAL.value,),
    PlanCode.KEYSURI_KOREA.value: (ProductCode.KEYSURI_KOREA.value,),
    PlanCode.FULL_SET.value: (
        ProductCode.TODAY_GENIE.value,
        ProductCode.KEYSURI_GLOBAL.value,
        ProductCode.KEYSURI_KOREA.value,
    ),
}

#: Trial entitlement is always all three products (Lifecycle sec. 3), and is
#: NOT expressed as a paid plan selection.
TRIAL_PRODUCTS: FrozenSet[str] = frozenset(
    {
        ProductCode.TODAY_GENIE.value,
        ProductCode.KEYSURI_GLOBAL.value,
        ProductCode.KEYSURI_KOREA.value,
    }
)

#: Customer-facing display names, seeded into `product` for catalog APIs.
PRODUCT_DISPLAY_NAMES: Dict[str, Tuple[str, str]] = {
    ProductCode.TODAY_GENIE.value: ("오늘의 지니 브리핑", "Today Genie Briefing"),
    ProductCode.KEYSURI_GLOBAL.value: ("키수리 글로벌", "KeeSuri Global"),
    ProductCode.KEYSURI_KOREA.value: ("키수리 코리아", "KeeSuri Korea"),
}

#: Free trial length in calendar days (Lifecycle sec. 3). Calendar days, not
#: publication days.
TRIAL_CALENDAR_DAYS = 14

#: Days before `trial_end_at` at which the conversion invitation is sent
#: (Lifecycle sec. 4.1).
CONVERSION_INVITE_LEAD_DAYS = 3

#: Grace period, in days, for an ALREADY-PAID subscriber's failed renewal
#: (Lifecycle sec. 8). A never-paid first conversion charge gets no grace.
PAID_RENEWAL_GRACE_DAYS = 3

#: Fixed renewal retry cadence, in days from the scheduled billing day
#: (Lifecycle sec. 8).
RENEWAL_RETRY_OFFSET_DAYS: Tuple[int, ...] = (0, 1, 3)

#: Free-trial eligibility block retention, in days, keyed by stable verified
#: person identity (Lifecycle sec. 3.2).
TRIAL_ELIGIBILITY_BLOCK_DAYS = 365
