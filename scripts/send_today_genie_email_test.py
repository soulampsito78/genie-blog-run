#!/usr/bin/env python3
"""
Local Today_Geenee owner-review MIME integration harness (CID inline + attachments).

This is NOT customer delivery. It does not call approve_run(), does not build
review_passed customer final HTML, and must not be used as sent_archived or
customer delivery proof.

Default mode is report-only:
  - Does not send email.
  - Does not update static/email/GENIE_EMAIL_today_genie_*_latest.jpg.
  - May write JSON/HTML artifacts under output/** unless --no-write-output.

Real SMTP send requires ALL of:
  --send
  GENIE_EMAIL_SEND_TEST=1 (or true/yes)
  --confirm SEND
  explicit recipients via --to and/or GENIE_EMAIL_TEST_TO (owner allowlist only
  unless --allow-non-owner-test)

Publishing static/email latest assets requires --publish-latest-assets.

Usage:
  python3 scripts/send_today_genie_email_test.py \\
    --preview-json output/today_genie_preview_0420_1333.json

Image paths default to preview JSON image_run / artifacts; override with --top-image / --bottom-image.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
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
    last_send_trace,
    send_genie_email,
    smtp_configured,
)
from main import build_today_genie_email_html_for_cid_mime_send  # noqa: E402
from publishing_policy import OWNER_REVIEW_EMAIL_ALLOWLIST  # noqa: E402
from renderers import today_genie_email_inline_cid_pair  # noqa: E402

STABLE_ATTACH_TOP = "GENIE_EMAIL_today_genie_top.jpg"
STABLE_ATTACH_BOTTOM = "GENIE_EMAIL_today_genie_bottom.jpg"
_SEND_CONFIRM_PHRASE = "SEND"
_ENV_SEND_TEST_TRUTHY = frozenset({"1", "true", "True", "yes", "YES"})
_HARNESS_META = {
    "harness_kind": "owner_review_mime_integration",
    "not_customer_delivery": True,
    "not_approve_run": True,
    "not_review_passed_path": True,
    "not_sent_archived_proof": True,
}


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _latest_preview_json() -> Path:
    previews = sorted((_REPO / "output").glob("today_genie_preview_*.json"), key=lambda p: p.stat().st_mtime)
    if not previews:
        raise FileNotFoundError("No today_genie_preview_*.json found under output/")
    return previews[-1]


def _publish_latest_email_assets(top_fs: str, bot_fs: str) -> tuple[str, str]:
    """Mirror selected same-run images into canonical static/email latest assets."""
    email_dir = _REPO / "static" / "email"
    email_dir.mkdir(parents=True, exist_ok=True)
    top_latest = email_dir / "GENIE_EMAIL_today_genie_top_latest.jpg"
    bot_latest = email_dir / "GENIE_EMAIL_today_genie_bottom_latest.jpg"
    shutil.copyfile(top_fs, top_latest)
    shutil.copyfile(bot_fs, bot_latest)
    return str(top_latest), str(bot_latest)


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


def _parse_env_test_recipients() -> list[str]:
    raw = os.getenv("GENIE_EMAIL_TEST_TO", "").strip()
    if not raw or ";" in raw or "\n" in raw:
        return []
    return _parse_address_tokens([raw])


def _owner_allowlist_recipients() -> list[str]:
    return sorted(OWNER_REVIEW_EMAIL_ALLOWLIST)


def _resolve_recipients(
    cli_to: list[str],
) -> tuple[list[str], list[str], str, str | None]:
    """
    Returns (report_preview_recipients, send_recipients, resolution_source, validation_error).

    Send recipients require explicit --to and/or GENIE_EMAIL_TEST_TO.
    Report preview falls back to owner allowlist when no explicit list is given.
    """
    explicit = _parse_address_tokens(cli_to)
    env_addrs = _parse_env_test_recipients()

    if explicit:
        report_preview = explicit
        send_recipients = explicit
        source = "cli --to"
    elif env_addrs:
        report_preview = env_addrs
        send_recipients = env_addrs
        source = "GENIE_EMAIL_TEST_TO"
    else:
        report_preview = _owner_allowlist_recipients()
        send_recipients = []
        source = "owner_allowlist_preview_only"

    for addr in send_recipients or report_preview:
        if "@" not in addr or not addr.strip():
            return report_preview, send_recipients, source, f"invalid recipient address: {addr!r}"

    return report_preview, send_recipients, source, None


def _recipient_allowlist_ok(recipients: list[str], *, allow_non_owner: bool) -> tuple[bool, str | None]:
    if not recipients:
        return False, "no recipients resolved"
    if allow_non_owner:
        return True, None
    blocked = [r for r in recipients if r.strip().lower() not in OWNER_REVIEW_EMAIL_ALLOWLIST]
    if blocked:
        return False, (
            "recipient(s) outside OWNER_REVIEW_EMAIL_ALLOWLIST: "
            + ", ".join(blocked)
            + " (pass --allow-non-owner-test to override)"
        )
    return True, None


def _env_send_test_gate_ok() -> bool:
    return os.getenv("GENIE_EMAIL_SEND_TEST", "").strip() in _ENV_SEND_TEST_TRUTHY


def _evaluate_send_gate(
    *,
    want_send: bool,
    confirm: str | None,
    send_recipients: list[str],
    allow_non_owner: bool,
) -> tuple[bool, str | None]:
    if not want_send:
        return False, "send disabled (default report-only; pass --send to attempt SMTP)"
    if not _env_send_test_gate_ok():
        return False, "GENIE_EMAIL_SEND_TEST not set to an allowed truthy value"
    if (confirm or "").strip() != _SEND_CONFIRM_PHRASE:
        return False, f"--confirm {_SEND_CONFIRM_PHRASE} is required for --send"
    if not send_recipients:
        return False, "no explicit send recipients (--to and/or GENIE_EMAIL_TEST_TO required)"
    ok, reason = _recipient_allowlist_ok(send_recipients, allow_non_owner=allow_non_owner)
    if not ok:
        return False, reason
    if not smtp_configured():
        return False, "SMTP not configured (SMTP_HOST, SMTP_USER, and password required)"
    return True, None


def _resolve_paths(preview: dict, top_arg: str | None, bot_arg: str | None) -> tuple[str, str]:
    if top_arg and bot_arg:
        return str(_REPO / top_arg), str(_REPO / bot_arg)
    ir = preview.get("image_run") or {}
    art = preview.get("artifacts") or {}
    top = (ir.get("top") or {}).get("path") or art.get("top_image")
    bot = (ir.get("bottom") or {}).get("path") or art.get("bottom_image")
    if not top or not bot:
        raise ValueError(
            "Could not resolve top/bottom image paths from preview JSON; pass --top-image and --bottom-image."
        )
    return str(_REPO / top), str(_REPO / bot)


def _build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description=(
            "Today_Geenee owner-review MIME harness (report-only by default; not customer delivery)."
        )
    )
    ap.add_argument(
        "--preview-json",
        type=Path,
        required=False,
        help="Path to today_genie preview JSON (repo-relative or absolute). Defaults to latest preview.",
    )
    ap.add_argument("--top-image", default="", help="Override top JPEG path (repo-relative).")
    ap.add_argument("--bottom-image", default="", help="Override bottom JPEG path (repo-relative).")
    ap.add_argument(
        "--report-only",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Report-only mode (default). Use --no-report-only only with --send for SMTP attempts.",
    )
    ap.add_argument(
        "--send",
        action="store_true",
        default=False,
        help="Attempt real SMTP send (requires env gate, --confirm SEND, explicit recipients).",
    )
    ap.add_argument(
        "--publish-latest-assets",
        action="store_true",
        default=False,
        help="Copy run images to static/email/*_latest.jpg (off by default).",
    )
    ap.add_argument(
        "--to",
        action="append",
        default=[],
        metavar="EMAIL",
        help="Recipient address(es); repeatable or comma-separated. Preferred explicit send target.",
    )
    ap.add_argument(
        "--confirm",
        default="",
        help=f'Confirmation phrase required for --send (must be exactly "{_SEND_CONFIRM_PHRASE}").',
    )
    ap.add_argument(
        "--allow-non-owner-test",
        action="store_true",
        default=False,
        help="Allow recipients outside OWNER_REVIEW_EMAIL_ALLOWLIST when sending.",
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
        "OWNER MIME HARNESS — default report-only; SMTP only with --send + "
        "GENIE_EMAIL_SEND_TEST + --confirm SEND + explicit recipients.",
        file=sys.stderr,
    )

    if args.preview_json:
        preview_path = args.preview_json
        if not preview_path.is_file():
            preview_path = _REPO / preview_path
        if not preview_path.is_file():
            _die(f"preview json not found: {args.preview_json}")
    else:
        preview_path = _latest_preview_json()

    stamp = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%m%d_%H%M")
    report_path = _REPO / "output" / f"today_genie_email_send_test_report_{stamp}.json"
    html_out_path = _REPO / "output" / f"today_genie_email_body_send_test_{stamp}.html"

    raw = json.loads(preview_path.read_text(encoding="utf-8"))
    data = raw.get("data") if isinstance(raw.get("data"), dict) else {}
    block_reason: str | None = None
    if not data:
        block_reason = "preview JSON missing data object"

    report_preview_recipients, send_recipients, recipient_source, recipient_error = _resolve_recipients(
        args.to
    )
    if recipient_error:
        block_reason = block_reason or f"recipient_resolution: {recipient_error}"

    top_fs, bot_fs = "", ""
    cid_top, cid_bottom = today_genie_email_inline_cid_pair()
    published_top, published_bottom = "", ""
    static_publish_attempted = False
    static_publish_reason: str | None = None

    if not block_reason:
        try:
            top_fs, bot_fs = _resolve_paths(raw, args.top_image or None, args.bottom_image or None)
        except Exception as e:  # noqa: BLE001
            block_reason = f"path_resolution: {type(e).__name__}: {e}"
        else:
            for label, p in (("top", top_fs), ("bottom", bot_fs)):
                if not os.path.isfile(p):
                    block_reason = f"missing {label} image file: {p}"
                    break

        if not block_reason and args.publish_latest_assets:
            static_publish_attempted = True
            published_top, published_bottom = _publish_latest_email_assets(top_fs, bot_fs)
        elif not block_reason:
            static_publish_reason = (
                "static/email latest assets not updated (pass --publish-latest-assets to copy)"
            )

    email_html = ""
    if not block_reason:
        run_meta = raw.get("run_meta") if isinstance(raw.get("run_meta"), dict) else {}
        validation_result = str(run_meta.get("validation_result") or "pass")
        # Owner/pre-approval MIME HTML only — not approve_run() customer review_passed HTML.
        email_html = build_today_genie_email_html_for_cid_mime_send(
            data,
            validation_result=validation_result,
        )

    send_allowed, send_block_reason = _evaluate_send_gate(
        want_send=args.send,
        confirm=args.confirm or None,
        send_recipients=send_recipients,
        allow_non_owner=args.allow_non_owner_test,
    )
    send_attempted = bool(send_allowed and not block_reason)

    subject = ""
    err: str | None = None
    ok = False
    if send_attempted:
        drafts = data.get("channel_drafts") if isinstance(data.get("channel_drafts"), dict) else {}
        subject = os.getenv("GENIE_EMAIL_TEST_SUBJECT", "").strip()
        if not subject:
            subject = f"[GENIE test] {drafts.get('email_subject') or data.get('title') or 'today_genie'}"

        print(
            f"SMTP send attempt → recipients: {', '.join(send_recipients)}",
            file=sys.stderr,
        )

        inline_parts = [
            (top_fs, cid_top, STABLE_ATTACH_TOP),
            (bot_fs, cid_bottom, STABLE_ATTACH_BOTTOM),
        ]
        attach_parts = [
            (top_fs, STABLE_ATTACH_TOP),
            (bot_fs, STABLE_ATTACH_BOTTOM),
        ]

        try:
            ok = send_genie_email(
                email_html,
                subject,
                inline_jpeg_parts=inline_parts,
                attachment_jpeg_parts=attach_parts,
                test_to_addrs=send_recipients,
            )
            diag = last_send_diagnostic()
            if not ok and diag:
                err = diag
        except Exception as e:  # noqa: BLE001
            err = f"{type(e).__name__}: {e}"
    elif send_block_reason:
        err = send_block_reason

    send_trace = last_send_trace()
    sent_html = str(send_trace.get("mime_html_text") or "")
    check_html = sent_html if sent_html else email_html

    def _idx(token: str) -> int:
        return check_html.find(token) if check_html else -1

    idx_top_img = _idx('cid:genie.today.top@genie-email.local')
    idx_label = _idx("[장전 브리핑]")
    idx_title = _idx(str(data.get("title", ""))) if check_html else -1
    idx_summary = _idx("오늘의 핵심 요약")
    idx_cue = _idx("오늘 아침 시장을 움직일 3가지는 아래에 이어집니다. 계속 읽기 ↓")
    idx_top3 = _idx("오늘의 TOP 3 뉴스 브리핑")
    idx_admin = _idx('id="genie-operational-handoff"')
    idx_bottom_img = _idx('cid:genie.today.bottom@genie-email.local')

    deterministic_checks = {
        "top_image_present": idx_top_img >= 0,
        "label_before_admin": (idx_label >= 0 and idx_admin >= 0 and idx_label < idx_admin),
        "title_before_admin": (idx_title >= 0 and idx_admin >= 0 and idx_title < idx_admin),
        "summary_before_admin": (idx_summary >= 0 and idx_admin >= 0 and idx_summary < idx_admin),
        "cue_before_admin": (idx_cue >= 0 and idx_admin >= 0 and idx_cue < idx_admin),
        "top3_before_admin": (idx_top3 >= 0 and idx_admin >= 0 and idx_top3 < idx_admin),
        "admin_after_editorial": (idx_admin > idx_top3 >= 0),
        "bottom_image_last": (idx_bottom_img > idx_admin >= 0),
    }

    smtp_host_used = os.getenv("SMTP_HOST", "").strip()
    smtp_port_used = os.getenv("SMTP_PORT", "").strip() or "587"
    smtp_user_used = os.getenv("SMTP_USER", "").strip()
    from_used = os.getenv("EMAIL_FROM", "").strip() or smtp_user_used

    report = {
        **_HARNESS_META,
        "mode": "smtp_send" if send_attempted else "report_only",
        "report_only": not send_attempted,
        "send_attempted": send_attempted,
        "send_block_reason": send_block_reason,
        "static_publish_attempted": static_publish_attempted,
        "static_publish_reason": static_publish_reason,
        "ok": (ok and err is None) if send_attempted else (err is None and not block_reason),
        "blocked_reason": block_reason,
        "smtp_host_used": smtp_host_used,
        "smtp_port_used": smtp_port_used,
        "smtp_user_used": smtp_user_used,
        "from_used": from_used,
        "recipient_resolution_source": recipient_source,
        "report_preview_recipients": report_preview_recipients,
        "send_recipients_resolved": send_recipients,
        "recipient_used": ", ".join(send_recipients) if send_attempted else "",
        "owner_review_allowlist": sorted(OWNER_REVIEW_EMAIL_ALLOWLIST),
        "allow_non_owner_test": args.allow_non_owner_test,
        "actual_to_header": send_trace.get("to_header", ""),
        "actual_cc_header": send_trace.get("cc_header", ""),
        "actual_bcc_header": send_trace.get("bcc_header", ""),
        "actual_envelope_to": send_trace.get("envelope_to", []),
        "actual_recipient_count": len(send_trace.get("envelope_to", []) or []),
        "mime_inline_jpeg_count": (
            2 if (not block_reason and top_fs and bot_fs and "cid:" in email_html) else 0
        ),
        "mime_attachment_jpeg_count": (2 if (not block_reason and top_fs and bot_fs) else 0),
        "smtp_host_set": bool(os.getenv("SMTP_HOST", "").strip()),
        "smtp_user_set": bool(os.getenv("SMTP_USER", "").strip()),
        "smtp_password_env_hint": bool(
            os.getenv("SMTP_PASSWORD", "").strip()
            or os.getenv("SMTP_PASSWORD_FILE", "").strip()
            or os.getenv("SMTP_APP_PASSWORD", "").strip()
        ),
        "smtp_ready_at_send": smtp_configured(),
        "password_resolution": last_password_resolution(),
        "mime_html_byte_identity": send_trace.get("mime_html_byte_identical", False),
        "mime_html_sha256": send_trace.get("mime_html_sha256", ""),
        "intended_html_sha256": send_trace.get("intended_html_sha256", ""),
        "mime_html_bytes_len": send_trace.get("mime_html_bytes_len", 0),
        "intended_html_bytes_len": send_trace.get("intended_html_bytes_len", 0),
        "deterministic_first_screen_checks": deterministic_checks,
        "deterministic_order_indices": {
            "top_image": idx_top_img,
            "label": idx_label,
            "title": idx_title,
            "summary_heading": idx_summary,
            "anticipation_cue": idx_cue,
            "top3_heading": idx_top3,
            "admin_box": idx_admin,
            "bottom_image": idx_bottom_img,
        },
        "deterministic_checks_source_html": "mime_send_trace" if sent_html else "built_email_html",
        "last_send_diagnostic": last_send_diagnostic(),
        "recipient_env": "GENIE_EMAIL_TEST_TO",
        "subject": subject,
        "preview_json": str(preview_path),
        "top_image": top_fs,
        "bottom_image": bot_fs,
        "canonical_latest_top_image": published_top,
        "canonical_latest_bottom_image": published_bottom,
        "generated_top_sha256": _sha256_file(top_fs) if top_fs and os.path.isfile(top_fs) else "",
        "generated_bottom_sha256": _sha256_file(bot_fs) if bot_fs and os.path.isfile(bot_fs) else "",
        "canonical_latest_top_sha256": _sha256_file(published_top) if published_top and os.path.isfile(published_top) else "",
        "canonical_latest_bottom_sha256": _sha256_file(published_bottom) if published_bottom and os.path.isfile(published_bottom) else "",
        "inline_cids": [cid_top, cid_bottom],
        "attachment_filenames": [STABLE_ATTACH_TOP, STABLE_ATTACH_BOTTOM],
        "inline_input_hashes": send_trace.get("inline_input_hashes", []),
        "attachment_input_hashes": send_trace.get("attachment_input_hashes", []),
        "identity_chain_checks": {},
        "html_char_len": len(email_html),
        "admin_box_present": ('id="genie-operational-handoff"' in email_html),
        "cid_inline_html_built": bool(email_html) and "cid:" in email_html,
        "send_returned_true": ok,
        "auth_result": "success" if ok else ("not_attempted" if not send_attempted else "failed"),
        "error": err,
        "cli_flags": {
            "send": args.send,
            "report_only": args.report_only,
            "publish_latest_assets": args.publish_latest_assets,
            "no_write_output": args.no_write_output,
            "confirm_provided": bool((args.confirm or "").strip()),
        },
        "output_artifacts_written": not args.no_write_output,
    }
    gt = report["generated_top_sha256"]
    gb = report["generated_bottom_sha256"]
    ct = report["canonical_latest_top_sha256"]
    cb = report["canonical_latest_bottom_sha256"]
    inline_hashes = [str(x.get("sha256") or "") for x in report["inline_input_hashes"] if isinstance(x, dict)]
    attach_hashes = [str(x.get("sha256") or "") for x in report["attachment_input_hashes"] if isinstance(x, dict)]
    report["identity_chain_checks"] = {
        "generated_equals_canonical_latest_top": bool(gt and ct and gt == ct),
        "generated_equals_canonical_latest_bottom": bool(gb and cb and gb == cb),
        "generated_top_in_inline_hashes": bool(gt and gt in inline_hashes),
        "generated_bottom_in_inline_hashes": bool(gb and gb in inline_hashes),
        "generated_top_in_attachment_hashes": bool(gt and gt in attach_hashes),
        "generated_bottom_in_attachment_hashes": bool(gb and gb in attach_hashes),
        "mapping_layer_identity_closed": bool(
            gt and gb and ct and cb
            and gt == ct and gb == cb
            and gt in inline_hashes and gb in inline_hashes
            and gt in attach_hashes and gb in attach_hashes
        ),
        "remaining_non_mapping_risk": (
            "cache-layer only possible (fixed CID tokens / stable attachment names); "
            "not a generated->mapped file identity gap"
        ),
    }

    payload = {**report, "report_path": str(report_path) if not args.no_write_output else ""}
    if args.no_write_output:
        print(json.dumps(payload, ensure_ascii=False))
    else:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        html_out_path.write_text(email_html, encoding="utf-8")
        report["email_body_html_artifact"] = str(html_out_path)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({**report, "report_path": str(report_path)}, ensure_ascii=False))

    if send_attempted:
        return 0 if report["ok"] else 1
    return 0 if not block_reason else 1


if __name__ == "__main__":
    raise SystemExit(main())
