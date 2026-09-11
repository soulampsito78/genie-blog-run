#!/usr/bin/env python3
"""Bind a locally inspected Gmail message and submit its signed Work verdict.

Secrets are read directly from Secret Manager into process memory and are never
printed or written to disk. The script cannot select recipients or enable live
delivery; those decisions remain service-owned and grant-bound.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import secrets
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ID = "gen-lang-client-0667098249"
SERVICE_URL = "https://genie-blog-run-1055014091206.asia-northeast3.run.app"
ARTIFACT_BUCKET = "gen-lang-client-0667098249-genie-artifacts"
REVIEWER_SECRET = "genie-delegated-reviewer-keys"
INTERNAL_TOKEN_SECRET = "genie-internal-job-token"
KEY_ID = "runner-v1"


def _secret(name: str) -> bytes:
    process = subprocess.run(
        [
            "gcloud",
            "secrets",
            "versions",
            "access",
            "latest",
            f"--secret={name}",
            f"--project={PROJECT_ID}",
        ],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    value = process.stdout.strip()
    if not value:
        raise RuntimeError("required_secret_unavailable")
    return value


def _normalise_checks(review: dict) -> tuple[dict, dict]:
    aliases = {
        "content": ("content", "CONTENT"),
        "sources": ("sources", "source", "SOURCES", "SOURCE"),
        "images": ("images", "image", "IMAGES", "IMAGE"),
        "render": ("render", "email_render", "RENDER", "EMAIL_RENDER"),
        "customer_render": ("customer_render", "CUSTOMER_RENDER"),
        "run_identity": ("run_identity", "RUN_IDENTITY"),
        "delivery_readiness": ("delivery_readiness", "DELIVERY_READINESS"),
    }
    source_checks = review.get("checks") or {}
    source_evidence = review.get("evidence") or {}
    checks, evidence = {}, {}
    for target, names in aliases.items():
        value = next((source_checks[name] for name in names if name in source_checks), None)
        if isinstance(value, dict):
            value = value.get("verdict")
        checks[target] = str(value or "").upper()
        refs = next((source_evidence[name] for name in names if name in source_evidence), None)
        if isinstance(refs, str):
            refs = [refs]
        evidence[target] = refs if isinstance(refs, list) else []
    return checks, evidence


def _post(path: str, raw: bytes, headers: dict[str, str]) -> dict:
    request = urllib.request.Request(
        SERVICE_URL + path, data=raw, headers=headers, method="POST"
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        result = json.loads(response.read())
    if not isinstance(result, dict):
        raise RuntimeError("invalid_service_response")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--review-json", required=True)
    parser.add_argument("--raw-mime", required=True)
    parser.add_argument("--email-render-capture", required=True)
    parser.add_argument("--customer-render-capture", required=True)
    parser.add_argument("--mailbox-id", required=True)
    parser.add_argument("--message-id", required=True)
    parser.add_argument("--received-at", required=True)
    parser.add_argument("--reviewer-model", default="gpt-5.3-codex-spark")
    args = parser.parse_args()

    review_input = json.loads(Path(args.review_json).read_text(encoding="utf-8"))
    run_id = str(review_input.get("run_id") or "")
    mode = str(review_input.get("product") or review_input.get("mode") or "")
    publication_date = str(review_input.get("publication_date") or "")
    verdict = str(review_input.get("overall_verdict") or "").upper()
    if verdict not in {
        "PASS",
        "HOLD_ANOMALY",
        "HOLD_INCOMPLETE",
        "REVIEW_UNAVAILABLE",
        "STATE_CONFLICT",
    }:
        raise RuntimeError("invalid_review_verdict")

    os.environ.update(
        {
            "GENIE_ARTIFACT_STORE_BACKEND": "gcs",
            "GENIE_ARTIFACT_BUCKET": ARTIFACT_BUCKET,
            "GENIE_ARTIFACT_PREFIX": "admin_runs",
            "GENIE_RECIPIENT_AUTHORITY": "ADMIN_BETA_DELEGATION",
        }
    )
    repo = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo))
    from delegated_delivery_safety import recipient_authority
    from delegated_gate import (
        POLICY_VERSION,
        RunArtifactCandidateLoader,
        canonical,
        register_received_mail_evidence,
    )

    now = datetime.now(timezone.utc)
    authority = recipient_authority()
    plan = authority.prepare(mode, publication_date, now)
    register_received_mail_evidence(
        run_id=run_id,
        mailbox_id=args.mailbox_id,
        message_id=args.message_id,
        received_at=args.received_at,
        raw_mime=Path(args.raw_mime).read_bytes(),
        render_capture=Path(args.email_render_capture).read_bytes(),
        customer_render_capture=Path(args.customer_render_capture).read_bytes(),
        recipient_plan=plan,
    )
    candidate = RunArtifactCandidateLoader(authority).load(run_id, now=now)
    checks, evidence = _normalise_checks(review_input)

    key_config = json.loads(_secret(REVIEWER_SECRET))
    key_record = key_config[KEY_ID]
    principal = str(key_record["principal"])
    secret = base64.b64decode(key_record["secret_b64"], validate=True)
    if len(secret) < 32 or not principal:
        raise RuntimeError("reviewer_secret_invalid")
    event = {
        "event_id": "review_" + secrets.token_hex(16),
        "run_id": run_id,
        "audience": "genie-delegated-review",
        "policy_version": POLICY_VERSION,
        "issued_at": now.isoformat(),
        "candidate_sha256": candidate.candidate_sha256,
        "review": {
            **candidate.binding,
            "policy_version": POLICY_VERSION,
            "reviewer_agent": principal,
            "reviewer_model": args.reviewer_model,
            "verdict": verdict,
            "reviewed_at": now.isoformat(),
            "checks": checks,
            "evidence": evidence,
            "critical_sources_checked": checks.get("sources") == "PASS",
            "anomalies": list(review_input.get("anomalies") or []),
            "customer_render_capture_sha256": candidate.binding[
                "customer_render_capture_sha256"
            ],
        },
    }
    raw = canonical(event).encode("utf-8")
    result = _post(
        "/internal/jobs/delegated-review",
        raw,
        {
            "Content-Type": "application/json",
            "X-Genie-Internal-Job-Token": _secret(INTERNAL_TOKEN_SECRET).decode(
                "utf-8"
            ),
            "X-Genie-Review-Key-Id": KEY_ID,
            "X-Genie-Review-Signature": hmac.new(
                secret, raw, hashlib.sha256
            ).hexdigest(),
        },
    )
    safe = {
        key: result.get(key)
        for key in (
            "verdict",
            "reason_codes",
            "customer_send_authorized",
            "approval_source",
            "approval_authority",
            "authority_grant_id",
            "attempt_id",
            "submission_outcome",
            "owner_notification_required",
        )
    }
    print(json.dumps(safe, ensure_ascii=False, sort_keys=True))
    return 0 if result.get("verdict") == verdict else 2


if __name__ == "__main__":
    raise SystemExit(main())
