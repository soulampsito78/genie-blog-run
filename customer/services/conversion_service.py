"""D-3 paid-conversion selection and explicit-consent foundation.

This service schedules a frozen conversion contract for ``trial_end_at``.  It
does not call a payment provider, create a billing attempt, charge, or activate
a paid subscription.
"""

import datetime as dt
import hashlib
import uuid
from dataclasses import dataclass
from typing import Iterable, Optional, Tuple

import sqlalchemy as sa
from sqlalchemy.orm import Session

from customer.domain.catalog import (
    CONVERSION_INVITE_LEAD_DAYS,
    CURRENCY_KRW,
    PLAN_FIXED_PRODUCTS,
    PLAN_PRICES_KRW,
    PLAN_PRODUCT_COUNT,
)
from customer.domain.clock import Clock, ensure_utc
from customer.domain.enums import (
    AccountStatus,
    CommandIdempotencyStatus,
    ConversionSnapshotStatus,
    PaymentMethodStatus,
    PlanCode,
    ProductCode,
    SubscriptionState,
)
from customer.domain.errors import (
    AccountNotActive,
    CatalogUnavailable,
    ConversionNotEligible,
    ConversionSelectionInvalid,
    ConversionSelectionRequired,
    IdempotencyKeyConflict,
    PaymentMethodRequired,
)
from customer.persistence.models import (
    CommandIdempotency,
    ConversionSelection,
    ConversionSelectionProduct,
    ConversionSnapshot,
    ConversionSnapshotProduct,
    CustomerAccount,
    PaymentMethod,
    PersonIdentity,
    PlanCatalog,
    Subscription,
)
from customer.services import audit_service as audit_events
from customer.services.audit_service import AuditService


CONVERSION_CONFIRM_COMMAND = "subscription.conversion_confirm"


@dataclass(frozen=True)
class ConversionEligibility:
    subscription: Subscription
    eligible: bool
    opens_at: dt.datetime
    closes_at: dt.datetime


@dataclass(frozen=True)
class ConversionResult:
    subscription: Subscription
    selection: ConversionSelection
    snapshot: Optional[ConversionSnapshot]
    products: Tuple[str, ...]
    replayed: bool = False


