#!/usr/bin/env python3
"""Run multiple real local `run_tpo_proof_once` attempts and log exits + bottom JPEG hashes."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]


def main() -> int:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 8
    runs: list[dict[str, object]] = []
    for i in range(n):
        proc = subprocess.run(
            [sys.executable, str(_REPO / "scripts" / "run_tpo_proof_once.py")],
            cwd=str(_REPO),
            capture_output=True,
            text=True,
        )
        stdout = (proc.stdout or "").strip().splitlines()
        summary: dict[str, object] = {}
        if stdout:
            try:
                summary = json.loads(stdout[-1])
            except json.JSONDecodeError:
                summary = {"parse_error": True, "tail": stdout[-1][:400]}
        art = summary.get("artifacts") if isinstance(summary.get("artifacts"), dict) else {}
        bot_rel = art.get("bottom_image") if isinstance(art, dict) else ""
        sha16 = ""
        if isinstance(bot_rel, str) and bot_rel.strip():
            p = _REPO / bot_rel
            if p.is_file():
                sha16 = hashlib.sha256(p.read_bytes()).hexdigest()[:16]
        prof = summary.get("run_profile_sec") if isinstance(summary.get("run_profile_sec"), dict) else {}
        runs.append(
            {
                "attempt": i + 1,
                "exit_code": proc.returncode,
                "tpo": summary.get("tpo"),
                "validation": (summary.get("status") or {}).get("content")
                if isinstance(summary.get("status"), dict)
                else None,
                "bottom_image_sha256_prefix": sha16,
                "proof_html": art.get("proof_html") if isinstance(art, dict) else "",
                "total_wall_sec": prof.get("total_wall_sec"),
                "errors_present": bool(summary.get("errors")),
            }
        )
    out_path = _REPO / "output" / "tpo_stability_probe_latest.json"
    blob = {"configured_attempts": n, "runs": runs}
    out_path.write_text(json.dumps(blob, ensure_ascii=False, indent=2), encoding="utf-8")
    sys.stdout.write(json.dumps({"written": str(out_path), **blob}, ensure_ascii=False, indent=2))
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
