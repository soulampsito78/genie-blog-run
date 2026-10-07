"""Authenticated beta edits: durable intent, pointer fence, config CAS, carry.

Not a cross-object transaction. EDITING fails closed at every existing send
boundary. Only an already authenticated, immutable intent can be reconciled;
reading an ordinary current list can never create a new authorization.
"""
from __future__ import annotations

import datetime as dt
import re
import secrets
from typing import Any

import admin_beta_delegation as delegation
import admin_safety_store as store
import admin_store
from delegated_delivery_safety import DeliverySafetyError

SCHEMA = "admin-beta-edit-v1"
PREFIX = "admin_beta_edits"
_OP = re.compile(r"^abe_[a-f0-9]{32}$")


def config_identity(cfg: dict[str, Any]) -> str:
    return delegation._digest({k: cfg.get(k) for k in (
        "recipients", "disabled_recipients", "version", "updated_at", "updated_by",
        "last_edit_operation_id",
    )})


def form_context(action: str, email: str = "") -> dict[str, Any]:
    """Read-only context. The HTTP layer must sign it for this admin session."""
    cfg = admin_store.load_beta_recipient_config()
    if cfg.get("load_ok") is not True:
        raise DeliverySafetyError("ADMIN_BETA_RECIPIENT_CONFIG_UNAVAILABLE")
    pointer, generation = delegation._read_current_with_generation()
    if pointer and pointer.get("status") == "EDITING":
        raise DeliverySafetyError("ADMIN_BETA_EDIT_PENDING")
    return {"schema": SCHEMA, "operation_id": "abe_" + secrets.token_hex(16),
            "action": action, "email": email, "config_generation": cfg["_storage_generation"],
            "config_sha256": config_identity(cfg), "pointer_generation": generation}


def _key(op: str, kind: str) -> str:
    if not _OP.fullmatch(str(op)):
        raise DeliverySafetyError("ADMIN_BETA_EDIT_ID_INVALID")
    return f"{PREFIX}/{op}/{kind}.json"


def _immutable(key: str, value: dict[str, Any]) -> dict[str, Any]:
    # Lost upload response is reconciled by fresh read, not assumed not-written.
    try:
        store._create_json_once(key, value)
    except Exception:
        existing = store._read_json(key)
        if existing != value:
            raise
    existing = store._read_json(key)
    if existing != value:
        raise DeliverySafetyError("ADMIN_BETA_EDIT_IDENTITY_CONFLICT")
    return existing


def _intent(op: str) -> dict[str, Any]:
    value = store._read_json(_key(op, "intent"))
    if not isinstance(value, dict):
        raise DeliverySafetyError("ADMIN_BETA_EDIT_INTENT_UNAVAILABLE")
    core = {k: v for k, v in value.items() if k != "intent_sha256"}
    if (value.get("schema") != SCHEMA or value.get("operation_id") != op
            or not str(value.get("operator_id") or "").startswith("owner_session:")
            or value.get("intent_sha256") != delegation._digest(core)):
        raise DeliverySafetyError("ADMIN_BETA_EDIT_INTENT_INVALID")
    return value


