"""Literal, versioned original-copy correction. No generation or customer send.

Immutable HTML revisions retain the received original. One conditional metadata
write selects the current revision; old received MIME/reviews then cease to
match. Both customer-submit paths share this operation's publication mutex.
"""
from datetime import datetime
from hashlib import sha256
from html import escape, unescape
import json
import re
from zoneinfo import ZoneInfo

MAX_PATCHES = 40
MAX_REPLACEMENT_CHARS = 12_000


class CopyEditError(ValueError):
    pass


def _digest(value):
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def revision_key(run_id, revision_id):
    import admin_store as store
    if not store.validate_run_id(run_id) or not re.fullmatch(r"[0-9a-f]{64}", str(revision_id)):
        raise CopyEditError("INVALID_COPY_REVISION")
    return store.gcs_artifact_object_key(run_id, f".copy.{revision_id}.email.html")


def _local_revision_path(run_id, revision_id):
    import admin_store as store
    revision_key(run_id, revision_id)
    return store.artifact_email_path(run_id).with_name(f"{run_id}.copy.{revision_id}.email.html")


def read_revision_html(meta):
    import admin_store as store
    row = meta.get("original_copy_revision") or {}
    run_id, identity = meta.get("run_id"), row.get("revision_id")
    key = revision_key(run_id, identity)
    if store._uses_gcs_backend():
        blob = store._get_gcs_bucket().blob(key)
        blob.reload()
        if not blob.size or blob.size > store.ADMIN_EMAIL_HTML_MAX_BYTES:
            raise CopyEditError("COPY_REVISION_SIZE_INVALID")
        raw = blob.download_as_bytes(if_generation_match=blob.generation)
    else:
        path = _local_revision_path(run_id, identity)
        if path.stat().st_size > store.ADMIN_EMAIL_HTML_MAX_BYTES:
            raise CopyEditError("COPY_REVISION_SIZE_INVALID")
        raw = path.read_bytes()
    if sha256(raw).hexdigest() != row.get("html_sha256"):
        raise CopyEditError("COPY_REVISION_HASH_MISMATCH")
    return raw.decode("utf-8")


def _put_revision_once(run_id, revision_id, text):
    import admin_store as store
    raw = text.encode("utf-8")
    if not raw or len(raw) > store.ADMIN_EMAIL_HTML_MAX_BYTES:
        raise CopyEditError("COPY_REVISION_SIZE_INVALID")
    if store._uses_gcs_backend():
        from google.api_core.exceptions import PreconditionFailed
        blob = store._get_gcs_bucket().blob(revision_key(run_id, revision_id))
        try:
            blob.upload_from_string(raw, content_type="text/html; charset=utf-8", if_generation_match=0)
        except PreconditionFailed:
            if blob.download_as_bytes() != raw:
                raise CopyEditError("COPY_REVISION_COLLISION")
    else:
        path = _local_revision_path(run_id, revision_id)
        try:
            with path.open("xb") as handle:
                handle.write(raw)
        except FileExistsError:
            if path.read_bytes() != raw:
                raise CopyEditError("COPY_REVISION_COLLISION")


def _eligible(meta, *, now):
    import admin_store as store
    from delegated_delivery_safety import PRODUCTS, _digest as publication_digest
    import admin_safety_store as safety
    if meta.get("mode") not in {"today_genie", "keysuri_global_tech", "keysuri_korea_tech"}:
        raise CopyEditError("COPY_EDIT_UNSUPPORTED_PRODUCT")
    if meta.get("target_date") != now.astimezone(ZoneInfo("Asia/Seoul")).date().isoformat():
        raise CopyEditError("COPY_EDIT_OUTSIDE_CURRENT_PUBLICATION_DATE")
    if meta.get("owner_review_status") not in {"pending_review", "reopened"}:
        raise CopyEditError("COPY_EDIT_OWNER_STATE_CONFLICT")
    if meta.get("customer_delivery_status") != "not_sent" or meta.get("customer_delivery_attempt_count"):
        raise CopyEditError("COPY_EDIT_CUSTOMER_ALREADY_ATTEMPTED")
    transition = store.run_delivery_transition(meta["run_id"])
    if transition.get("state") != "READY":
        raise CopyEditError("COPY_EDIT_DELIVERY_STATE_CONFLICT")
    if any(meta.get(k) for k in ("reissue_requested", "last_reissue_child_run_id", "superseded_by_run_id")):
        raise CopyEditError("COPY_EDIT_NOT_CURRENT_LEAF")
    if store.superseded_child_check(meta)[0]:
        raise CopyEditError("COPY_EDIT_LINEAGE_RECONCILIATION_REQUIRED")
    attempt = "publication_" + publication_digest([PRODUCTS[meta["mode"]], meta["target_date"]])
    for path in (f"publication_attempts/{attempt}.json", f"publication_outcomes/{attempt}.json"):
        if safety._read_json(path) is not None:
            raise CopyEditError("COPY_EDIT_PUBLICATION_ALREADY_ATTEMPTED")


