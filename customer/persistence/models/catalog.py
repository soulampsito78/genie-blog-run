"""Product and plan catalog.

Canonical: docs/web/CUSTOMER_LIFECYCLE_BILLING_POLICY_v1.md sec. 1 / sec. 1.1

Three concepts are kept apart on purpose:

  1. `Product`      - what can be delivered (three briefings).
  2. `PlanCatalog`  - a purchasable, versioned, priced plan definition.
  3. the subscription's own frozen contract (see models/subscription.py).

Conflating 2 and 3 is what makes a billing system silently re-price historical
contracts, which Lifecycle sec. 1.1 explicitly forbids.
"""

import datetime as dt
import uuid
from typing import Optional

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from customer.domain.catalog import CURRENCY_KRW
from customer.domain.enums import PlanCode, ProductCode
from customer.persistence.base import (
    CustomerBase,
    created_at_column,
    enum_check,
    updated_at_column,
    uuid_pk,
)


class Product(CustomerBase):
    """One of the three briefing products (Delivery contract sec. 2)."""

    __tablename__ = "product"

    code: Mapped[str] = mapped_column(sa.String(40), primary_key=True)
    display_name_ko: Mapped[str] = mapped_column(sa.String(120), nullable=False)
    display_name_en: Mapped[str] = mapped_column(sa.String(120), nullable=False)

    created_at: Mapped[dt.datetime] = created_at_column()

    __table_args__ = (
        enum_check("code", ProductCode, "code_valid"),
    )


class PlanCatalog(CustomerBase):
    """A versioned, priced plan definition.

    Price changes are additive: insert a row with the next `price_version` and
    close the previous row's `effective_to`. Never UPDATE `price_krw` on an
    existing row - live contracts and audit evidence reference it.
    """

    __tablename__ = "plan_catalog"

    id: Mapped[uuid.UUID] = uuid_pk()

    plan_code: Mapped[str] = mapped_column(sa.String(40), nullable=False)
    price_version: Mapped[int] = mapped_column(sa.Integer, nullable=False)

    #: VAT-INCLUSIVE monthly price. Lifecycle sec. 1: all catalog prices are
    #: quoted VAT-inclusive, so `vat_included` is constrained to TRUE rather
    #: than left as an ambiguous flag.
    price_krw: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    currency: Mapped[str] = mapped_column(
        sa.String(3), nullable=False, server_default=sa.text("'KRW'")
    )
    vat_included: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, server_default=sa.true()
    )

    #: How many products this plan's product set must contain: 1 for singles,
    #: 2 for package_two, 3 for full_set. Deferred constraint triggers compare
    #: actual selections against this value.
    product_count: Mapped[int] = mapped_column(sa.SmallInteger, nullable=False)

    effective_from: Mapped[dt.datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False
    )
    effective_to: Mapped[Optional[dt.datetime]] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[dt.datetime] = created_at_column()
    updated_at: Mapped[dt.datetime] = updated_at_column()

    __table_args__ = (
        enum_check("plan_code", PlanCode, "plan_code_valid"),
        sa.UniqueConstraint(
            "plan_code", "price_version", name="uq_plan_catalog_plan_code_price_version"
        ),
        sa.CheckConstraint("price_krw > 0", name="price_positive"),
        sa.CheckConstraint(
            "currency = '{0}'".format(CURRENCY_KRW), name="currency_krw"
        ),
        sa.CheckConstraint("vat_included IS TRUE", name="vat_included"),
        sa.CheckConstraint(
            "price_version > 0", name="price_version_positive"
        ),
        sa.CheckConstraint(
            "effective_to IS NULL OR effective_to > effective_from",
            name="effective_range",
        ),
        # INVARIANT (Lifecycle sec. 1): package_two is exactly two distinct
        # products and full_set is all three. Encoded here so a bad catalog row
        # cannot exist in the first place.
        sa.CheckConstraint(
            "(plan_code = 'package_two' AND product_count = 2) "
            "OR (plan_code = 'full_set' AND product_count = 3) "
            "OR (plan_code IN ('today_genie', 'keysuri_global', 'keysuri_korea') "
            "AND product_count = 1)",
            name="product_count_matches_plan",
        ),
        # One live catalog row per plan at a time.
        sa.Index(
            "uq_plan_catalog_open_plan_code",
            "plan_code",
            unique=True,
            postgresql_where=sa.text("effective_to IS NULL"),
        ),
    )


class PlanFixedProduct(CustomerBase):
    """Product membership for plans whose contents are NOT customer-selected.

    `package_two` has no rows here by design - its two products are a customer
    selection frozen onto the conversion snapshot / subscription, not a catalog
    fact.
    """

    __tablename__ = "plan_fixed_product"

    plan_code: Mapped[str] = mapped_column(sa.String(40), primary_key=True)
    product_code: Mapped[str] = mapped_column(
        sa.String(40),
        sa.ForeignKey("product.code", ondelete="RESTRICT"),
        primary_key=True,
    )

    __table_args__ = (
        sa.CheckConstraint(
            "plan_code IN ('today_genie', 'keysuri_global', 'keysuri_korea', 'full_set')",
            name="plan_code_is_fixed_membership",
        ),
    )
