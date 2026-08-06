#!/usr/bin/env python3
"""Read-only local inspection of owner-review failure events and recurrence counters.

No secrets. No network. No writes. Exit non-zero on malformed input.

Examples:
  python3 scripts/inspect_owner_review_ops_local.py \\
    --failure-log tests/fixtures/owner_review_ops/sample_failure_events.jsonl \\
    --artifacts-dir tests/fixtures/owner_review_ops/artifacts \\
    --group-by program_id,first_failed_stage,issue_code
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from keysuri_recurrence_metrics import (  # noqa: E402
    RECURRENCE_COUNTER_NAMES,
    aggregate_recurrence_counters,
    recurrence_counters_for_run,
)
from owner_review_failure_events import OWNER_REVIEW_RUN_FAILED_EVENT  # noqa: E402


def _load_json_object(path: Path) -> Mapping[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"malformed_json:{path}:{exc}") from exc
    if not isinstance(data, Mapping):
        raise ValueError(f"malformed_json_object:{path}")
    return data


def load_failure_events(paths: Sequence[Path]) -> List[Dict[str, Any]]:
    events: List[Dict[str, Any]] = []
    for path in paths:
        if not path.exists():
            raise ValueError(f"missing_path:{path}")
        if path.is_dir():
            for child in sorted(path.rglob("*")):
                if child.is_file() and child.suffix in {".json", ".jsonl", ".log", ".txt"}:
                    events.extend(load_failure_events([child]))
            continue
        text = path.read_text(encoding="utf-8")
        if path.suffix == ".json":
            payload = json.loads(text)
            if isinstance(payload, list):
                for item in payload:
                    if not isinstance(item, Mapping):
                        raise ValueError(f"malformed_event_list:{path}")
                    events.append(dict(item))
            elif isinstance(payload, Mapping):
                events.append(dict(payload))
            else:
                raise ValueError(f"malformed_json:{path}")
            continue
        for line_no, raw in enumerate(text.splitlines(), start=1):
            line = raw.strip()
            if not line:
                continue
            # Accept bare JSON lines, or prefixed textPayload containing the JSON object.
            start = line.find("{")
            end = line.rfind("}")
            if start < 0 or end <= start:
                # Non-JSON noise is ignored; a brace-looking line must parse.
                if "{" in line or "}" in line:
                    raise ValueError(f"malformed_log_line:{path}:{line_no}")
                continue
            try:
                obj = json.loads(line[start : end + 1])
            except json.JSONDecodeError as exc:
                raise ValueError(f"malformed_log_line:{path}:{line_no}:{exc}") from exc
            if not isinstance(obj, Mapping):
                raise ValueError(f"malformed_log_line:{path}:{line_no}")
            if str(obj.get("event") or "") != OWNER_REVIEW_RUN_FAILED_EVENT:
                continue
            events.append(dict(obj))
    return events


def load_artifact_records(paths: Sequence[Path]) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    for path in paths:
        if not path.exists():
            raise ValueError(f"missing_path:{path}")
        if path.is_dir():
            for child in sorted(path.rglob("*.json")):
                records.append(dict(_load_json_object(child)))
            continue
        records.append(dict(_load_json_object(path)))
    return records


def group_events(
    events: Iterable[Mapping[str, Any]],
    *,
    keys: Sequence[str],
) -> Dict[str, int]:
    counts: Counter[str] = Counter()
    for event in events:
        if "issue_code" in keys:
            codes = list(event.get("issue_codes") or []) or [""]
            for code in codes:
                parts = []
                for key in keys:
                    if key == "issue_code":
                        parts.append(f"issue_code={code}")
                    else:
                        parts.append(f"{key}={event.get(key)}")
                counts["|".join(parts)] += 1
        else:
            parts = [f"{key}={event.get(key)}" for key in keys]
            counts["|".join(parts)] += 1
    return dict(sorted(counts.items()))


def build_report(
    *,
    events: Sequence[Mapping[str, Any]],
    artifacts: Sequence[Mapping[str, Any]],
    group_by: Sequence[str],
) -> Dict[str, Any]:
    counters = [recurrence_counters_for_run(rec) for rec in artifacts]
    aggregated = aggregate_recurrence_counters(artifacts)
    revisions = sorted(
        {
            str(ev.get("revision") or "").strip()
            for ev in events
            if str(ev.get("revision") or "").strip()
        }
        | {
            str(rec.get("revision") or rec.get("git_commit") or "").strip()
            for rec in artifacts
            if str(rec.get("revision") or rec.get("git_commit") or "").strip()
        }
    )
    return {
        "event_name": OWNER_REVIEW_RUN_FAILED_EVENT,
        "event_count": len(events),
        "artifact_count": len(artifacts),
        "group_by": list(group_by),
        "grouped_events": group_events(events, keys=group_by),
        "recurrence_counter_names": list(RECURRENCE_COUNTER_NAMES),
        "recurrence_counters_aggregated": aggregated,
        "recurrence_counters_per_artifact": counters,
        "revisions": revisions,
        "side_effect_free": True,
        "network": False,
        "writes": False,
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Inspect local owner-review failure events and recurrence counters (read-only)."
    )
    parser.add_argument("--failure-log", action="append", default=[], help="JSON/JSONL/log path(s)")
    parser.add_argument("--artifacts-dir", action="append", default=[], help="Artifact JSON path(s) or dirs")
    parser.add_argument(
        "--group-by",
        default="program_id,first_failed_stage,issue_code",
        help="Comma-separated group keys",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON report on stdout")
    args = parser.parse_args(list(argv) if argv is not None else None)

    try:
        event_paths = [Path(p) for p in args.failure_log]
        artifact_paths = [Path(p) for p in args.artifacts_dir]
        if not event_paths and not artifact_paths:
            raise ValueError("missing_input:provide --failure-log and/or --artifacts-dir")
        events = load_failure_events(event_paths) if event_paths else []
        artifacts = load_artifact_records(artifact_paths) if artifact_paths else []
        group_by = [part.strip() for part in str(args.group_by).split(",") if part.strip()]
        if not group_by:
            raise ValueError("malformed_group_by")
        report = build_report(events=events, artifacts=artifacts, group_by=group_by)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001 — operator-facing local tool
        print(f"ERROR: unexpected:{exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"events={report['event_count']} artifacts={report['artifact_count']}")
        print("grouped_events:")
        for key, count in report["grouped_events"].items():
            print(f"  {count}\t{key}")
        print("recurrence_counters_aggregated:")
        for name in RECURRENCE_COUNTER_NAMES:
            print(f"  {name}={report['recurrence_counters_aggregated'].get(name, 0)}")
        if report["revisions"]:
            print("revisions: " + ", ".join(report["revisions"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
