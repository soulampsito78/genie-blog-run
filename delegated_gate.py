"""Staged authenticated second-pass runner; OFF until explicitly configured.

No public route, scheduler, credential, or IAM change is installed by this file.
The event body is never an authoritative candidate or a recipient list. A trusted
server loader rebuilds those from artifacts, received-mail evidence and the
recipient authority. HMAC authenticates the configured runner, not the truth of
its editorial judgment or its self-reported model name.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Mapping

from delegated_review import evaluate_shadow_review, POLICY_VERSION as SHADOW_POLICY
from customer_review_confirmation import DELEGATED_REVIEW_TEXT, DELEGATED_WORK_REVIEW

POLICY_VERSION = "genie-keesuri-second-pass-v2"
REQUIRED_CHECKS = frozenset({"content", "sources", "images", "render", "customer_render", "run_identity", "delivery_readiness"})
VERDICTS = frozenset({"PASS", "HOLD_ANOMALY", "HOLD_INCOMPLETE", "REVIEW_UNAVAILABLE", "STATE_CONFLICT"})
_HEX = re.compile(r"^[a-f0-9]{64}$")
_EVENT = re.compile(r"^[A-Za-z0-9_-]{16,100}$")
_HUMAN_COPY = "본 브리핑은 운영책임자의 직접 검수를 통과했습니다."
_DELEGATED_COPY = DELEGATED_REVIEW_TEXT
_NAVER_RECEIPT_SUFFIX = re.compile(
    r"<table style='display:none'><tr><td><img src=\"https://mail\.naver\.com/readReceipt/notify/\?img="
    r"(?:[A-Za-z0-9._~-]|%[a-fA-F0-9]{2}){1,8192}\" border=\"0\"/></td></tr></table>\s*\Z"
)


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _time(value: Any) -> datetime:
    parsed = datetime.fromisoformat(str(value))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timezone_required")
    return parsed.astimezone(timezone.utc)


class GateError(RuntimeError):
    def __init__(self, code: str, verdict: str = "HOLD_INCOMPLETE"):
        super().__init__(code)
        self.code, self.verdict = code, verdict


@dataclass(frozen=True)
class ReviewerKey:
    principal: str
    secret: bytes


@dataclass(frozen=True)
class GateSettings:
    """Trusted service configuration; never deserialize this from a request."""
    mode: str = "OFF"
    authorized_policy: str = ""
    audience: str = "genie-delegated-review"
    reviewer_keys: Mapping[str, ReviewerKey] | None = None

    @classmethod
    def from_environment(cls) -> "GateSettings":
        keys = {}
        try:
            encoded = json.loads(os.getenv("GENIE_DELEGATED_REVIEWER_KEYS", "{}"))
            for key_id, row in encoded.items():
                secret = base64.b64decode(row["secret_b64"], validate=True)
                if len(secret) < 32 or not str(row["principal"]).strip():
                    raise ValueError("invalid reviewer key")
                keys[str(key_id)] = ReviewerKey(str(row["principal"]), secret)
        except (ValueError, TypeError, KeyError, AttributeError):
            keys = {}
        return cls(
            mode=os.getenv("DELEGATED_SEND_MODE", "OFF").strip().upper(),
            authorized_policy=os.getenv("GENIE_DELEGATED_AUTHORIZED_POLICY", ""),
            audience=os.getenv("GENIE_DELEGATED_REVIEW_AUDIENCE", "genie-delegated-review"),
            reviewer_keys=keys,
        )


def authenticate_event(raw: bytes, headers: Mapping[str, str], settings: GateSettings, *, now: datetime) -> tuple[dict, str]:
    """Verify exact bytes before parsing. Header identity cannot grant authority."""
    if not isinstance(raw, bytes) or not raw or len(raw) > 128 * 1024:
        raise GateError("INVALID_EVENT_SIZE", "REVIEW_UNAVAILABLE")
    key_id = str(headers.get("x-genie-review-key-id") or "")
    key = (settings.reviewer_keys or {}).get(key_id)
    if not key or len(key.secret) < 32:
        raise GateError("REVIEWER_KEY_UNAVAILABLE", "REVIEW_UNAVAILABLE")
    signature = str(headers.get("x-genie-review-signature") or "")
    expected = hmac.new(key.secret, raw, hashlib.sha256).hexdigest()
    if not _HEX.fullmatch(signature) or not hmac.compare_digest(signature, expected):
        raise GateError("REVIEW_AUTHENTICATION_FAILED", "REVIEW_UNAVAILABLE")

    def unique_pairs(pairs):
        row = {}
        for k, v in pairs:
            if k in row:
                raise ValueError("duplicate JSON key")
            row[k] = v
        return row

    try:
        event = json.loads(raw.decode("utf-8"), object_pairs_hook=unique_pairs,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError("non-finite JSON")))
        if not isinstance(event, dict) or not _EVENT.fullmatch(str(event.get("event_id") or "")):
            raise ValueError("invalid event identity")
        if event.get("audience") != settings.audience or event.get("policy_version") != POLICY_VERSION:
            raise GateError("REVIEW_AUDIENCE_OR_POLICY_MISMATCH", "STATE_CONFLICT")
        issued = _time(event.get("issued_at"))
        current = _time(now.isoformat())
        if issued > current or current - issued > timedelta(minutes=5):
            raise GateError("STALE_EVENT", "REVIEW_UNAVAILABLE")
        if not isinstance(event.get("review"), dict):
            raise ValueError("missing review")
        if event["review"].get("reviewer_agent") != key.principal:
            raise GateError("REVIEWER_PRINCIPAL_MISMATCH", "STATE_CONFLICT")
        return event, key.principal
    except GateError:
        raise
    except (UnicodeError, ValueError, TypeError, AttributeError):
        raise GateError("MALFORMED_REVIEW_EVENT", "HOLD_INCOMPLETE")


class _Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls = set()

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            for key, value in attrs:
                if key == "href" and isinstance(value, str) and value.startswith(("https://", "http://")):
                    self.urls.add(value)


@dataclass(frozen=True)
class FrozenImage:
    role: str
    cid: str
    filename: str
    content: bytes


@dataclass(frozen=True)
class FrozenCandidate:
    """Immutable payload owns image bytes, never a mutable source pathname."""
    binding_json: str
    meta_json: str
    saved_html: str
    subject: str
    customer_html: str
    images: tuple[FrozenImage, ...]
    recipient_plan_json: str

    @property
    def binding(self) -> dict:
        return json.loads(self.binding_json)

    @property
    def recipient_plan(self) -> dict:
        return json.loads(self.recipient_plan_json)

    @property
    def candidate_sha256(self) -> str:
        return digest(self.binding)

    def assert_integrity(self) -> None:
        binding = self.binding
        if binding.get("body_sha256") != _sha(self.customer_html.encode("utf-8")) or binding.get("subject_sha256") != _sha(self.subject.encode("utf-8")):
            raise GateError("FROZEN_PAYLOAD_CHANGED", "STATE_CONFLICT")
        image_rows = [{"role": image.role, "cid": image.cid, "filename": image.filename, "sha256": _sha(image.content)} for image in self.images]
        if binding.get("image_identity") != image_rows or binding.get("image_sha256") != {row["role"]: row["sha256"] for row in image_rows}:
            raise GateError("FROZEN_IMAGES_CHANGED", "STATE_CONFLICT")
        if binding.get("recipient_plan_sha256") != digest(self.recipient_plan):
            raise GateError("FROZEN_RECIPIENTS_CHANGED", "STATE_CONFLICT")
        meta = json.loads(self.meta_json)
        if binding.get("artifact_sha256") != digest(meta) or binding.get("received_html_sha256") != _sha(self.saved_html.encode("utf-8")):
            raise GateError("FROZEN_ARTIFACT_CHANGED", "STATE_CONFLICT")


def freeze_candidate(*, meta: dict, saved_html: str, received_message: dict, recipient_plan: dict) -> FrozenCandidate:
    """Internal adapter: use authoritative artifacts and independently read MIME.

