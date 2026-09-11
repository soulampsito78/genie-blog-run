"""Durable one-time admin delegation for the exact beta recipient cohort.

The grant is intentionally narrower than a customer subscription database.  It
authorizes unattended delivery only to the exact admin-managed beta cohort that
the operator activated.  Any address, config-version, disabled-list, product or
policy change invalidates the grant and fails closed before SMTP submission.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
from typing import Any, Iterable

from zoneinfo import ZoneInfo

DELEGATION_SCHEMA = "admin-beta-delegation-v1"
DELEGATION_POLICY = "admin-beta-continuous-send-v1"
DELEGATION_AUTHORITY = "ADMIN_BETA_DELEGATION"
SUPPRESSION_POLICY = "ADMIN_DISABLED_RECIPIENTS_V1"
DEFAULT_RECIPIENT_COUNT = 12
ALLOWED_MODES = frozenset(
    {"today_genie", "keysuri_global_tech", "keysuri_korea_tech"}
)
KST = ZoneInfo("Asia/Seoul")
_CURRENT_KEY = "admin_beta_delegation/current.json"


def _digest(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _normalised_products(products: Iterable[str]) -> list[str]:
    result = sorted({str(value or "").strip() for value in products})
    if not result or not set(result) <= ALLOWED_MODES:
        from delegated_delivery_safety import DeliverySafetyError

        raise DeliverySafetyError("ADMIN_BETA_DELEGATION_PRODUCT_SCOPE_INVALID")
    return result


def _read_current_with_generation() -> tuple[dict[str, Any] | None, str]:
    """Read the revocation pointer together with its storage generation."""
    import admin_safety_store as store
    from delegated_delivery_safety import DeliverySafetyError

    try:
        if store._uses_gcs_backend():
            blob = store._get_gcs_bucket().blob(f"{store.SAFETY_PREFIX}/{_CURRENT_KEY}")
            if not blob.exists():
                return None, "0"
            blob.reload()
            raw = blob.download_as_text()
            generation = str(blob.generation or "")
        else:
            path = store._local_path(_CURRENT_KEY)
            if not path.is_file():
                return None, "0"
            raw = path.read_text(encoding="utf-8")
            generation = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        value = json.loads(raw)
        if not isinstance(value, dict) or not generation:
            raise ValueError()
        return value, generation
    except DeliverySafetyError:
        raise
    except Exception as exc:
        raise DeliverySafetyError("ADMIN_BETA_DELEGATION_STATE_UNAVAILABLE") from exc


def _compare_and_swap_current(
    expected_generation: str, payload: dict[str, Any]
) -> str:
    """Advance ACTIVE/REVOKED state only from the exact pointer just read."""
    import admin_safety_store as store
    from delegated_delivery_safety import DeliverySafetyError

    raw = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    try:
        if store._uses_gcs_backend():
            blob = store._get_gcs_bucket().blob(f"{store.SAFETY_PREFIX}/{_CURRENT_KEY}")
            try:
                blob.upload_from_string(
                    raw,
                    content_type="application/json",
                    if_generation_match=int(expected_generation),
                )
            except Exception as exc:
                if getattr(exc, "code", None) in (409, 412) or exc.__class__.__name__ in {
                    "Conflict",
                    "PreconditionFailed",
                }:
                    raise DeliverySafetyError(
                        "ADMIN_BETA_DELEGATION_STATE_CONFLICT"
                    ) from exc
                raise
            blob.reload()
            return str(blob.generation or "")

        # The local backend is test/development only. A file lock gives it the
        # same compare-and-swap semantics as the GCS generation precondition.
        import fcntl

        path = store._local_path(_CURRENT_KEY)
        lock_path = store._local_path("admin_beta_delegation/current.lock")
        with lock_path.open("a+", encoding="utf-8") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            if path.is_file():
                current_raw = path.read_text(encoding="utf-8")
                current_generation = hashlib.sha256(
                    current_raw.encode("utf-8")
                ).hexdigest()
            else:
                current_generation = "0"
            if current_generation != expected_generation:
                raise DeliverySafetyError("ADMIN_BETA_DELEGATION_STATE_CONFLICT")
            temp = path.with_suffix(".json.tmp")
            temp.write_text(raw, encoding="utf-8")
            os.replace(temp, path)
            return hashlib.sha256(raw.encode("utf-8")).hexdigest()
    except DeliverySafetyError:
        raise
    except Exception as exc:
        raise DeliverySafetyError("ADMIN_BETA_DELEGATION_STATE_UNAVAILABLE") from exc


def _current_cohort(*, expected_count: int) -> dict[str, Any]:
    from admin_store import _is_valid_email, load_beta_recipient_config
    from delegated_delivery_safety import DeliverySafetyError
    from email_sender import parse_customer_to_addrs

    if expected_count != DEFAULT_RECIPIENT_COUNT:
        raise DeliverySafetyError("ADMIN_BETA_EXACT_COHORT_MISMATCH")
    cfg = load_beta_recipient_config()
    if cfg.get("load_ok") is not True:
        raise DeliverySafetyError("ADMIN_BETA_RECIPIENT_CONFIG_UNAVAILABLE")
    env_recipients = [
        str(value).strip().lower() for value in parse_customer_to_addrs() if str(value).strip()
    ]
    if env_recipients:
        # This grant never inherits hidden environment recipients.
        raise DeliverySafetyError("ADMIN_BETA_ENV_RECIPIENTS_NOT_AUTHORIZED")
    disabled = sorted(
        {str(value).strip().lower() for value in cfg.get("disabled_recipients") or [] if str(value).strip()}
    )
    if disabled:
        raise DeliverySafetyError("ADMIN_BETA_DISABLED_RECIPIENT_PRESENT")
    recipients = [
        str(value).strip().lower()
        for value in cfg.get("recipients") or []
        if str(value).strip()
    ]
    if any(not _is_valid_email(value) for value in recipients):
        raise DeliverySafetyError("ADMIN_BETA_RECIPIENT_CONFIG_INVALID")
    if (
        expected_count < 1
        or len(recipients) != expected_count
        or len(set(recipients)) != len(recipients)
    ):
        raise DeliverySafetyError("ADMIN_BETA_EXACT_COHORT_MISMATCH")
    version = int(cfg.get("version") or 1)
    identity = {
        "env_recipients": [],
        "admin_recipients": recipients,
        "disabled_recipients": disabled,
        "final_recipients": recipients,
        "admin_version": version,
    }
    return {
        "recipient_count": len(recipients),
        "recipients": recipients,
        "recipients_sha256": _digest(recipients),
        "recipient_configuration_version": f"env+admin:v{version}",
        "recipient_configuration_hash": _digest(identity),
        "suppression_policy": SUPPRESSION_POLICY,
    }


def activate_admin_beta_delegation(
    *,
    products: Iterable[str],
    operator_id: str,
    expected_count: int = DEFAULT_RECIPIENT_COUNT,
    now: dt.datetime | None = None,
) -> dict[str, Any]:
    """Persist one exact, revocable grant; normal publications need no new click."""
    from admin_safety_store import _create_json_once, _read_json
    from delegated_delivery_safety import DeliverySafetyError

    if not str(operator_id or "").strip():
        raise DeliverySafetyError("ADMIN_BETA_DELEGATION_OPERATOR_REQUIRED")
    instant = now or dt.datetime.now(KST)
    if instant.tzinfo is None:
        raise DeliverySafetyError("AWARE_CLOCK_REQUIRED")
    if int(expected_count) != DEFAULT_RECIPIENT_COUNT:
        raise DeliverySafetyError("ADMIN_BETA_EXACT_COHORT_MISMATCH")
    cohort = _current_cohort(expected_count=DEFAULT_RECIPIENT_COUNT)
    payload = {
        "schema": DELEGATION_SCHEMA,
        "policy_version": DELEGATION_POLICY,
        "authority": DELEGATION_AUTHORITY,
        "status": "ACTIVE",
        "products": _normalised_products(products),
        "operator_id": str(operator_id).strip(),
        "activated_at": instant.astimezone(dt.timezone.utc).isoformat(),
        **cohort,
    }
    payload["grant_sha256"] = _digest(payload)
    payload["grant_id"] = "admin_beta_grant_" + payload["grant_sha256"]
    key = f"admin_beta_delegation/grants/{payload['grant_id']}.json"
    if not _create_json_once(key, payload) and _read_json(key) != payload:
        raise DeliverySafetyError("ADMIN_BETA_DELEGATION_GRANT_CONFLICT")
    _, expected_generation = _read_current_with_generation()
    _compare_and_swap_current(
        expected_generation,
        {
            "schema": DELEGATION_SCHEMA,
            "status": "ACTIVE",
            "grant_id": payload["grant_id"],
            "grant_sha256": payload["grant_sha256"],
        },
    )
    return payload


def revoke_admin_beta_delegation(
    *, operator_id: str, reason: str, now: dt.datetime | None = None
) -> dict[str, Any]:
    from delegated_delivery_safety import DeliverySafetyError

    pointer, expected_generation = _read_current_with_generation()
    pointer = pointer or {}
    if not str(operator_id or "").strip() or not str(reason or "").strip():
        raise DeliverySafetyError("ADMIN_BETA_DELEGATION_REVOCATION_EVIDENCE_REQUIRED")
    instant = now or dt.datetime.now(KST)
    record = {
        "schema": DELEGATION_SCHEMA,
        "status": "REVOKED",
        "grant_id": str(pointer.get("grant_id") or ""),
        "operator_id": str(operator_id).strip(),
        "reason": str(reason).strip()[:240],
        "revoked_at": instant.astimezone(dt.timezone.utc).isoformat(),
    }
    _compare_and_swap_current(expected_generation, record)
    return record


def load_active_admin_beta_delegation() -> dict[str, Any]:
    from admin_safety_store import _read_json
    from delegated_delivery_safety import DeliverySafetyError

    pointer, pointer_generation = _read_current_with_generation()
    if not isinstance(pointer, dict) or pointer.get("status") != "ACTIVE":
        raise DeliverySafetyError("ADMIN_BETA_DELEGATION_NOT_ACTIVE")
    grant_id = str(pointer.get("grant_id") or "")
    if not re.fullmatch(r"admin_beta_grant_[a-f0-9]{64}", grant_id):
        raise DeliverySafetyError("ADMIN_BETA_DELEGATION_GRANT_INVALID")
    grant = _read_json(f"admin_beta_delegation/grants/{grant_id}.json")
    if not isinstance(grant, dict):
        raise DeliverySafetyError("ADMIN_BETA_DELEGATION_GRANT_UNAVAILABLE")
    core = {key: value for key, value in grant.items() if key not in {"grant_id", "grant_sha256"}}
    digest = _digest(core)
    if (
        grant.get("schema") != DELEGATION_SCHEMA
        or grant.get("policy_version") != DELEGATION_POLICY
        or grant.get("authority") != DELEGATION_AUTHORITY
        or grant.get("suppression_policy") != SUPPRESSION_POLICY
        or grant.get("status") != "ACTIVE"
        or grant_id != "admin_beta_grant_" + digest
        or grant.get("grant_sha256") != digest
        or pointer.get("grant_sha256") != digest
        or _normalised_products(grant.get("products") or []) != grant.get("products")
    ):
        raise DeliverySafetyError("ADMIN_BETA_DELEGATION_GRANT_INVALID")
    if int(grant.get("recipient_count") or 0) != DEFAULT_RECIPIENT_COUNT:
        raise DeliverySafetyError("ADMIN_BETA_EXACT_COHORT_MISMATCH")
    current = _current_cohort(expected_count=DEFAULT_RECIPIENT_COUNT)
    for field in (
        "recipient_count",
        "recipients",
        "recipients_sha256",
        "recipient_configuration_version",
        "recipient_configuration_hash",
        "suppression_policy",
    ):
        if current.get(field) != grant.get(field):
            raise DeliverySafetyError("ADMIN_BETA_DELEGATION_COHORT_CHANGED")
    final_pointer, final_generation = _read_current_with_generation()
    if final_pointer != pointer or final_generation != pointer_generation:
        raise DeliverySafetyError("ADMIN_BETA_DELEGATION_STATE_CHANGED")
    result = dict(grant)
    result["_pointer_generation"] = pointer_generation
    return result


class AdminBetaRecipientAuthority:
    """Recipient authority backed by the operator's exact beta-cohort grant."""

    def prepare(self, mode: str, publication_date: Any, now: dt.datetime) -> dict[str, Any]:
        from admin_safety_store import _create_json_once, _read_json
        from delegated_delivery_safety import (
            DeliverySafetyError,
            PRODUCTS,
            SCHEMA,
            _day,
            _digest as plan_digest,
            _instant,
        )

        grant = load_active_admin_beta_delegation()
        if mode not in grant["products"] or mode not in PRODUCTS:
            raise DeliverySafetyError("ADMIN_BETA_DELEGATION_PRODUCT_NOT_AUTHORIZED")
        instant = _instant(now)
        day = _day(publication_date)
        if day != instant.astimezone(KST).date():
            raise DeliverySafetyError("STALE_PUBLICATION")
        recipients = []
        for email in grant["recipients"]:
            identity = hashlib.sha256(email.encode("utf-8")).hexdigest()
            recipients.append(
                {
                    "account_id": "admin-beta-account-" + identity,
                    "snapshot_id": "admin-beta-snapshot-" + identity,
                    "subscription_id": "admin-beta-delegation-" + grant["grant_sha256"],
                    "delivery_email": email,
                    "delivery_email_id": "admin-beta-email-" + identity,
                    "entitlement_id": grant["grant_id"],
                }
            )
        plan = {
            "schema": SCHEMA,
            "product_code": PRODUCTS[mode],
            "publication_date": day.isoformat(),
            "frozen_at": instant.isoformat(),
            "recipients": recipients,
            "excluded_reason_counts": {},
            "authority": DELEGATION_AUTHORITY,
            "authority_policy_version": DELEGATION_POLICY,
            "suppression_policy": SUPPRESSION_POLICY,
            "authority_grant_id": grant["grant_id"],
            "authority_pointer_generation": grant["_pointer_generation"],
            "recipient_configuration_version": grant["recipient_configuration_version"],
            "recipient_configuration_hash": grant["recipient_configuration_hash"],
        }
        plan["sha256"] = plan_digest(plan)
        plan["plan_id"] = "recipient_" + plan["sha256"]
        key = f"delegated_recipient_plans/{plan['plan_id']}.json"
        if not _create_json_once(key, plan) and _read_json(key) != plan:
            raise DeliverySafetyError("RECIPIENT_PLAN_STORE_CONFLICT")
        return plan

    def revalidate(self, plan: dict[str, Any], now: dt.datetime) -> bool:
        from delegated_delivery_safety import (
            DeliverySafetyError,
            PRODUCTS,
            _instant,
            load_recipient_plan,
        )

        current_plan = load_recipient_plan(
            plan.get("plan_id"), expected_sha256=plan.get("sha256")
        )
        grant = load_active_admin_beta_delegation()
        current_day = _instant(now).astimezone(KST).date().isoformat()
        authorized_products = {PRODUCTS[mode] for mode in grant["products"]}
        if (
            current_plan.get("authority") != DELEGATION_AUTHORITY
            or current_plan.get("authority_policy_version") != DELEGATION_POLICY
            or current_plan.get("suppression_policy") != SUPPRESSION_POLICY
            or current_plan.get("authority_grant_id") != grant.get("grant_id")
            or current_plan.get("authority_pointer_generation")
            != grant.get("_pointer_generation")
            or current_plan.get("product_code") not in authorized_products
            or current_plan.get("publication_date") != current_day
            or current_plan.get("recipient_configuration_hash")
            != grant.get("recipient_configuration_hash")
            or current_plan.get("recipient_configuration_version")
            != grant.get("recipient_configuration_version")
            or [row.get("delivery_email") for row in current_plan.get("recipients") or []]
            != grant.get("recipients")
        ):
            raise DeliverySafetyError("ADMIN_BETA_DELEGATION_PLAN_CHANGED")
        return True