def editable_segments(saved_html):
    """Text nodes only; scripts, styles, links/attributes and admin tail stay locked."""
    # Split preserves original markup byte-for-byte; replacements are escaped.
    # Skip attributes entirely and all source/review/footer controls.
    tokens = re.split(r'''(<!--.*?-->|<(?:[^<>"']|"[^"]*"|'[^']*')*>)''', saved_html, flags=re.S)
    in_unsafe = 0
    visible_index = 0
    result = []
    stopped = False
    for index, token in enumerate(tokens):
        if token.startswith("<"):
            tag = re.match(r"<\s*(/?)\s*([\w-]+)", token)
            if tag and tag[2].lower() in {"script", "style", "a", "code", "button", "select", "option"}:
                in_unsafe += -1 if tag[1] else 1
                in_unsafe = max(0, in_unsafe)
            continue
        text = unescape(token)
        if "운영자 검수 상태" in text:
            stopped = True
        if stopped or in_unsafe or not text.strip():
            continue
        # Publication number tables are sourced separately; this editor does
        # not alter canonical source observations or their rendered values.
        if re.fullmatch(r"[\s\d.,+%−–:/()-]+", text):
            continue
        result.append({"field_id": f"copy_{visible_index}", "token_index": index,
                       "text": text, "text_sha256": sha256(text.encode()).hexdigest()})
        visible_index += 1
    return tokens, result


def prepare_copy_edit(run_id, changes, *, expected_html_sha256, expected_meta_sha256, now=None):
    import admin_store as store
    now = now or datetime.now(ZoneInfo("Asia/Seoul"))
    meta = store.load_run_artifact(run_id, normalize=False)
    if not meta:
        raise CopyEditError("COPY_EDIT_RUN_NOT_FOUND")
    _eligible(meta, now=now)
    old = store.load_run_email_html(run_id) or ""
    if sha256(old.encode()).hexdigest() != expected_html_sha256 or _digest(meta) != expected_meta_sha256:
        raise CopyEditError("COPY_EDIT_BASE_CHANGED")
    if not isinstance(changes, list) or not 1 <= len(changes) <= MAX_PATCHES:
        raise CopyEditError("COPY_EDIT_CHANGE_COUNT_INVALID")
    tokens, fields = editable_segments(old)
    by_id = {f["field_id"]: f for f in fields}
    seen, actual = set(), []
    for change in changes:
        if not isinstance(change, dict) or change.get("field_id") not in by_id:
            raise CopyEditError("COPY_EDIT_UNKNOWN_FIELD")
        identity = change["field_id"]
        if identity in seen:
            raise CopyEditError("COPY_EDIT_DUPLICATE_FIELD")
        seen.add(identity)
        field = by_id[identity]
        replacement = change.get("replacement")
        if (change.get("before_sha256") != field["text_sha256"] or not isinstance(replacement, str)
                or len(replacement) > MAX_REPLACEMENT_CHARS or "\x00" in replacement):
            raise CopyEditError("COPY_EDIT_FIELD_CHANGED_OR_INVALID")
        if replacement == field["text"]:
            continue
        tokens[field["token_index"]] = escape(replacement, quote=False)
        actual.append({"field_id": identity, "before_sha256": field["text_sha256"],
                       "after_sha256": sha256(replacement.encode()).hexdigest()})
    if not actual:
        raise CopyEditError("COPY_EDIT_NO_CHANGE")
    edited = "".join(tokens)
    if len(edited.encode()) > store.ADMIN_EMAIL_HTML_MAX_BYTES:
        raise CopyEditError("COPY_REVISION_SIZE_INVALID")
    revision_id = _digest({"run_id": run_id, "base_html": expected_html_sha256,
                           "base_meta": expected_meta_sha256, "new_html": sha256(edited.encode()).hexdigest()})
    return {"run_id": run_id, "revision_id": revision_id, "request_sha256": _digest(changes), "before_html_sha256": expected_html_sha256,
            "before_meta_sha256": expected_meta_sha256, "html_sha256": sha256(edited.encode()).hexdigest(),
            "html": edited, "before_html": old, "meta": meta, "changes": actual}