Call before Work examines the final candidate. Existing pre-review generation
repairs remain intact in artifact metadata and are included in this identity.
The same adapter reruns at dispatch; changed artifact, source, image, receipt,
lineage, final content or recipient snapshot requires a new review.
"""
    from admin_store import validate_run_id
    run_id, mode = str(meta.get("run_id") or ""), str(meta.get("mode") or "")
    if not validate_run_id(run_id):
        raise GateError("INVALID_RUN_ID", "STATE_CONFLICT")
    from delegated_delivery_safety import PRODUCTS
    if mode not in PRODUCTS or recipient_plan.get("product_code") != PRODUCTS[mode]:
        raise GateError("RECIPIENT_PUBLICATION_PRODUCT_MISMATCH", "STATE_CONFLICT")
    recipients = [row["delivery_email"] for row in recipient_plan.get("recipients") or []]
    if not recipients:
        raise GateError("NO_ELIGIBLE_RECIPIENTS")
    if mode == "today_genie":
        from today_geenee_customer_delivery import prepare_today_geenee_customer_delivery as prepare
    elif mode in {"keysuri_global_tech", "keysuri_korea_tech"}:
        if mode == "keysuri_korea_tech":
            from admin_store import _keysuri_korea_bottom_baseline_confirmed
            baseline_ok, baseline_reason = _keysuri_korea_bottom_baseline_confirmed(meta)
            if not baseline_ok:
                raise GateError(baseline_reason)
        from keysuri_customer_delivery import prepare_keysuri_customer_delivery as prepare
    else:
        raise GateError("UNSUPPORTED_PRODUCT", "STATE_CONFLICT")
    # The delegated candidate is rendered once with an explicit display source
    # before its hash is frozen.  This presentation argument cannot grant any
    # approval or delivery right; later authenticated review and final boundary
    # checks remain mandatory.
    prepared = prepare(
        saved_html,
        meta,
        recipients_override=recipients,
        approval_source=DELEGATED_WORK_REVIEW,
    )
    if not prepared.get("ok"):
        raise GateError(str(prepared.get("error") or "CANDIDATE_PREPARATION_FAILED"))
    customer_html = str(prepared["html_body"])
    # Never let a future renderer's explicit human-attestation copy slip through.
    if "운영책임자의 직접 검수" in customer_html:
        raise GateError("UNSUPPORTED_HUMAN_APPROVAL_COPY", "STATE_CONFLICT")
    if _DELEGATED_COPY not in customer_html:
        raise GateError("DELEGATED_APPROVAL_COPY_MISSING", "STATE_CONFLICT")
    images = tuple(FrozenImage("top" if index == 0 else "bottom" if index == 1 else f"image_{index+1}", str(cid), Path(filename).name, Path(path).read_bytes())
                   for index, (path, cid, filename) in enumerate(prepared["inline_jpeg_parts"]))
    if any(not image.content for image in images):
        raise GateError("EMPTY_IMAGE")
    links = _Links()
    links.feed(customer_html)
    # The artifact hash additionally covers source selection and generation repair
    # trace, including links present in metadata but absent from the email design.
    artifact_hash = digest(meta)
    image_rows = [{"role": image.role, "cid": image.cid, "filename": image.filename, "sha256": _sha(image.content)} for image in images]
    publication_date = str(recipient_plan.get("publication_date") or "")
    binding = {
        "run_id": run_id, "mode": mode, "publication_date": publication_date,
        "artifact_id": f"{run_id}:{artifact_hash}", "artifact_sha256": artifact_hash,
        "subject_sha256": _sha(str(prepared["subject"]).encode("utf-8")),
        "body_sha256": _sha(customer_html.encode("utf-8")),
        "received_html_sha256": _sha(saved_html.encode("utf-8")),
        "image_sha256": {row["role"]: row["sha256"] for row in image_rows},
        "image_identity": image_rows, "source_urls": sorted(links.urls),
        "source_links_sha256": digest(sorted(links.urls)),
        "recipient_plan_sha256": digest(recipient_plan), "policy_version": POLICY_VERSION,
        "received_message_id": received_message.get("message_id"), "received_message": received_message,
        "customer_render_capture_sha256": received_message.get("customer_render_capture_sha256"),
        "first_pass_verdict": "PASS" if meta.get("validation_result") == "pass" else "HOLD",
        "artifact_status": meta.get("artifact_status"), "owner_review_status": meta.get("owner_review_status"),
        "customer_surface_status": meta.get("customer_surface_status"),
        "customer_delivery_status": meta.get("customer_delivery_status"),
        "safety_verdict": meta.get("safety_verdict"), "editorial_verdict": meta.get("editorial_verdict"),
        "parent_run_id": meta.get("parent_run_id"), "reissue_requested": meta.get("reissue_requested"),
        "last_reissue_child_run_id": meta.get("last_reissue_child_run_id"), "superseded_by_run_id": meta.get("superseded_by_run_id"),
    }
    frozen = FrozenCandidate(canonical(binding), canonical(meta), saved_html, str(prepared["subject"]), customer_html, images, canonical(recipient_plan))
    frozen.assert_integrity()
    return frozen


def verify_received_html_transport(received: str, saved: str) -> dict:
    """Allow only the exact hidden Naver suffix observed in real review emails.

