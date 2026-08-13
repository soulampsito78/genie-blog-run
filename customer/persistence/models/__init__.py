"""Customer ORM models.

Importing this package registers every customer table on
`customer.persistence.base.customer_metadata`, which is what Alembic's
autogenerate compares the live database against. Any new model module MUST be
imported here or it will silently drop out of migrations.
"""

from customer.persistence.models.audit import AuditEvent, CommandIdempotency
from customer.persistence.models.auth import AuthChallenge, IdentityVerification
from customer.persistence.models.billing import BillingAttempt, BillingEvent
from customer.persistence.models.catalog import PlanCatalog, PlanFixedProduct, Product
from customer.persistence.models.delivery import (
    DeliveryEmail,
    DeliveryEvent,
    Entitlement,
    RecipientSnapshot,
)
from customer.persistence.models.identity import (
    BrowserSession,
    CustomerAccount,
    PersonIdentity,
    TrialEligibilityBlock,
)
from customer.persistence.models.payment import PaymentMethod
from customer.persistence.models.subscription import (
    ConversionSnapshot,
    ConversionSnapshotProduct,
    Subscription,
    SubscriptionProduct,
)

__all__ = [
    "AuditEvent",
    "AuthChallenge",
    "BillingAttempt",
    "BillingEvent",
    "BrowserSession",
    "CommandIdempotency",
    "ConversionSnapshot",
    "ConversionSnapshotProduct",
    "CustomerAccount",
    "DeliveryEmail",
    "DeliveryEvent",
    "Entitlement",
    "IdentityVerification",
    "PaymentMethod",
    "PersonIdentity",
    "PlanCatalog",
    "PlanFixedProduct",
    "Product",
    "RecipientSnapshot",
    "Subscription",
    "SubscriptionProduct",
    "TrialEligibilityBlock",
]