def edit_recipient(*, context: dict[str, Any], action: str, email: str,
                   operator_id: str, now: dt.datetime | None = None) -> dict[str, Any]:
    """Called only after authenticated HTTP + CSRF + context HMAC validation."""
    if not str(operator_id).startswith("owner_session:"):
        raise DeliverySafetyError("ADMIN_BETA_EDIT_OPERATOR_REQUIRED")
    op = str(context.get("operation_id") or "")
    key = _key(op, "intent")
    target = str(email).strip().lower()
    if context.get("schema") != SCHEMA or action not in {"add", "remove"} or context.get("action") != action:
        raise DeliverySafetyError("ADMIN_BETA_EDIT_CONTEXT_INVALID")
    if action == "remove" and context.get("email") != target:
        raise DeliverySafetyError("ADMIN_BETA_EDIT_CONTEXT_INVALID")
    previous = store._read_json(key)
    if previous is not None:
        previous = _intent(op)
        if (previous["action"], previous["email"], previous["operator_id"], previous["context"]) != (action, target, operator_id, context):
            raise DeliverySafetyError("ADMIN_BETA_EDIT_IDENTITY_CONFLICT")
        return resume_edit(op)
    cfg = admin_store.load_beta_recipient_config()
    pointer, generation = delegation._read_current_with_generation()
    if (cfg.get("load_ok") is not True or context["config_generation"] != cfg["_storage_generation"]
            or context["config_sha256"] != config_identity(cfg) or context["pointer_generation"] != generation):
        raise DeliverySafetyError("ADMIN_BETA_EDIT_STALE_FORM")
    if pointer and pointer.get("status") == "EDITING":
        raise DeliverySafetyError("ADMIN_BETA_EDIT_PENDING")
    if not admin_store._is_valid_email(target):
        raise DeliverySafetyError("ADMIN_BETA_EDIT_INVALID_EMAIL")
    recipients = list(cfg["recipients"])
    if action == "add":
        if target in recipients:
            raise DeliverySafetyError("ADMIN_BETA_EDIT_ALREADY_EXISTS")
        recipients.append(target)
    else:
        if target not in recipients:
            raise DeliverySafetyError("ADMIN_BETA_EDIT_NOT_FOUND")
        recipients.remove(target)
    if len(recipients) > delegation.MAX_BETA_RECIPIENT_COUNT or len(set(recipients)) != len(recipients):
        raise DeliverySafetyError("ADMIN_BETA_RECIPIENT_CAPACITY_INVALID")
    if any(not admin_store._is_valid_email(x) for x in recipients):
        raise DeliverySafetyError("ADMIN_BETA_RECIPIENT_CONFIG_INVALID")
    parent = None
    reason = "ADMIN_BETA_DELEGATION_NOT_ACTIVE"
    if pointer and pointer.get("status") == "ACTIVE":
        try:
            loaded = delegation.load_active_admin_beta_delegation(reconcile_edits=False)
            if loaded["_pointer_generation"] != generation:
                raise DeliverySafetyError("ADMIN_BETA_DELEGATION_STATE_CHANGED")
            parent = {k: v for k, v in loaded.items() if not k.startswith("_")}
            reason = ""
        except DeliverySafetyError as exc:
            reason = str(exc)
    # Capture a deterministic write, not fresh wall-clock fields on each retry.
    instant = now or dt.datetime.now(delegation.KST)
    if instant.tzinfo is None:
        raise DeliverySafetyError("AWARE_CLOCK_REQUIRED")
    updated = {"recipients": recipients, "disabled_recipients": list(cfg["disabled_recipients"]),
               "version": int(cfg["version"]) + 1, "updated_at": instant.isoformat(),
               "updated_by": operator_id, "last_edit_operation_id": op}
    value = {"schema": SCHEMA, "operation_id": op, "operator_id": operator_id,
             "action": action, "email": target, "context": context, "old_config": cfg,
             "new_config": updated, "old_pointer": pointer, "parent_grant": parent,
             "no_carry_reason": reason, "created_at": instant.isoformat()}
    value["intent_sha256"] = delegation._digest(value)
    _immutable(key, value)
    return resume_edit(op)


def _finish(intent: dict[str, Any], saved: bool | None, connection: str, reason: str = "") -> dict[str, Any]:
    return _immutable(_key(intent["operation_id"], "result"), {
        "schema": SCHEMA, "operation_id": intent["operation_id"],
        "intent_sha256": intent["intent_sha256"], "config_saved": saved,
        "connection": connection, "reason": reason,
        "new_config_sha256": config_identity(intent["new_config"]),
    })


