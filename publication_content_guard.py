"""Serialize original-copy edits with both existing customer-submit paths.

A completed operation may clean up its durable mutex. A running/unknown one
never expires into permission to repeat an external effect. This is a technical
mutex, not an Owner HOLD, approval, retry allowance, or publication attempt.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from functools import wraps
from hashlib import sha256
import json
import secrets

_HELD = ContextVar("publication_content_guards", default={})


class ContentMutationBusy(RuntimeError):
    pass


def _key(product, day):
    from delegated_delivery_safety import PRODUCTS
    from datetime import date
    if product not in PRODUCTS or date.fromisoformat(day).isoformat() != day:
        raise ValueError("invalid_content_guard_publication")
    return "publication_content_guards/" + sha256((product + "\n" + day).encode()).hexdigest() + ".json"


@contextmanager
def _local_mutex(key):
    import admin_safety_store as store
    if store._uses_gcs_backend():
        yield
        return
    import fcntl
    with store._local_path(key + ".mutex").open("a+b") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def _delete_matching(key, operation_id, *, completed_only=False):
    import admin_safety_store as store
    if store._uses_gcs_backend():
        from google.api_core.exceptions import NotFound, PreconditionFailed
        blob = store._get_gcs_bucket().blob(f"{store.SAFETY_PREFIX}/{key}")
        try:
            blob.reload()
            generation = blob.generation
            row = json.loads(blob.download_as_bytes(if_generation_match=generation))
            if row.get("operation_id") != operation_id or (completed_only and row.get("state") != "COMPLETED"):
                return False
            blob.delete(if_generation_match=generation)
            return True
        except (NotFound, PreconditionFailed):
            return False
    row = store._read_json(key)
    if not row or row.get("operation_id") != operation_id or (completed_only and row.get("state") != "COMPLETED"):
        return False
    store._local_path(key).unlink()
    return True


@contextmanager
def publication_content_guard(product, day, *, run_id, action):
    import admin_safety_store as store
    key = _key(product, day)
    held = _HELD.get()
    if key in held:
        yield held[key]
        return
    operation_id = secrets.token_hex(20)
    row = {"operation_id": operation_id, "run_id": run_id, "action": action,
           "state": "RUNNING", "created_at": datetime.now(timezone.utc).isoformat()}
    with _local_mutex(key):
        old = store._read_json(key)
        if old and old.get("state") == "COMPLETED":
            _delete_matching(key, old.get("operation_id"), completed_only=True)
        if not store._create_json_once(key, row):
            raise ContentMutationBusy("PUBLICATION_CONTENT_OPERATION_RUNNING_OR_UNKNOWN")
    context = _HELD.set({**held, key: operation_id})
    try:
        yield operation_id
    finally:
        _HELD.reset(context)
        # No later caller can acquire until completion is recorded/deleted.
        # If recording/deletion fails, preserve the durable lock for diagnosis.
        with _local_mutex(key):
            current = store._read_json(key)
            if current and current.get("operation_id") == operation_id:
                store._write_json(key, {**current, "state": "COMPLETED",
                                       "finished_at": datetime.now(timezone.utc).isoformat()})
                _delete_matching(key, operation_id, completed_only=True)


def serialize_owner_submission(function):
    """Keep the existing public owner-submit signature and result contract."""
    @wraps(function)
    def wrapped(run_id, *args, **kwargs):
        from admin_store import load_run_artifact
        meta = load_run_artifact(run_id)
        if not meta or not meta.get("target_date"):
            return function(run_id, *args, **kwargs)
        try:
            with publication_content_guard(meta.get("mode"), meta["target_date"],
                                           run_id=run_id, action="owner_customer_submit"):
                return function(run_id, *args, **kwargs)
        except ContentMutationBusy as exc:
            return None, str(exc)
    return wrapped
