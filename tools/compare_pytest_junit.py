#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def failures(path: Path) -> set[str]:
    root = ET.parse(path).getroot()
    result = set()
    for case in root.iter("testcase"):
        if case.find("failure") is not None or case.find("error") is not None:
            result.add(f"{case.get('classname')}::{case.get('name')}")
    return result


def counts(path: Path) -> dict:
    root = ET.parse(path).getroot()
    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    if root.tag != "testsuite":
        suites = [suite for suite in suites if suite.get("name") == "pytest"] or suites[:1]
    return {
        key: sum(int(float(suite.get(key, "0"))) for suite in suites)
        for key in ("tests", "failures", "errors", "skipped")
    }


def main() -> int:
    baseline_path, patched_path = map(Path, sys.argv[1:3])
    baseline = failures(baseline_path)
    patched = failures(patched_path)
    report = {
        "baseline": counts(baseline_path),
        "patched": counts(patched_path),
        "baseline_failure_reproduced": sorted(baseline & patched),
        "baseline_failure_fixed": sorted(baseline - patched),
        "new_failure": sorted(patched - baseline),
        "classification": "PASS" if not (patched - baseline) else "NEW_FAILURE",
    }
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if not report["new_failure"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