def resume_edit(op: str) -> dict[str, Any]:
    """Resume only this stored authenticated intent; no new recipient input."""
    intent = _intent(op)
    result = store._read_json(_key(op, "result"))
    if result is not None:
        if result.get("intent_sha256") != intent["intent_sha256"]:
            raise DeliverySafetyError("ADMIN_BETA_EDIT_IDENTITY_CONFLICT")
        return result
    fence = {"schema": delegation.DELEGATION_SCHEMA, "status": "EDITING",
             "edit_operation_id": op, "edit_intent_sha256": intent["intent_sha256"],
             "grant_id": (intent["old_pointer"] or {}).get("grant_id", "")}
    pointer, generation = delegation._read_current_with_generation()
    cfg = admin_store.load_beta_recipient_config()
    if cfg.get("load_ok") is not True:
        raise DeliverySafetyError("ADMIN_BETA_RECIPIENT_CONFIG_UNAVAILABLE")
    saved = config_identity(cfg) == config_identity(intent["new_config"])
    applied = store._read_json(_key(op, "applied"))
    if applied is not None and applied != {
        "operation_id": op, "intent_sha256": intent["intent_sha256"],
        "new_config_sha256": config_identity(intent["new_config"]),
    }:
        raise DeliverySafetyError("ADMIN_BETA_EDIT_IDENTITY_CONFLICT")
    owns = pointer == fence
    if (pointer == intent["old_pointer"] and generation == intent["context"]["pointer_generation"]):
        if cfg["_storage_generation"] != intent["old_config"]["_storage_generation"] or config_identity(cfg) != config_identity(intent["old_config"]):
            return _finish(intent, saved, "CONFLICT", "ADMIN_BETA_EDIT_CONFIG_CHANGED")
        try:
            delegation._compare_and_swap_current(generation, fence)
        except Exception:
            current, _ = delegation._read_current_with_generation()
            if current != fence:
                raise
        pointer, generation = delegation._read_current_with_generation()
        owns = pointer == fence
    if not owns:
        # A final ACTIVE write may have succeeded before its response/result
        # record was lost. It is never redone or used to resurrect a revocation.
        if (saved and pointer and pointer.get("status") == "ACTIVE"
                and pointer.get("edit_operation_id") == op
                and pointer.get("edit_intent_sha256") == intent["intent_sha256"]):
            active = delegation.load_active_admin_beta_delegation(reconcile_edits=False)
            if active.get("edit_operation_id") == op:
                return _finish(intent, True, "LINKED")
        if (saved and pointer and pointer.get("status") in {"STOPPED", "REVOKED"}
                and pointer.get("edit_operation_id") == op):
            return _finish(intent, True, "STOPPED", "ADMIN_BETA_DELEGATION_NOT_ACTIVE")
        if applied is not None:
            # Historical application is not undone by a newer valid edit.
            # No attempt is made to restore or re-link the old payload.
            return _finish(intent, True, "SUPERSEDED", "ADMIN_BETA_EDIT_POINTER_CHANGED")
        unchanged = config_identity(cfg) == config_identity(intent["old_config"]) and cfg["_storage_generation"] == intent["old_config"]["_storage_generation"]
        return _finish(intent, True if saved else (False if unchanged else None),
                       "CANCELLED" if saved or unchanged else "UNKNOWN", "ADMIN_BETA_EDIT_POINTER_CHANGED")
    if not saved:
        if cfg["_storage_generation"] != intent["old_config"]["_storage_generation"] or config_identity(cfg) != config_identity(intent["old_config"]):
            # Never restore old recipients or overwrite another writer.
            stopped = {**fence, "status": "STOPPED", "reason": "ADMIN_BETA_EDIT_CONFIG_CHANGED"}
            delegation._compare_and_swap_current(generation, stopped)
            return _finish(intent, False, "CONFLICT", stopped["reason"])
        new = intent["new_config"]
        try:
            admin_store.save_beta_recipient_config(new["recipients"], disabled_recipients=new["disabled_recipients"],
                version=new["version"], updated_by=new["updated_by"], updated_at=new["updated_at"],
                operation_id=op, expected_generation=cfg["_storage_generation"])
        except Exception:
            current = admin_store.load_beta_recipient_config()
            if current.get("load_ok") is not True or config_identity(current) != config_identity(new):
                raise
        cfg = admin_store.load_beta_recipient_config()
        saved = cfg.get("load_ok") is True and config_identity(cfg) == config_identity(new)
        if not saved:
            raise DeliverySafetyError("ADMIN_BETA_EDIT_CONFIG_CHANGED")
    _immutable(_key(op, "applied"), {"operation_id": op,
        "intent_sha256": intent["intent_sha256"],
        "new_config_sha256": config_identity(intent["new_config"])})
    # Re-read the fence after config commit. A concurrent revoke wins; never
    # retry against its newer generation or change its state back to ACTIVE.
    pointer, generation = delegation._read_current_with_generation()
    if pointer != fence:
        return _finish(intent, True, "CANCELLED", "ADMIN_BETA_EDIT_POINTER_CHANGED")
    parent = intent["parent_grant"]
    if not parent or not intent["new_config"]["recipients"]:
        status = "REVOKED" if (intent["old_pointer"] or {}).get("status") == "REVOKED" else "STOPPED"
        stopped = {**fence, "status": status, "reason": intent["no_carry_reason"] or "EMPTY_COHORT"}
        delegation._compare_and_swap_current(generation, stopped)
        return _finish(intent, True, "STOPPED", stopped["reason"])
    # Same current-cohort validation as every final send: no env recipients,
    # no disabled bypass, exact version/count/hash, unchanged product scope.
    cohort = delegation._current_cohort()
    if config_identity(admin_store.load_beta_recipient_config()) != config_identity(intent["new_config"]):
        raise DeliverySafetyError("ADMIN_BETA_EDIT_CONFIG_CHANGED")
    grant = {"schema": delegation.DELEGATION_SCHEMA, "policy_version": parent["policy_version"],
             "authority": delegation.DELEGATION_AUTHORITY, "status": "ACTIVE",
             "products": delegation._normalised_products(parent["products"]),
             "operator_id": intent["operator_id"], "activated_at": intent["created_at"],
             "parent_grant_id": parent["grant_id"], "edit_operation_id": op,
             "edit_intent_sha256": intent["intent_sha256"], **cohort}
    grant["grant_sha256"] = delegation._digest(grant)
    grant["grant_id"] = "admin_beta_grant_" + grant["grant_sha256"]
    _immutable(f"admin_beta_delegation/grants/{grant['grant_id']}.json", grant)
    active_pointer = {"schema": delegation.DELEGATION_SCHEMA, "status": "ACTIVE",
                      "grant_id": grant["grant_id"], "grant_sha256": grant["grant_sha256"],
                      "edit_operation_id": op, "edit_intent_sha256": intent["intent_sha256"]}
    try:
        delegation._compare_and_swap_current(generation, active_pointer)
    except Exception:
        current, _ = delegation._read_current_with_generation()
        if current != active_pointer:
            raise
    active = delegation.load_active_admin_beta_delegation(reconcile_edits=False)
    if active["grant_id"] != grant["grant_id"]:
        raise DeliverySafetyError("ADMIN_BETA_EDIT_POINTER_CHANGED")
    return _finish(intent, True, "LINKED")


def reconcile_pending_edit() -> dict[str, Any] | None:
    """Authenticated management page only: recover its existing EDITING intent.

    Never looks for orphan intents and never acquires a fence for a new edit.
    A lost final response can be reconciled from the pointer's existing op too.
    """
    pointer, _ = delegation._read_current_with_generation()
    if not pointer or not pointer.get("edit_operation_id"):
        return None
    op = pointer["edit_operation_id"]
    intent = _intent(op)
    if pointer.get("edit_intent_sha256") != intent["intent_sha256"]:
        raise DeliverySafetyError("ADMIN_BETA_EDIT_IDENTITY_CONFLICT")
    result = store._read_json(_key(op, "result"))
    if result is not None:
        return None
    return resume_edit(op)