Never strip arbitrary tables, HTML after a closing tag, tracking-like hosts,
extra query parameters or visible content. Raw MIME evidence is always hashed
before this narrowly scoped comparison and is never rewritten.
"""
    received, saved = received.rstrip("\r\n"), saved.rstrip("\r\n")
    if received == saved:
        return {"recognized_transport_suffix_count": 0}
    match = _NAVER_RECEIPT_SUFFIX.search(received)
    if match and received[:match.start()].rstrip("\r\n") == saved:
        return {"recognized_transport_suffix_count": 1, "transport_suffix_kind": "NAVER_READ_RECEIPT",
                "transport_suffix_sha256": _sha(match.group(0).encode("utf-8"))}
    raise GateError("RECEIVED_HTML_RUN_BINDING_MISMATCH", "STATE_CONFLICT")


def register_received_mail_evidence(*, run_id: str, mailbox_id: str, message_id: str,
                                    received_at: str, raw_mime: bytes, render_capture: bytes,
                                    customer_render_capture: bytes, recipient_plan: dict) -> dict:
    """Trusted Gmail broker only; not exposed as a reviewer/request endpoint.

Derive evidence hashes from actual MIME/capture bytes. Refuse wrong saved HTML,
wrong image bytes or missing run identity. Gmail account authentication and the
pixel inspection itself remain responsibilities of the configured cloud broker;
this function cannot make a connector available or prove visual quality.
"""
    from email import policy
    from email.parser import BytesParser
    from admin_store import load_run_artifact, load_run_email_html, validate_run_id
    from admin_safety_store import _create_json_once, _read_json
    from delegated_delivery_safety import load_recipient_plan
    if not validate_run_id(run_id) or not mailbox_id or not message_id or not raw_mime or not render_capture or not customer_render_capture:
        raise GateError("RECEIVED_MAIL_EVIDENCE_INCOMPLETE")
    _time(received_at)
    plan = load_recipient_plan(recipient_plan["plan_id"], expected_sha256=recipient_plan["sha256"])
    meta, saved_html = load_run_artifact(run_id), load_run_email_html(run_id)
    if not meta or not saved_html:
        raise GateError("AUTHORITATIVE_ARTIFACT_UNAVAILABLE")
    mime = BytesParser(policy=policy.default).parsebytes(raw_mime)
    html_parts = [part.get_content() for part in mime.walk() if part.get_content_type() == "text/html"]
    if len(html_parts) != 1 or run_id not in html_parts[0]:
        raise GateError("RECEIVED_HTML_RUN_BINDING_MISMATCH", "STATE_CONFLICT")
    transport = verify_received_html_transport(html_parts[0], saved_html)
    internet_id = str(mime.get("Message-ID") or "")
    if not internet_id:
        raise GateError("RECEIVED_MESSAGE_ID_MISSING")
    receipt = {"mailbox_id": mailbox_id, "message_id": message_id,
        "internet_message_id": internet_id, "received_at": received_at,
        "raw_mime_sha256": _sha(raw_mime), "render_capture_sha256": _sha(render_capture),
        "customer_render_capture_sha256": _sha(customer_render_capture)}
    candidate = freeze_candidate(meta=meta, saved_html=saved_html, received_message=receipt, recipient_plan=plan)
    received_images = {}
    for part in mime.walk():
        if part.get_content_maintype() == "image":
            cid = str(part.get("Content-ID") or "").strip("<>")
            if not cid or cid in received_images:
                raise GateError("RECEIVED_IMAGE_IDENTITY_AMBIGUOUS", "STATE_CONFLICT")
            received_images[cid] = _sha(part.get_payload(decode=True) or b"")
    for image in candidate.images:
        if received_images.get(image.cid.strip("<>")) != _sha(image.content):
            raise GateError("RECEIVED_IMAGE_ARTIFACT_MISMATCH", "STATE_CONFLICT")
    record = {"run_id": run_id, "publication_date": plan["publication_date"], "received_message": receipt,
              "recipient_plan_id": plan["plan_id"], "recipient_plan_sha256": plan["sha256"],
              "candidate_sha256": candidate.candidate_sha256, "transport_comparison": transport}
    key = f"delegated_received_bindings/{_sha(run_id.encode('utf-8'))}.json"
    if not _create_json_once(key, record) and _read_json(key) != record:
        raise GateError("RECEIVED_BINDING_ALREADY_EXISTS_REVIEW_REQUIRED", "STATE_CONFLICT")
    return record


class RunArtifactCandidateLoader:
    """Production-artifact adapter. Missing trusted Gmail binding fails closed.