def _commit_pointer(prepared, revision):
    import admin_store as store
    from publication_content_guard import _local_mutex
    run_id = prepared["run_id"]
    def updated(meta):
        if _digest(meta) != prepared["before_meta_sha256"]:
            raise CopyEditError("COPY_EDIT_BASE_CHANGED")
        changed = {**meta, "original_copy_revision": revision, "copy_review_required": True}
        changed["original_copy_revision"]["prior_review_projection"] = {
            key: meta[key] for key in ("delegated_review_id", "delegated_review_status", "delegated_candidate_sha256", "approval_source")
            if key in meta}
        for key in ("delegated_review_id", "delegated_candidate_sha256", "approval_source"):
            changed.pop(key, None)
        changed["delegated_review_status"] = "pending"
        return changed
    if store._uses_gcs_backend():
        from google.api_core.exceptions import PreconditionFailed
        blob = store._get_gcs_bucket().blob(store.gcs_json_object_key(run_id))
        blob.reload()
        generation = blob.generation
        meta = json.loads(blob.download_as_bytes(if_generation_match=generation))
        changed = updated(meta)
        try:
            blob.upload_from_string(json.dumps(changed, ensure_ascii=False, indent=2),
                                    content_type="application/json", if_generation_match=generation)
        except PreconditionFailed:
            raise CopyEditError("COPY_EDIT_BASE_CHANGED")
    else:
        # The shared publication mutex serializes all submit/edit paths; this
        # short file mutex also protects conditional metadata replacement.
        with _local_mutex(f"copy_metadata/{run_id}.json"):
            changed = updated(store._read_json_blob(run_id))
            path = store.artifact_json_path(run_id)
            temporary = path.with_suffix(".copy-tmp")
            temporary.write_text(json.dumps(changed, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(path)
    store._write_summary_blob(run_id, changed)
    return changed


def send_corrected_owner_review(saved_html, meta):
    """Use the existing owner transport, never customer recipients or a model."""
    from email_sender import send_genie_email, last_send_trace
    if meta["mode"] == "today_genie":
        from today_geenee_customer_delivery import resolve_today_genie_reusable_images, build_customer_final_subject
        parts = resolve_today_genie_reusable_images(meta).inline_parts
        subject = build_customer_final_subject(meta, saved_html)
    else:
        from keysuri_customer_delivery import resolve_keysuri_inline_jpeg_parts
        parts = resolve_keysuri_inline_jpeg_parts(saved_html, meta)
        subject = meta.get("email_subject") or "키수리 문구 교정 검수본"
    if not parts:
        raise CopyEditError("COPY_EDIT_EXISTING_IMAGES_UNAVAILABLE")
    ok = send_genie_email(saved_html, "[운영자 검토] " + subject,
                         inline_jpeg_parts=list(parts), attachment_jpeg_parts=[], allow_rich_delivery=True)
    trace = last_send_trace()
    if not ok or not trace.get("smtp_submission_completed") or trace.get("smtp_refused_recipient_count"):
        raise CopyEditError("COPY_EDIT_OWNER_MAIL_RECONCILE")
    return {"smtp_accepted": True, "smtp_accepted_recipient_count": trace.get("smtp_accepted_recipient_count")}


def apply_copy_edit(run_id, changes, *, expected_html_sha256, expected_meta_sha256,
                    actual_actor="ADMIN_SESSION", now=None):
    import admin_store as store
    import admin_safety_store as safety
    from publication_content_guard import publication_content_guard
    now = now or datetime.now(ZoneInfo("Asia/Seoul"))
    meta = store.load_run_artifact(run_id, normalize=False)
    if not meta:
        raise CopyEditError("COPY_EDIT_RUN_NOT_FOUND")
    if actual_actor not in {"ADMIN_SESSION", "CODEX"}:
        raise CopyEditError("COPY_EDIT_ACTOR_INVALID")
    with publication_content_guard(meta.get("mode"), meta.get("target_date"),
                                   run_id=run_id, action="original_copy_edit"):
        # A repeated browser POST must never resend the owner message.
        current = store.load_run_artifact(run_id, normalize=False)
        prior = current.get("original_copy_revision") or {}
        if prior.get("before_html_sha256") == expected_html_sha256 and prior.get("before_meta_sha256") == expected_meta_sha256:
            if prior.get("request_sha256") != _digest(changes):
                raise CopyEditError("COPY_EDIT_BASE_CHANGED")
            return _complete_owner_review(current, already_applied=True, now=now)
        prepared = prepare_copy_edit(run_id, changes, expected_html_sha256=expected_html_sha256,
                                     expected_meta_sha256=expected_meta_sha256, now=now)
        identity = prepared["revision_id"]
        revision = {k: prepared[k] for k in ("revision_id", "request_sha256", "before_html_sha256", "before_meta_sha256", "html_sha256", "changes")}
        revision.update(actual_actor=actual_actor, edited_at=now.isoformat(), model_calls=0, image_calls=0,
                        producer_qa_is_pre_edit=True, owner_mail_state="PENDING")
        # Store both immutable preimage and result before the one atomic pointer.
        _put_revision_once(run_id, prepared["before_html_sha256"], prepared["before_html"])
        _put_revision_once(run_id, identity, prepared["html"])
        record_key = f"original_copy_edits/{identity}.json"
        if not safety._create_json_once(record_key, {**revision, "run_id": run_id, "state": "PREPARED"}):
            existing = safety._read_json(record_key) or {}
            if (existing.get("state") != "PREPARED" or existing.get("run_id") != run_id
                    or any(existing.get(k) != revision[k] for k in ("html_sha256", "request_sha256", "before_meta_sha256"))):
                raise CopyEditError("COPY_EDIT_RECONCILIATION_REQUIRED")
        safety.append_operator_audit("original_copy_edit", operator_id=actual_actor, run_id=run_id,
                                     result="APPLYING_LITERAL_REVISION", metadata=revision)
        changed = _commit_pointer(prepared, revision)
        safety._write_json(record_key, {**revision, "run_id": run_id, "state": "APPLIED_OWNER_MAIL_PENDING"})
        return _complete_owner_review(changed, already_applied=False, now=now)


def _complete_owner_review(meta, *, already_applied, now):
    """Resume storage-only failures; an uncertain SMTP attempt is never repeated.

    Immutable accepted proof is written before the mutable UI projection. If
    projection fails, the next identical request repairs it without SMTP.
    """
    import admin_store as store
    import admin_safety_store as safety
    revision = meta["original_copy_revision"]
    run_id, identity = meta["run_id"], revision["revision_id"]
    claim_key = f"original_copy_owner_mail_attempts/{identity}.json"
    outcome_key = f"original_copy_owner_mail_outcomes/{identity}.json"
    accepted = safety._read_json(outcome_key)
    result = {"run_id": run_id, "revision_id": identity, "already_applied": already_applied,
              "model_calls": 0, "image_calls": 0}
    if not accepted:
        if safety._read_json(claim_key):
            return {**result, "owner_mail_state": "RECONCILE"}
        _eligible(meta, now=now)
        saved_html = read_revision_html(meta)
        claim = {"run_id": run_id, "revision_id": identity, "html_sha256": revision["html_sha256"],
                 "attempted_at": datetime.now(ZoneInfo("Asia/Seoul")).isoformat(), "state": "OUTCOME_UNKNOWN"}
        if not safety._create_json_once(claim_key, claim):
            return {**result, "owner_mail_state": "RECONCILE"}
        try:
            evidence = send_corrected_owner_review(saved_html, meta)
        except Exception as exc:
            raise CopyEditError("COPY_EDIT_OWNER_MAIL_RECONCILE") from exc
        accepted = {**claim, **evidence, "state": "SMTP_ACCEPTED",
                    "accepted_at": datetime.now(ZoneInfo("Asia/Seoul")).isoformat()}
        if not safety._create_json_once(outcome_key, accepted):
            raise CopyEditError("COPY_EDIT_OWNER_MAIL_RECONCILE")
    if (accepted.get("run_id") != run_id or accepted.get("html_sha256") != revision["html_sha256"]
            or accepted.get("state") != "SMTP_ACCEPTED"):
        raise CopyEditError("COPY_EDIT_OWNER_MAIL_RECONCILE")
    if revision.get("owner_mail_state") != "SMTP_ACCEPTED":
        def stamp(row):
            if (row.get("original_copy_revision") or {}).get("revision_id") != identity:
                raise CopyEditError("COPY_EDIT_BASE_CHANGED")
            row["original_copy_revision"]["owner_mail_state"] = "SMTP_ACCEPTED"
            row["owner_email_smtp_attempted"] = True
            row["owner_email_delivery_status"] = "smtp_accepted"
        store.update_run_artifact(run_id, stamp)
    safety._write_json(f"original_copy_edits/{identity}.json",
                       {**revision, "run_id": run_id, "state": "OWNER_MAIL_ACCEPTED"})
    return {**result, "owner_mail_state": "SMTP_ACCEPTED"}
