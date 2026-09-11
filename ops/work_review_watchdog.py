#!/usr/bin/env python3
"""Independent missed-review watchdog for the local Work reviewer.

This process never reviews content, calls a model, changes production or sends
customer mail.  It only checks the finite slot manifest and create-exclusive
shadow evidence, writes a deduplicated exception packet, and can emit a local
macOS notification.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional


VERDICTS = {
    "PASS",
    "HOLD_ANOMALY",
    "HOLD_INCOMPLETE",
    "REVIEW_UNAVAILABLE",
    "STATE_CONFLICT",
}

PROVISIONAL_WAITING_VERDICT = "HOLD_INCOMPLETE"
WAITING_SEND_STATES = {"WAITING", "WINDOW_WAITING_INCOMPLETE"}
REQUIRED_CHECK_GROUPS = (
    ("content",),
    ("sources",),
    ("images",),
    ("email_render", "render"),
    ("customer_render",),
    ("run_identity",),
    ("delivery_readiness",),
)


class WatchdogError(RuntimeError):
    pass


def _instant(value: Any) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise WatchdogError("timezone_required")
    return parsed.astimezone(timezone.utc)


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _signature(packet: Mapping[str, Any]) -> str:
    stable = {
        key: packet.get(key)
        for key in (
            "slot_id",
            "product",
            "publication_date",
            "verdict",
            "problem_code",
            "run_id",
        )
    }
    return hashlib.sha256(_canonical(stable).encode("utf-8")).hexdigest()


def _evidence_for_slot(evidence_dir: Path, slot_id: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    if not evidence_dir.exists():
        return rows
    for path in sorted(evidence_dir.glob("*.json")):
        try:
            row = _load_json(path)
        except Exception:
            continue
        if isinstance(row, dict) and row.get("slot_id") == slot_id:
            row = dict(row)
            row["_evidence_file"] = str(path)
            rows.append(row)
    return rows


def _evidence_time(row: Mapping[str, Any]) -> datetime:
    for key in ("reviewed_at", "observed_at", "created_at"):
        if row.get(key):
            try:
                return _instant(row[key])
            except Exception:
                pass
    path = Path(str(row.get("_evidence_file") or ""))
    if path.exists():
        return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    return datetime.min.replace(tzinfo=timezone.utc)


def _verdict(row: Mapping[str, Any]) -> str:
    return str(row.get("overall_verdict") or row.get("verdict") or "").strip().upper()


def _pass_is_complete(row: Mapping[str, Any]) -> bool:
    checks = row.get("checks") or row.get("class_verdicts")
    if not isinstance(checks, Mapping):
        return False
    for aliases in REQUIRED_CHECK_GROUPS:
        value = next((checks[name] for name in aliases if name in checks), None)
        if isinstance(value, Mapping):
            value = value.get("verdict") or value.get("status")
        if str(value or "").strip().upper() != "PASS":
            return False
    if row.get("approval_authority") not in {None, "NONE"}:
        return False
    if row.get("customer_send_authorized") not in {None, False}:
        return False
    return True


def _is_provisional_waiting(row: Mapping[str, Any]) -> bool:
    if _verdict(row) != PROVISIONAL_WAITING_VERDICT:
        return False
    send_state = str(
        row.get("customer_send_state")
        or row.get("customer_delivery_status")
        or row.get("state")
        or ""
    ).upper()
    if send_state in WAITING_SEND_STATES:
        return True
    reason_codes = row.get("reason_codes")
    if isinstance(reason_codes, list):
        return "NO_MATCHING_OWNER_REVIEW_MAIL" in {
            str(code).upper() for code in reason_codes
        }
    return False


def _is_observation(row: Mapping[str, Any]) -> bool:
    record_type = str(row.get("record_type") or "").strip().lower()
    if record_type == "observation":
        return True
    observation_status = str(row.get("observation_status") or "").strip().upper()
    if observation_status == "WAITING":
        return True
    # Compatibility for the malformed pre-contract files already written by
    # the reviewer. Explicit final records are never reclassified by legacy
    # state/reason heuristics.
    if record_type == "final":
        return False
    return _is_provisional_waiting(row)


def _is_final(row: Mapping[str, Any]) -> bool:
    record_type = str(row.get("record_type") or "").strip().lower()
    if record_type not in {"", "final"}:
        return False
    return _verdict(row) in VERDICTS and not _is_observation(row)


def _packet(slot: Mapping[str, Any], *, verdict: str, problem_code: str,
            now: datetime, evidence: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    run_id = str((evidence or {}).get("run_id") or "")
    send_state = str((evidence or {}).get("customer_send_state") or
                     (evidence or {}).get("customer_delivery_status") or "UNKNOWN")
    return {
        "schema_version": 1,
        "slot_id": str(slot.get("slot_id") or ""),
        "product": str(slot.get("product") or ""),
        "publication_date": str(slot.get("publication_date") or ""),
        "run_id": run_id,
        "verdict": verdict,
        "problem_code": problem_code,
        "detected_at": now.astimezone(timezone.utc).isoformat(),
        "what_happened": problem_code,
        "why_it_matters": "A missing or non-PASS Work review cannot authorize delegated delivery.",
        "what_was_already_done": "The independent watchdog checked the finite manifest and immutable local evidence.",
        "current_send_state": send_state,
        "recommended_action": "Keep delegated delivery OFF and inspect the exact Work/Gmail/evidence failure.",
        "owner_decision_required": False,
        "customer_send_authorized": False,
        "approval_authority": "NONE",
        "supporting_evidence": [str((evidence or {}).get("_evidence_file") or "")],
    }


def inspect_slots(*, manifest: Mapping[str, Any], evidence_dir: Path,
                  now: datetime) -> Dict[str, Any]:
    if now.tzinfo is None or now.utcoffset() is None:
        raise WatchdogError("now_timezone_required")
    slots = manifest.get("slots")
    if not isinstance(slots, list):
        raise WatchdogError("manifest_slots_missing")
    pending: List[str] = []
    complete: List[str] = []
    skipped: List[str] = []
    exceptions: List[Dict[str, Any]] = []
    current = now.astimezone(timezone.utc)
    for slot in slots:
        if not isinstance(slot, Mapping) or not slot.get("slot_id"):
            raise WatchdogError("manifest_slot_invalid")
        slot_id = str(slot["slot_id"])
        if slot.get("watchdog_monitor", True) is False:
            skipped.append(slot_id)
            continue
        windows = slot.get("windows_kst")
        if not isinstance(windows, list) or not windows:
            raise WatchdogError("manifest_windows_missing:" + slot_id)
        deadline = max(_instant(value) for value in windows)
        rows = _evidence_for_slot(evidence_dir, slot_id)
        final_rows = [row for row in rows if _is_final(row)]
        wait_rows = [row for row in rows if _is_observation(row)]
        evidence = max(final_rows, key=_evidence_time) if final_rows else None
        if evidence is not None:
            verdict = _verdict(evidence)
            if verdict == "PASS" and _pass_is_complete(evidence):
                complete.append(slot_id)
                continue
            if verdict == "PASS":
                exceptions.append(_packet(slot, verdict="HOLD_INCOMPLETE",
                    problem_code="MALFORMED_PASS_EVIDENCE", now=current,
                    evidence=evidence))
            else:
                reasons = evidence.get("reason_codes") or []
                problem = str(reasons[0]) if isinstance(reasons, list) and reasons else verdict
                exceptions.append(_packet(slot, verdict=verdict,
                    problem_code=problem, now=current, evidence=evidence))
            continue
        pending_wait = max(wait_rows, key=_evidence_time) if wait_rows else None
        if pending_wait is not None:
            if current > deadline:
                reasons = pending_wait.get("reason_codes") or []
                problem = (
                    str(reasons[0])
                    if isinstance(reasons, list) and reasons else
                    "NO_MATCHING_OWNER_REVIEW_MAIL"
                )
                exceptions.append(_packet(slot, verdict="REVIEW_UNAVAILABLE",
                    problem_code=problem, now=current,
                    evidence=pending_wait))
            else:
                pending.append(slot_id)
            continue
        if current > deadline:
            exceptions.append(_packet(slot, verdict="REVIEW_UNAVAILABLE",
                problem_code="MISSING_REVIEW_EVIDENCE_AFTER_DEADLINE", now=current))
        else:
            pending.append(slot_id)
    return {
        "checked_at": current.isoformat(),
        "pending_slots": pending,
        "complete_slots": complete,
        "skipped_slots": skipped,
        "exceptions": exceptions,
    }


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _write_once(path: Path, value: Any) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return False
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    return True


def macos_notification(packet: Mapping[str, Any]) -> None:
    title = "GENIE Work 검수 예외"
    message = "%s · %s" % (packet.get("product") or "unknown", packet.get("problem_code") or "exception")
    escape = lambda value: str(value).replace("\\", "\\\\").replace('"', '\\"')
    script = 'display notification "%s" with title "%s"' % (escape(message), escape(title))
    subprocess.run(["/usr/bin/osascript", "-e", script], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def run_watchdog(*, manifest_path: Path, evidence_dir: Path, state_path: Path,
                 report_dir: Path, now: datetime,
                 notifier: Optional[Callable[[Mapping[str, Any]], None]] = None) -> Dict[str, Any]:
    lock_path = state_path.with_suffix(state_path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        manifest = _load_json(manifest_path)
        result = inspect_slots(manifest=manifest, evidence_dir=evidence_dir, now=now)
        try:
            state = _load_json(state_path) if state_path.exists() else {"notified": {}}
        except Exception:
            raise WatchdogError("watchdog_state_invalid")
        notified = state.setdefault("notified", {})
        new_packets = []
        for packet in result["exceptions"]:
            signature = _signature(packet)
            packet["exception_signature"] = signature
            if signature in notified:
                continue
            report_path = report_dir / (signature + ".json")
            if not _write_once(report_path, packet):
                continue
            if notifier is not None:
                notifier(packet)
            notified[signature] = {
                "reported_at": result["checked_at"],
                "report_path": str(report_path),
            }
            new_packets.append(packet)
        state["last_checked_at"] = result["checked_at"]
        _atomic_json(state_path, state)
        result["new_exceptions"] = new_packets
        result["new_exception_count"] = len(new_packets)
        return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--evidence-dir", required=True, type=Path)
    parser.add_argument("--state", required=True, type=Path)
    parser.add_argument("--report-dir", required=True, type=Path)
    parser.add_argument("--now", help="ISO-8601 override for tests/manual checks")
    parser.add_argument("--notify", action="store_true")
    return parser


def main(argv: Optional[Iterable[str]] = None) -> int:
    args = _parser().parse_args(argv)
    now = _instant(args.now) if args.now else datetime.now(timezone.utc)
    try:
        result = run_watchdog(
            manifest_path=args.manifest,
            evidence_dir=args.evidence_dir,
            state_path=args.state,
            report_dir=args.report_dir,
            now=now,
            notifier=macos_notification if args.notify else None,
        )
    except Exception as exc:
        print(json.dumps({"watchdog_ok": False, "error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps({"watchdog_ok": True, **result}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