class ConversionService:
    """Coordinate mutable selection and immutable explicit conversion consent."""

    def __init__(self, session: Session, clock: Clock, audit=None) -> None:
        self._session = session
        self._clock = clock
        self._audit = audit or AuditService(session, clock)

    def catalog(self, account_id: uuid.UUID) -> Tuple[Tuple[PlanCatalog, Tuple[str, ...]], ...]:
        self._active_account(account_id, lock=False)
        now = ensure_utc(self._clock.now())
        rows = list(
            self._session.scalars(
                sa.select(PlanCatalog)
                .where(
                    PlanCatalog.effective_from <= now,
                    sa.or_(PlanCatalog.effective_to.is_(None), PlanCatalog.effective_to > now),
                )
                .order_by(PlanCatalog.plan_code.asc())
            ).all()
        )
        if {row.plan_code for row in rows} != set(PlanCode.values()) or len(rows) != 5:
            raise CatalogUnavailable("exactly one current version of each plan is required")
        result = []
        for row in rows:
            self._assert_canonical_catalog_row(row)
            products = PLAN_FIXED_PRODUCTS.get(row.plan_code, tuple())
            result.append((row, tuple(sorted(products))))
        return tuple(result)

    def eligibility(self, account_id: uuid.UUID) -> ConversionEligibility:
        self._active_account(account_id, lock=False)
        subscription = self._trial_subscription(account_id, lock=False)
        opens_at, closes_at = self._window(subscription)
        now = ensure_utc(self._clock.now())
        eligible = (
            opens_at <= now < closes_at
            and subscription.state
            in {
                SubscriptionState.TRIALING.value,
                SubscriptionState.RENEWAL_PENDING.value,
            }
        )
        return ConversionEligibility(subscription, eligible, opens_at, closes_at)

    def select(
        self,
        *,
        account_id: uuid.UUID,
        plan_code: str,
        products: Iterable[str],
    ) -> ConversionResult:
        self._active_account(account_id)
        subscription = self._trial_subscription(account_id)
        self._assert_open(subscription)
        if subscription.state == SubscriptionState.CONVERSION_SCHEDULED.value:
            raise ConversionNotEligible("confirmed conversion cannot be changed")
        catalog = self._catalog_row(plan_code)
        selected_products = self._validate_products(plan_code, products)
        now = ensure_utc(self._clock.now())

        selection = self._session.scalar(
            sa.select(ConversionSelection)
            .where(ConversionSelection.subscription_id == subscription.id)
            .with_for_update()
        )
        if selection is None:
            selection = ConversionSelection(
                account_id=account_id,
                subscription_id=subscription.id,
                plan_code=catalog.plan_code,
                price_krw=catalog.price_krw,
                price_version=catalog.price_version,
                currency=catalog.currency,
                selected_at=now,
                created_at=now,
                updated_at=now,
            )
            self._session.add(selection)
            self._session.flush()
        else:
            current_products = self._selection_products(selection.id)
            if (
                selection.plan_code == catalog.plan_code
                and selection.price_krw == catalog.price_krw
                and selection.price_version == catalog.price_version
                and selection.currency == catalog.currency
                and current_products == selected_products
            ):
                if subscription.state == SubscriptionState.TRIALING.value:
                    subscription.state = SubscriptionState.RENEWAL_PENDING.value
                    subscription.updated_at = now
                    self._session.flush()
                return ConversionResult(
                    subscription, selection, None, selected_products, replayed=True
                )
            selection.plan_code = catalog.plan_code
            selection.price_krw = catalog.price_krw
            selection.price_version = catalog.price_version
            selection.currency = catalog.currency
            selection.selected_at = now
            selection.updated_at = now
            selection.products.clear()
            self._session.flush()
        selection.products.extend(
            ConversionSelectionProduct(product_code=product)
            for product in selected_products
        )
        if subscription.state == SubscriptionState.TRIALING.value:
            subscription.state = SubscriptionState.RENEWAL_PENDING.value
            subscription.updated_at = now
        self._session.flush()
        return ConversionResult(subscription, selection, None, selected_products)

    def current_selection(self, account_id: uuid.UUID) -> ConversionResult:
        self._active_account(account_id, lock=False)
        subscription = self._trial_subscription(account_id, lock=False)
        selection = self._session.scalar(
            sa.select(ConversionSelection).where(
                ConversionSelection.subscription_id == subscription.id,
                ConversionSelection.account_id == account_id,
            )
        )
        if selection is None:
            raise ConversionSelectionRequired("no paid plan has been selected")
        snapshot = self._session.scalar(
            sa.select(ConversionSnapshot).where(
                ConversionSnapshot.selection_id == selection.id,
                ConversionSnapshot.account_id == account_id,
            )
        )
        return ConversionResult(
            subscription,
            selection,
            snapshot,
            self._selection_products(selection.id),
            replayed=snapshot is not None,
        )

    def confirm(
        self, *, account_id: uuid.UUID, idempotency_key: str
    ) -> ConversionResult:
        account = self._active_account(account_id)
        subscription = self._trial_subscription(account_id)
        key = _idempotency_key(idempotency_key)
        command = self._command(key)
        if command is not None:
            self._assert_same_command(command, account_id)
            return self._replayed_result(command, account_id)

        self._assert_open(subscription)
        if subscription.state not in {
            SubscriptionState.TRIALING.value,
            SubscriptionState.RENEWAL_PENDING.value,
        }:
            raise ConversionNotEligible("trial is not awaiting conversion consent")
        selection = self._session.scalar(
            sa.select(ConversionSelection)
            .where(
                ConversionSelection.subscription_id == subscription.id,
                ConversionSelection.account_id == account_id,
            )
            .with_for_update()
        )
        if selection is None:
            raise ConversionSelectionRequired("explicit paid plan selection required")
        products = self._selection_products(selection.id)
        catalog = self._catalog_row(selection.plan_code)
        if (
            selection.price_krw != catalog.price_krw
            or selection.price_version != catalog.price_version
            or selection.currency != catalog.currency
        ):
            raise ConversionSelectionInvalid("selected catalog version is no longer current")
        self._validate_products(selection.plan_code, products)
        payment_method = self._usable_default_payment_method(account_id)
        now = ensure_utc(self._clock.now())
        first_charge_at = ensure_utc(subscription.trial_end_at)
        snapshot = ConversionSnapshot(
            selection_id=selection.id,
            account_id=account.id,
            person_id=account.person_id,
            subscription_id=subscription.id,
            payment_method_id=payment_method.id,
            plan_code=selection.plan_code,
            price_krw=selection.price_krw,
            price_version=selection.price_version,
            currency=selection.currency,
            confirmed_at=now,
            first_charge_at=first_charge_at,
            status=ConversionSnapshotStatus.PENDING.value,
            created_at=now,
            updated_at=now,
        )
        self._session.add(snapshot)
        self._session.flush()
        snapshot.products.extend(
            ConversionSnapshotProduct(product_code=product) for product in products
        )
        subscription.state = SubscriptionState.CONVERSION_SCHEDULED.value
        subscription.updated_at = now
        self._session.add(
            CommandIdempotency(
                account_id=account_id,
                command=CONVERSION_CONFIRM_COMMAND,
                idempotency_key=key,
                request_fingerprint=_fingerprint(account_id),
                status=CommandIdempotencyStatus.COMPLETED.value,
                result_reference=str(snapshot.id),
                created_at=now,
                updated_at=now,
                completed_at=now,
            )
        )
        self._session.flush()
        self._audit.record(
            audit_events.CONVERSION_CONFIRMED,
            account_id=account_id,
            subscription_id=subscription.id,
            actor_type="customer",
            entity_type="conversion_snapshot",
            entity_id=snapshot.id,
            payload={
                "plan_code": snapshot.plan_code,
                "price_krw": snapshot.price_krw,
                "price_version": snapshot.price_version,
                "currency": snapshot.currency,
                "product_count": len(products),
                "first_charge_at": snapshot.first_charge_at.isoformat(),
                "charged": False,
            },
        )
        return ConversionResult(subscription, selection, snapshot, products)

    def _active_account(self, account_id: uuid.UUID, *, lock: bool = True) -> CustomerAccount:
        query = sa.select(CustomerAccount).where(CustomerAccount.id == account_id)
        if lock:
            query = query.with_for_update()
        account = self._session.scalar(query)
        if account is None or account.status != AccountStatus.ACTIVE.value:
            raise AccountNotActive("account is not active")
        person = self._session.get(PersonIdentity, account.person_id)
        if person is None or not person.adult_verified or person.adult_verified_at is None:
            raise ConversionNotEligible("verified adult identity is required")
        return account

    def _trial_subscription(self, account_id: uuid.UUID, *, lock: bool = True) -> Subscription:
        query = sa.select(Subscription).where(
            Subscription.account_id == account_id,
            Subscription.trial_start_at.is_not(None),
        ).order_by(Subscription.created_at.desc())
        if lock:
            query = query.with_for_update()
        subscription = self._session.scalar(query)
        if subscription is None or subscription.trial_end_at is None:
            raise ConversionNotEligible("trial subscription is unavailable")
        return subscription

    def _window(self, subscription: Subscription) -> Tuple[dt.datetime, dt.datetime]:
        closes_at = ensure_utc(subscription.trial_end_at)
        return closes_at - dt.timedelta(days=CONVERSION_INVITE_LEAD_DAYS), closes_at

    def _assert_open(self, subscription: Subscription) -> None:
        opens_at, closes_at = self._window(subscription)
        now = ensure_utc(self._clock.now())
        if now < opens_at or now >= closes_at:
            raise ConversionNotEligible("conversion is available only in the D-3 window")

    def _catalog_row(self, plan_code: str) -> PlanCatalog:
        if plan_code not in PlanCode.values():
            raise ConversionSelectionInvalid("unknown paid plan")
        now = ensure_utc(self._clock.now())
        rows = list(self._session.scalars(sa.select(PlanCatalog).where(
            PlanCatalog.plan_code == plan_code,
            PlanCatalog.effective_from <= now,
            sa.or_(PlanCatalog.effective_to.is_(None), PlanCatalog.effective_to > now),
        )).all())
        if len(rows) != 1:
            raise CatalogUnavailable("one current catalog version is required")
        self._assert_canonical_catalog_row(rows[0])
        return rows[0]

    @staticmethod
    def _assert_canonical_catalog_row(row: PlanCatalog) -> None:
        if (
            row.price_krw != PLAN_PRICES_KRW[row.plan_code]
            or row.product_count != PLAN_PRODUCT_COUNT[row.plan_code]
            or row.currency != CURRENCY_KRW
            or not row.vat_included
        ):
            raise CatalogUnavailable("current catalog does not match canonical pricing")

    @staticmethod
    def _validate_products(plan_code: str, products: Iterable[str]) -> Tuple[str, ...]:
        raw = tuple(str(product) for product in products)
        selected = tuple(sorted(set(raw)))
        if len(selected) != len(raw):
            raise ConversionSelectionInvalid("selected products must be distinct")
        if not set(selected).issubset(set(ProductCode.values())):
            raise ConversionSelectionInvalid("unknown product selection")
        fixed = PLAN_FIXED_PRODUCTS.get(plan_code)
        if fixed is not None:
            if set(selected) != set(fixed):
                raise ConversionSelectionInvalid("fixed plan composition mismatch")
        elif plan_code == PlanCode.PACKAGE_TWO.value:
            if len(selected) != 2:
                raise ConversionSelectionInvalid("package_two requires two products")
        else:
            raise ConversionSelectionInvalid("unknown plan selection")
        return selected

    def _usable_default_payment_method(self, account_id: uuid.UUID) -> PaymentMethod:
        method = self._session.scalar(sa.select(PaymentMethod).where(
            PaymentMethod.account_id == account_id,
            PaymentMethod.status == PaymentMethodStatus.ACTIVE.value,
            PaymentMethod.is_default.is_(True),
            PaymentMethod.own_name_verified.is_(True),
            PaymentMethod.own_name_verified_at.is_not(None),
        ).with_for_update())
        if method is None or not method.billing_key_reference.strip():
            raise PaymentMethodRequired("usable default payment method required")
        return method

    def _selection_products(self, selection_id: uuid.UUID) -> Tuple[str, ...]:
        return tuple(sorted(self._session.scalars(sa.select(
            ConversionSelectionProduct.product_code
        ).where(ConversionSelectionProduct.conversion_selection_id == selection_id)).all()))

    def _command(self, key: str) -> Optional[CommandIdempotency]:
        return self._session.scalar(sa.select(CommandIdempotency).where(
            CommandIdempotency.command == CONVERSION_CONFIRM_COMMAND,
            CommandIdempotency.idempotency_key == key,
        ))

    @staticmethod
    def _assert_same_command(command: CommandIdempotency, account_id: uuid.UUID) -> None:
        if command.account_id != account_id or command.request_fingerprint != _fingerprint(account_id):
            raise IdempotencyKeyConflict("idempotency key belongs to another conversion")
        if command.status != CommandIdempotencyStatus.COMPLETED.value or not command.result_reference:
            raise IdempotencyKeyConflict("conversion confirmation is incomplete")

    def _replayed_result(self, command: CommandIdempotency, account_id: uuid.UUID) -> ConversionResult:
        try:
            snapshot_id = uuid.UUID(command.result_reference)
        except (TypeError, ValueError):
            raise IdempotencyKeyConflict("conversion result reference is invalid")
        snapshot = self._session.get(ConversionSnapshot, snapshot_id)
        if snapshot is None or snapshot.account_id != account_id:
            raise IdempotencyKeyConflict("conversion result reference is unavailable")
        subscription = self._session.get(Subscription, snapshot.subscription_id)
        selection = self._session.get(ConversionSelection, snapshot.selection_id)
        if subscription is None or selection is None:
            raise IdempotencyKeyConflict("conversion result state is unavailable")
        products = tuple(sorted(self._session.scalars(sa.select(
            ConversionSnapshotProduct.product_code
        ).where(ConversionSnapshotProduct.conversion_snapshot_id == snapshot.id)).all()))
        return ConversionResult(subscription, selection, snapshot, products, replayed=True)


def _idempotency_key(value: str) -> str:
    normalized = str(value or "").strip()
    if not normalized or len(normalized) > 200:
        raise IdempotencyKeyConflict("invalid idempotency key")
    return normalized


def _fingerprint(account_id: uuid.UUID) -> str:
    return hashlib.sha256(
        "conversion-confirm-v1:{0}".format(account_id).encode("utf-8")
    ).hexdigest()