The Gmail ingestion adapter must persist the run-bound receipt under this private
safety-store prefix before review. This runner never copies a receipt supplied
inside the signed verdict into that independent record.
"""
    def __init__(self, recipient_authority):
        self.recipient_authority = recipient_authority

    def load(self, run_id: str, *, now: datetime) -> FrozenCandidate:
        from admin_store import load_run_artifact, load_run_email_html
        from admin_safety_store import _read_json
        meta = load_run_artifact(run_id)
        html = load_run_email_html(run_id)
        record = _read_json(f"delegated_received_bindings/{_sha(run_id.encode('utf-8'))}.json")
        if not meta or not html or not record or record.get("run_id") != run_id:
            raise GateError("AUTHORITATIVE_ARTIFACT_OR_RECEIPT_UNAVAILABLE")
        from delegated_delivery_safety import load_recipient_plan
        # The plan was prepared/frozen before review. Rebuilding it with a new
        # frozen_at timestamp on every load would falsely invalidate every PASS.
        plan = load_recipient_plan(record.get("recipient_plan_id"), expected_sha256=record.get("recipient_plan_sha256"))
        if plan.get("publication_date") != record.get("publication_date"):
            raise GateError("RECEIPT_PUBLICATION_PLAN_MISMATCH", "STATE_CONFLICT")
        candidate = freeze_candidate(meta=meta, saved_html=html, received_message=record.get("received_message") or {}, recipient_plan=plan)
        if record.get("candidate_sha256") != candidate.candidate_sha256:
            # A frozen run's material mutation requires a newly received review
            # candidate. The existing recovery contract creates a fresh run ID.
            raise GateError("RECEIVED_CANDIDATE_CHANGED_REISSUE_REVIEW_REQUIRED", "STATE_CONFLICT")
        return candidate


def evaluate_authenticated_review(candidate: FrozenCandidate, event: dict, *, now: datetime) -> dict:
    candidate.assert_integrity()
    review = event["review"]
    if event.get("candidate_sha256") != candidate.candidate_sha256:
        raise GateError("CANDIDATE_CHANGED_REVIEW_REQUIRED", "STATE_CONFLICT")
    if review.get("policy_version") != POLICY_VERSION:
        raise GateError("REVIEW_POLICY_MISMATCH", "STATE_CONFLICT")
    final_capture = candidate.binding.get("customer_render_capture_sha256")
    if not isinstance(final_capture, str) or not _HEX.fullmatch(final_capture):
        raise GateError("FINAL_CUSTOMER_RENDER_EVIDENCE_MISSING")
    if review.get("customer_render_capture_sha256") != final_capture:
        raise GateError("FINAL_CUSTOMER_RENDER_BINDING_MISMATCH", "STATE_CONFLICT")
    if review.get("verdict") not in VERDICTS:
        raise GateError("UNKNOWN_REVIEW_STATE")
    if review["verdict"] != "PASS":
        return {"verdict": review["verdict"], "reason_codes": ["REVIEWER_REPORTED_NON_PASS"]}
    checks, evidence = review.get("checks"), review.get("evidence")
    if not isinstance(checks, dict) or not isinstance(evidence, dict):
        raise GateError("REVIEW_DIMENSIONS_MISSING")
    if any(value in {"FAIL", "HOLD", "ANOMALY"} for value in checks.values() if isinstance(value, str)):
        raise GateError("REVIEW_ANOMALY", "HOLD_ANOMALY")
    if any(checks.get(key) != "PASS" or not isinstance(evidence.get(key), list) or not evidence[key] or not all(isinstance(ref, str) and ref.strip() for ref in evidence[key]) for key in REQUIRED_CHECKS):
        raise GateError("REVIEW_DIMENSIONS_INCOMPLETE")
    # Reuse existing state/time/message invariants after strict v2 authentication
    # and candidate digest validation. This is an internal compatibility mapping.
    legacy = dict(review)
    legacy["policy_version"] = SHADOW_POLICY
    legacy["checks"] = {**checks, "operations": "PASS"}
    legacy["evidence"] = {**evidence, "operations": evidence["run_identity"] + evidence["delivery_readiness"]}
    result = evaluate_shadow_review(candidate.binding, legacy, now=now)
    mapped = {"HOLD": "STATE_CONFLICT", "REVIEW_INCOMPLETE": "HOLD_INCOMPLETE", "WORK_REVIEW_ERROR": "HOLD_INCOMPLETE"}
    result["verdict"] = mapped.get(result["verdict"], result["verdict"])
    if review.get("anomalies"):
        result.update(verdict="HOLD_ANOMALY", reason_codes=["REVIEW_ANOMALY"])
    return result


def _outcome(verdict: str, reason: str, **extra: Any) -> dict:
    return {"verdict": verdict, "reason_codes": [reason], "customer_send_authorized": False,
            "approval_source": "NONE", "approval_authority": "NONE", "owner_notification_required": verdict != "PASS", **extra}


def run_configured_review_event(raw: bytes, headers: Mapping[str, str], *, now: datetime | None = None) -> dict:
    """Composition entry point for the authenticated internal review route.

