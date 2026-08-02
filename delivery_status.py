"""Canonical owner-review and customer-delivery state contracts.

SMTP acceptance means that the configured SMTP server accepted at least one
recipient. It is not mailbox delivery; only a provider delivery signal may
advance a run to ``delivery_confirmed``.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Optional


class CustomerDeliveryStatus(str, Enum):
    NOT_SENT = "not_sent"
    SEND_ATTEMPTED = "send_attempted"
    SMTP_ACCEPTED = "smtp_accepted"
    PARTIAL_ACCEPTED = "partial_accepted"
    DELIVERY_CONFIRMED = "delivery_confirmed"
    DELAYED = "delayed"
    BOUNCED = "bounced"
    REJECTED = "rejected"
    FAILED = "failed"
    BLOCKED = "blocked"
    UNKNOWN = "unknown"


class OwnerReviewDeliveryStatus(str, Enum):
    NOT_SENT = "not_sent"
    SEND_ATTEMPTED = "send_attempted"
    SMTP_ACCEPTED = "smtp_accepted"
    FAILED = "failed"


_CUSTOMER_LEGACY_ALIASES = {
    "customer_sent_after_approval": CustomerDeliveryStatus.SMTP_ACCEPTED,
    "sent_after_owner_approval": CustomerDeliveryStatus.SMTP_ACCEPTED,
    "delivery_confirmed": CustomerDeliveryStatus.DELIVERY_CONFIRMED,
    "sent_after_timeout": CustomerDeliveryStatus.SMTP_ACCEPTED,
}


def normalize_customer_delivery_status(value: Any) -> CustomerDeliveryStatus:
    """Normalize persisted legacy vocabulary without accepting vague success words."""
    if isinstance(value, CustomerDeliveryStatus):
        return value
    raw = str(value or "").strip().lower()
    if not raw:
        return CustomerDeliveryStatus.NOT_SENT
    legacy = _CUSTOMER_LEGACY_ALIASES.get(raw)
    if legacy is not None:
        return legacy
    try:
        return CustomerDeliveryStatus(raw)
    except ValueError:
        return CustomerDeliveryStatus.UNKNOWN


def is_customer_delivery_accepted(value: Any) -> bool:
    return normalize_customer_delivery_status(value) in {
        CustomerDeliveryStatus.SMTP_ACCEPTED,
        CustomerDeliveryStatus.PARTIAL_ACCEPTED,
        CustomerDeliveryStatus.DELIVERY_CONFIRMED,
    }


def is_customer_delivery_terminal_success(value: Any) -> bool:
    return normalize_customer_delivery_status(value) in {
        CustomerDeliveryStatus.SMTP_ACCEPTED,
        CustomerDeliveryStatus.DELIVERY_CONFIRMED,
    }


def is_customer_delivery_terminal_failure(value: Any) -> bool:
    return normalize_customer_delivery_status(value) in {
        CustomerDeliveryStatus.BOUNCED,
        CustomerDeliveryStatus.REJECTED,
        CustomerDeliveryStatus.BLOCKED,
    }


def is_customer_delivery_pending(value: Any) -> bool:
    return normalize_customer_delivery_status(value) in {
        CustomerDeliveryStatus.NOT_SENT,
        CustomerDeliveryStatus.SEND_ATTEMPTED,
        CustomerDeliveryStatus.DELAYED,
        CustomerDeliveryStatus.PARTIAL_ACCEPTED,
    }


def is_customer_delivery_retryable(value: Any) -> bool:
    return normalize_customer_delivery_status(value) in {
        CustomerDeliveryStatus.FAILED,
        CustomerDeliveryStatus.DELAYED,
        CustomerDeliveryStatus.PARTIAL_ACCEPTED,
    }


def normalize_owner_review_delivery_status(value: Any) -> OwnerReviewDeliveryStatus:
    if isinstance(value, OwnerReviewDeliveryStatus):
        return value
    raw = str(value or "").strip().lower()
    if not raw:
        return OwnerReviewDeliveryStatus.NOT_SENT
    try:
        return OwnerReviewDeliveryStatus(raw)
    except ValueError:
        return OwnerReviewDeliveryStatus.FAILED


def is_owner_review_accepted(value: Any) -> bool:
    return normalize_owner_review_delivery_status(value) == OwnerReviewDeliveryStatus.SMTP_ACCEPTED


def customer_delivery_status_value(value: Any) -> str:
    return normalize_customer_delivery_status(value).value


def accepted_recipient_status(
    accepted_count: int,
    requested_count: int,
) -> Optional[CustomerDeliveryStatus]:
    accepted = max(0, int(accepted_count or 0))
    requested = max(0, int(requested_count or 0))
    if accepted == 0:
        return None
    if requested and accepted < requested:
        return CustomerDeliveryStatus.PARTIAL_ACCEPTED
    return CustomerDeliveryStatus.SMTP_ACCEPTED
