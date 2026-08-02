#!/usr/bin/env python3
"""Compare two pytest JUnit files by collected identity and exact outcome."""
from __future__ import annotations

import json
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path


def _node_id(case: ET.Element) -> str:
    return f"{case.get('classname', '')}::{case.get('name', '')}"


def _outcome(case: ET.Element) -> str:
    if case.find("failure") is not None or case.find("error") is not None:
        return "failed"
    skipped = case.find("skipped")
    if skipped is not None:
        return "xfailed" if skipped.get("type") == "pytest.xfail" else "skipped"
    return "passed"


def _profile(path: Path) -> tuple[Counter[str], Counter[tuple[str, str]], dict[str, int]]:
    root = ET.parse(path).getroot()
    identities: Counter[str] = Counter()
    outcomes: Counter[tuple[str, str]] = Counter()
    counts = {name: 0 for name in ("collected", "passed", "failed", "skipped", "xfailed")}
    for case in root.iter("testcase"):
        node_id = _node_id(case)
        outcome = _outcome(case)
        identities[node_id] += 1
        outcomes[(node_id, outcome)] += 1
        counts["collected"] += 1
        counts[outcome] += 1
    return identities, outcomes, counts


def _counter_diff(left: Counter, right: Counter) -> list[str]:
    result: list[str] = []
    for item, count in sorted((left - right).items(), key=lambda row: str(row[0])):
        rendered = "::".join(item) if isinstance(item, tuple) else item
        result.extend([rendered] * count)
    return result


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: compare_pytest_profiles.py DEFAULT_JUNIT HARNESS_JUNIT", file=sys.stderr)
        return 2

    default_ids, default_outcomes, default_counts = _profile(Path(sys.argv[1]))
    harness_ids, harness_outcomes, harness_counts = _profile(Path(sys.argv[2]))
    identity_match = default_ids == harness_ids
    outcome_match = identity_match and default_outcomes == harness_outcomes
    env_divergence = "NONE" if outcome_match else "DETECTED"

    for prefix, counts in (("DEFAULT_PROFILE", default_counts), ("HARNESS_PROFILE", harness_counts)):
        print(f"{prefix}_COLLECTED={counts['collected']}")
        print(f"{prefix}_PASSED={counts['passed']}")
        print(f"{prefix}_FAILED={counts['failed']}")
        print(f"{prefix}_SKIPPED={counts['skipped']}")
        print(f"{prefix}_XFAILED={counts['xfailed']}")
    print(f"PROFILE_NODE_IDENTITY_MATCH={'YES' if identity_match else 'NO'}")
    print(f"PROFILE_OUTCOME_MATCH={'YES' if outcome_match else 'NO'}")
    print(f"ENV_DIVERGENCE={env_divergence}")
    print(
        json.dumps(
            {
                "default_only_nodes": _counter_diff(default_ids, harness_ids),
                "harness_only_nodes": _counter_diff(harness_ids, default_ids),
                "default_only_outcomes": _counter_diff(default_outcomes, harness_outcomes),
                "harness_only_outcomes": _counter_diff(harness_outcomes, default_outcomes),
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if env_divergence == "NONE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