Only body bytes and signature headers are transport inputs. All dependencies,
keys, activation policy, suppression health and artifacts are service-owned.
The route does not schedule reviews or create reviewer evidence by itself.
"""
    settings = GateSettings.from_environment()
    if settings.mode not in {"SHADOW", "ON"}:
        return _outcome("STATE_CONFLICT", "DELEGATED_SEND_MODE_OFF")
    from delegated_delivery_safety import recipient_authority
    authority = recipient_authority()
    return process_review_event(raw, headers, loader=RunArtifactCandidateLoader(authority),
        recipient_authority=authority, now=now or datetime.now(timezone.utc), settings=settings)


def process_review_event(raw: bytes, headers: Mapping[str, str], *, loader, recipient_authority,
                         now: datetime, settings: GateSettings | None = None, sender=None) -> dict:
    """Trusted worker entry point. No requester-supplied candidate/recipient flags.

``sender`` is a trusted server dependency for isolated tests, never a request
parameter. Production dispatch uses the existing SMTP functions with frozen
payload bytes. All durable claims survive failures and process restarts.
"""
    settings = settings or GateSettings.from_environment()
    if settings.mode not in {"SHADOW", "ON"}:
        return _outcome("STATE_CONFLICT", "DELEGATED_SEND_MODE_OFF")
    if settings.mode == "ON" and settings.authorized_policy != POLICY_VERSION:
        return _outcome("STATE_CONFLICT", "OWNER_DELEGATION_POLICY_NOT_ACTIVATED")
    event, principal, attempt_id, candidate = None, None, None, None
    from admin_safety_store import _create_json_once
    from admin_store import run_delivery_transition
    try:
        event, principal = authenticate_event(raw, headers, settings, now=now)
        # Claim before any review or attempt; collisions/retries cannot resubmit.
        event_key = digest({"principal": principal, "event_id": event["event_id"]})
        if not _create_json_once(f"delegated_review_events/{event_key}.json", {
            "event_sha256": _sha(raw), "event": event, "principal": principal,
            "received_at": now.isoformat(), "status": "RECEIVED", "send_attempted": False,
        }):
            return _outcome("STATE_CONFLICT", "REPLAYED_REVIEW_EVENT_RECONCILE")
        run_id = str(event.get("run_id") or "")
        current_transition = run_delivery_transition(run_id)
        if current_transition["state"] == "HELD":
            raise GateError("RUN_HELD_MANUAL_RECOVERY_REQUIRED" if current_transition.get("manual_recovery_required") else "RUN_EXPLICITLY_HELD", "STATE_CONFLICT")
        if current_transition["state"] == "SUBMITTED":
            raise GateError("DELIVERY_HANDOFF_ALREADY_CLAIMED", "STATE_CONFLICT")
        candidate = loader.load(run_id, now=now)
        if candidate.binding.get("run_id") != run_id:
            raise GateError("AUTHORITATIVE_RUN_MISMATCH", "STATE_CONFLICT")
        evaluation = evaluate_authenticated_review(candidate, event, now=now)
        audit = {"event_id": event["event_id"], "review_id": event_key, "run_id": run_id,
                 "candidate_sha256": candidate.candidate_sha256, "policy_version": POLICY_VERSION,
                 "reviewer_principal": principal, "reviewer_model": event["review"].get("reviewer_model"),
                 "reviewer_model_independently_verified": False, "authenticity_verified": True,
                 "reviewed_at": event["review"].get("reviewed_at"), "evaluated_at": now.isoformat()}
        if evaluation["verdict"] != "PASS":
            if evaluation["verdict"] == "HOLD_ANOMALY" and settings.mode == "ON":
                latch = run_delivery_transition(run_id, action="HOLD", authority="DELEGATED_WORK_REVIEW",
                                                manual_recovery_required=True)
                if not latch.get("allowed"):
                    raise GateError(latch["reason"], "STATE_CONFLICT")
            result = _outcome(evaluation["verdict"], evaluation["reason_codes"][0], **audit)
        elif settings.mode == "SHADOW":
            result = _outcome("PASS", "AUTHENTICATED_SHADOW_ONLY", **audit)
        else:
            # Reload at the final boundary; A->B changes require a new PASS.
            current = loader.load(run_id, now=now)
            current.assert_integrity()
            if current.candidate_sha256 != candidate.candidate_sha256:
                raise GateError("CANDIDATE_CHANGED_BEFORE_SUBMIT", "STATE_CONFLICT")
            plan = current.recipient_plan
            recipient_authority.revalidate(plan, now=now)
            from delegated_delivery_safety import reserve_publication_attempt, complete_publication_attempt
            reservation = reserve_publication_attempt(plan, run_id=run_id, candidate_sha256=current.candidate_sha256,
                                                      review_id=event_key, now=now)
            if not reservation.get("allowed"):
                raise GateError(str(reservation.get("reason") or "PUBLICATION_RECONCILIATION_REQUIRED"), "STATE_CONFLICT")
            attempt_id = reservation["attempt_id"]
            # Recheck suppression and kill switch after acquiring durable claims.
            # Explicit injected settings are trusted test/composition config; the
            # production default rereads the environment immediately before SMTP.
            recipient_authority.revalidate(plan, now=now)
            if settings.mode != "ON" or (sender is None and os.getenv("DELEGATED_SEND_MODE", "OFF").strip().upper() != "ON"):
                raise GateError("DELEGATED_SEND_DISABLED_BEFORE_SUBMIT", "STATE_CONFLICT")
            handoff = run_delivery_transition(run_id, action="SUBMIT", authority="DELEGATED_WORK_REVIEW",
                                              candidate_sha256=current.candidate_sha256)
            if not handoff.get("allowed"):
                raise GateError(handoff["reason"], "STATE_CONFLICT")
            if sender is None:
                submission = submit_frozen_candidate(
                    current,
                    plan,
                    audit={**audit, "attempt_id": attempt_id},
                    recipient_authority=recipient_authority,
                )
            else:
                submission = sender(current, plan, audit={**audit, "attempt_id": attempt_id})
            status = str(submission.get("outcome") or "OUTCOME_UNKNOWN")
            provider_status = ("PROVIDER_ACCEPTED" if status == "ACCEPTED_ALL" else
                               "PROVIDER_REJECTED" if status in {"REFUSED_ALL", "NOT_SENT"} else
                               "UNKNOWN_AFTER_SUBMIT")
            complete_publication_attempt(attempt_id, outcome=provider_status, evidence=submission)
            result = _outcome("PASS", "DELEGATED_SUBMISSION_RECORDED", **audit,
                              customer_send_authorized=True, approval_source="DELEGATED_WORK_REVIEW",
                              approval_authority=str(plan.get("authority") or "DELEGATED_WORK_REVIEW"),
                              authority_grant_id=plan.get("authority_grant_id"), attempt_id=attempt_id,
                              submission_outcome=status, inbox_receipt_confirmed=False,
                              owner_notification_required=status != "ACCEPTED_ALL")
        if not _create_json_once(f"delegated_review_results/{event_key}.json", result):
            raise GateError("REVIEW_RESULT_ALREADY_EXISTS", "STATE_CONFLICT")
        return result
    except Exception as exc:
        if isinstance(exc, GateError) and exc.verdict == "HOLD_ANOMALY" and candidate is not None and settings.mode == "ON":
            try:
                latch = run_delivery_transition(candidate.binding["run_id"], action="HOLD",
                    authority="DELEGATED_WORK_REVIEW", manual_recovery_required=True)
                if not latch.get("allowed"):
                    exc = GateError(latch["reason"], "STATE_CONFLICT")
            except Exception:
                exc = GateError("ANOMALY_HOLD_STORE_UNAVAILABLE", "REVIEW_UNAVAILABLE")
        code = exc.code if isinstance(exc, GateError) else "REVIEW_OR_DELIVERY_DEPENDENCY_UNAVAILABLE"
        if exc.__class__.__name__ == "DeliverySafetyError" and re.fullmatch(r"[A-Z0-9_]{1,120}", str(exc)):
            code = str(exc)
        verdict = exc.verdict if isinstance(exc, GateError) else "REVIEW_UNAVAILABLE"
        result = _outcome(verdict, code, attempt_id=attempt_id, reconciliation_required=bool(attempt_id))
        # Best-effort exception evidence; failure never relaxes the send boundary.
        if event is not None and principal is not None:
            try:
                _create_json_once(f"delegated_review_failures/{digest({'principal': principal, 'event_id': event['event_id']})}.json", result)
            except Exception:
                pass
        return result


def submit_frozen_candidate(
    candidate: FrozenCandidate,
    recipient_plan: dict,
    *,
    audit: dict,
    recipient_authority=None,
) -> dict:
    """Only caller is the authenticated runner after durable recipient gates.

