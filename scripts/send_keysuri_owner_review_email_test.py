#!/usr/bin/env python3
"""
Local Kee-Suri owner-review SMTP harness (plain HTML from existing preview file).

NOT customer delivery. Does not call approve_run(), orchestrator, Gemini/Vertex,
image API, scheduler, or mutate output/admin_runs or static/email.

Default mode is report-only. Real SMTP send requires ALL of:
  --send
  GENIE_EMAIL_SEND_TEST=1 (or true/yes)
  --confirm SEND
  explicit --to recipient(s) on OWNER_REVIEW_EMAIL_ALLOWLIST only

Usage:
  python3 scripts/send_keysuri_owner_review_email_test.py \\
    --html output/keysuri_preview/keysuri_global_generated_owner_review_preview.html
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from email_sender import (  # noqa: E402
    last_password_resolution,
    last_send_diagnostic,
    send_genie_email,
    smtp_configured,
)
from publishing_policy import OWNER_REVIEW_EMAIL_ALLOWLIST  # noqa: E402

_DEFAULT_HTML = (
    _REPO / "output" / "keysuri_preview" / "keysuri_global_generated_owner_review_preview.html"
)
_DEFAULT_SUBJECT = "[KEYSURI test] Kee-Suri owner-review preview"
_SEND_CONFIRM_PHRASE = "SEND"
_ENV_SEND_TEST_TRUTHY = frozenset({"1", "true", "True", "yes", "YES"})
_HARNESS_META = {
    "harness_kind": "keysuri_owner_review_smtp_harness",
    "not_customer_delivery": True,
    "not_approve_run": True,
    "not_admin_artifact_mutation": True,
    "not_scheduler": True,
    "not_image_api": True,
}


def _die(msg: str, code: int = 2) -> None:
    print(msg, file=sys.stderr)
    sys.exit(code)


def _parse_address_tokens(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in values:
        for part in raw.split(","):
            addr = part.strip()
            if not addr or "@" not in addr:
                continue
            low = addr.lower()
            if low in seen:
                continue
            seen.add(low)
            out.append(addr)
    return out


def _env_send_test_gate_ok() -> bool:
    return os.getenv("GENIE_EMAIL_SEND_TEST", "").strip() in _ENV_SEND_TEST_TRUTHY


def _recipient_allowlist_ok(recipients: list[str]) -> tuple[bool, str | None]:
    if not recipients:
        return False, "no recipients resolved"
    blocked = [r for r in recipients if r.strip().lower() not in OWNER_REVIEW_EMAIL_ALLOWLIST]
    if blocked:
        return (
            False,
            "recipient(s) outside OWNER_REVIEW_EMAIL_ALLOWLIST: " + ", ".join(blocked),
        )
    return True, None


def _evaluate_send_gate(
    *,
    want_send: bool,
    confirm: str | None,
    recipients: list[str],
    html_exists: bool,
) -> tuple[bool, str | None]:
    if not html_exists:
        return False, "HTML file missing or unreadable"
    if not want_send:
        return False, "send disabled (default report-only; pass --send to attempt SMTP)"
    if not _env_send_test_gate_ok():
        return False, "GENIE_EMAIL_SEND_TEST not set to an allowed truthy value"
    if (confirm or "").strip() != _SEND_CONFIRM_PHRASE:
        return False, f"--confirm {_SEND_CONFIRM_PHRASE} is required for --send"
    if not recipients:
        return False, "no explicit send recipients (--to required for --send)"
    ok, reason = _recipient_allowlist_ok(recipients)
    if not ok:
        return False, reason
    if not smtp_configured():
        return False, "SMTP not configured (SMTP_HOST, SMTP_USER, and password required)"
    return True, None


def _resolve_html_path(arg: str | None) -> Path:
    if arg:
        p = Path(arg)
        if not p.is_file():
            p = _REPO / arg
        return p
    if _DEFAULT_HTML.is_file():
        return _DEFAULT_HTML
    _die(
        "no --html path and default preview HTML not found: "
        f"{_DEFAULT_HTML.relative_to(_REPO)}"
    )


def _build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Kee-Suri owner-review SMTP harness (report-only by default; not customer delivery)."
    )
    ap.add_argument(
        "--html",
        default="",
        help=(
            "Path to Kee-Suri owner-review HTML (repo-relative or absolute). "
            f"Default: {_DEFAULT_HTML.relative_to(_REPO)} if present."
        ),
    )
    ap.add_argument("--subject", default=_DEFAULT_SUBJECT, help="Email subject line.")
    ap.add_argument(
        "--send",
        action="store_true",
        default=False,
        help="Attempt real SMTP send (requires env gate, --confirm SEND, explicit --to).",
    )
    ap.add_argument(
        "--confirm",
        default="",
        help=f'Confirmation phrase required for --send (must be exactly "{_SEND_CONFIRM_PHRASE}").',
    )
    ap.add_argument(
        "--to",
        action="append",
        default=[],
        metavar="EMAIL",
        help="Recipient address(es); repeatable or comma-separated. Required for --send.",
    )
    ap.add_argument(
        "--no-write-output",
        action="store_true",
        default=False,
        help="Print JSON report to stdout only; do not write output/** artifacts.",
    )
    return ap


def main() -> int:
    ap = _build_arg_parser()
    args = ap.parse_args()

    print(
        "KEYSURI OWNER REVIEW SMTP HARNESS — default report-only; SMTP only with "
        "--send + GENIE_EMAIL_SEND_TEST + --confirm SEND + allowlisted --to.",
        file=sys.stderr,
    )

    html_path = _resolve_html_path(args.html.strip() or None)
    if not html_path.is_file():
        _die(f"HTML file not found: {html_path}")

    try:
        html_body = html_path.read_text(encoding="utf-8")
    except OSError as exc:
        _die(f"could not read HTML file: {html_path} ({type(exc).__name__})")

    recipients = _parse_address_tokens(args.to)
    subject = (args.subject or _DEFAULT_SUBJECT).strip() or _DEFAULT_SUBJECT

    send_attempted, send_block_reason = _evaluate_send_gate(
        want_send=bool(args.send),
        confirm=args.confirm,
        recipients=recipients,
        html_exists=bool(html_body.strip()),
    )

    send_success = False
    error: str | None = None
    if send_attempted:
        send_success = bool(
            send_genie_email(
                html_body,
                subject,
                to_addrs_override=recipients,
            )
        )
        if not send_success:
            diag = last_send_diagnostic().strip()
            error = diag or "send_genie_email returned False"

    pwd_meta = last_password_resolution()
    kst = datetime.now(ZoneInfo("Asia/Seoul"))
    report = {
        **_HARNESS_META,
        "html_path": str(html_path.relative_to(_REPO) if html_path.is_relative_to(_REPO) else html_path),
        "subject": subject,
        "recipients": recipients,
        "owner_review_allowlist": sorted(OWNER_REVIEW_EMAIL_ALLOWLIST),
        "send_attempted": send_attempted,
        "send_success": send_success if send_attempted else False,
        "send_block_reason": send_block_reason,
        "smtp_configured": smtp_configured(),
        "smtp_host_set": bool(os.getenv("SMTP_HOST", "").strip()),
        "smtp_user_set": bool(os.getenv("SMTP_USER", "").strip()),
        "password_source": pwd_meta.get("source") or "",
        "password_file_exists": bool(pwd_meta.get("file_exists")),
        "html_char_len": len(html_body),
        "error": error,
        "report_created_at": kst.isoformat(),
        "cli_flags": {
            "send": bool(args.send),
            "confirm_provided": bool((args.confirm or "").strip()),
            "no_write_output": bool(args.no_write_output),
        },
    }

    report_json = json.dumps(report, ensure_ascii=False, indent=2)
    if args.no_write_output:
        print(report_json)
    else:
        stamp = kst.strftime("%Y%m%d_%H%M%S")
        out_path = _REPO / "output" / f"keysuri_owner_review_email_send_test_report_{stamp}.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(report_json + "\n", encoding="utf-8")
        report["report_path"] = str(out_path.relative_to(_REPO))
        print(json.dumps(report, ensure_ascii=False, indent=2))

    return 0 if (not send_attempted or send_success) else 1


if __name__ == "__main__":
    sys.exit(main())