The provider sees the exact reviewed HTML and owned image bytes. Source paths
cannot mutate the candidate after review. SMTP acceptance is never receipt.
"""
    from admin_store import update_run_artifact, now_kst_iso, run_delivery_transition, normalize_artifact_view
    from email_sender import last_send_diagnostic, last_send_trace, reset_last_send_state
    from delivery_trace import build_customer_email_delivery_fields
    candidate.assert_integrity()
    if os.getenv("DELEGATED_SEND_MODE", "OFF").strip().upper() != "ON":
        raise GateError("DELEGATED_SEND_MODE_OFF", "STATE_CONFLICT")
    meta = json.loads(candidate.meta_json)
    run_id, mode = candidate.binding["run_id"], candidate.binding["mode"]
    transition = run_delivery_transition(run_id)
    if (transition.get("state") != "SUBMITTED" or transition.get("authority") != "DELEGATED_WORK_REVIEW"
            or transition.get("candidate_sha256") != candidate.candidate_sha256):
        raise GateError("DELEGATED_HANDOFF_CLAIM_MISSING", "STATE_CONFLICT")
    attempted_at = now_kst_iso()
    authority_fields = {
        "approval_source": "DELEGATED_WORK_REVIEW",
        "approval_authority": str(recipient_plan.get("authority") or "DELEGATED_WORK_REVIEW"),
        "delegated_authority_grant_id": recipient_plan.get("authority_grant_id"),
        "delegated_review_id": audit["review_id"], "delegated_review_policy_version": POLICY_VERSION,
        "delegated_candidate_sha256": candidate.candidate_sha256, "delegated_reviewed_at": audit["reviewed_at"],
        "delegated_reviewer_principal": audit["reviewer_principal"],
        "delegated_delivery_attempt_id": audit["attempt_id"], "customer_delivery_reason": "delegated_work_review_pass",
    }
    def attempt(row):
        if digest(normalize_artifact_view(row, run_id)) != candidate.binding["artifact_sha256"]:
            raise GateError("ARTIFACT_CHANGED_AT_HANDOFF", "STATE_CONFLICT")
        row.update(authority_fields)
        row["customer_delivery_status"] = "SUBMITTED"
        row["customer_delivery_attempted_at"] = attempted_at
        row["customer_delivery_attempt_count"] = int(row.get("customer_delivery_attempt_count") or 0) + 1
    if not update_run_artifact(run_id, attempt):
        raise GateError("RUN_ATTEMPT_RECORD_FAILED", "STATE_CONFLICT")
    recipients = [row["delivery_email"] for row in recipient_plan["recipients"]]
    reset_last_send_state()
    with tempfile.TemporaryDirectory(prefix="genie-delegated-frozen-") as directory:
        parts = []
        for index, image in enumerate(candidate.images):
            path = Path(directory) / f"{index}.jpg"
            path.write_bytes(image.content)
            path.chmod(0o400)
            parts.append((str(path), image.cid, image.filename))
        prepared = {"ok": True, "html_body": candidate.customer_html, "subject": candidate.subject,
                    "inline_jpeg_parts": parts, "recipients": recipients, "preheader": ""}
        # Re-read the revocation/config generation at the last application
        # boundary. A revoked or changed beta grant can never reuse a stale plan.
        if recipient_authority is None:
            from delegated_delivery_safety import recipient_authority as authority_factory

            recipient_authority = authority_factory()
        recipient_authority.revalidate(recipient_plan, datetime.now(timezone.utc))
        if mode == "today_genie":
            from today_geenee_customer_delivery import send_today_geenee_customer_final_email as send
        else:
            from keysuri_customer_delivery import send_keysuri_customer_final_email as send
        sent = send(candidate.saved_html, meta, prepared_delivery=prepared)
    trace = dict(last_send_trace() or {})
    trace.setdefault("envelope_to", recipients)
    trace["attempted_at"] = attempted_at
    fields = build_customer_email_delivery_fields(attempted=True, send_ok=bool(sent), subject=candidate.subject,
                                                  trace=trace, diagnostic=last_send_diagnostic(), sent_at_kst=now_kst_iso())
    status = str(fields.get("customer_email_delivery_status") or "OUTCOME_UNKNOWN")
    def complete(row):
        row.update(fields)
        row.update(authority_fields)
        row["customer_delivery_status"] = status
        row["delegated_review_status"] = "passed"
        row["provider_exactly_once"] = False
        row["inbox_receipt_confirmed"] = False
        # Human review status/approved_by/owner_reviewed_at are never fabricated.
    if not update_run_artifact(run_id, complete):
        raise GateError("RUN_RESULT_RECORD_FAILED_RECONCILE", "STATE_CONFLICT")
    return {"outcome": status, "target_count": len(recipients),
            "accepted_count": fields.get("customer_delivery_accepted_count"),
            "refused_count": fields.get("customer_delivery_refused_count"),
            "unknown_count": fields.get("customer_delivery_unknown_count"),
            "provider_exactly_once": False, "inbox_receipt_confirmed": False,
            "approval_source": "DELEGATED_WORK_REVIEW", "attempt_id": audit["attempt_id"]}
