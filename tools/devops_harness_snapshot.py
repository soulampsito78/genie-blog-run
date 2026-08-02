#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path


def _run(repo: Path, *args: str) -> bytes:
    return subprocess.check_output(args, cwd=repo)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _file_record(path: Path, repo: Path) -> dict:
    stat = path.lstat()
    relative = path.relative_to(repo).as_posix()
    if path.is_symlink():
        digest = _sha(os.readlink(path).encode("utf-8"))
        kind = "symlink"
    elif path.is_file():
        digest = _sha(path.read_bytes())
        kind = "file"
    else:
        digest = ""
        kind = "directory"
    return {"path": relative, "kind": kind, "mtime_ns": stat.st_mtime_ns, "sha256": digest}


def build_snapshot(repo: Path) -> dict:
    untracked_raw = _run(repo, "git", "ls-files", "--others", "--exclude-standard", "-z")
    untracked = [item.decode("utf-8") for item in untracked_raw.split(b"\0") if item]
    untracked_records = []
    for relative in sorted(untracked):
        path = repo / relative
        if path.exists() or path.is_symlink():
            untracked_records.append(_file_record(path, repo))

    generated_roots = [repo / "output" / "admin_runs", repo / "output" / "admin_notices"]
    generated_records = []
    for root in generated_roots:
        if root.exists():
            generated_records.append(_file_record(root, repo))
            for path in sorted(root.rglob("*")):
                generated_records.append(_file_record(path, repo))
    for pattern in ("logs.json", "run_output*.json", "owner_email_*.html"):
        for path in sorted(repo.glob(pattern)):
            generated_records.append(_file_record(path, repo))

    return {
        "schema_version": "devops_harness_snapshot_v1",
        "head": _run(repo, "git", "rev-parse", "HEAD").decode().strip(),
        "tracked_diff_sha256": _sha(_run(repo, "git", "diff", "--binary", "HEAD", "--")),
        "staged_diff_sha256": _sha(_run(repo, "git", "diff", "--binary", "--cached", "--")),
        "untracked": untracked_records,
        "generated": generated_records,
    }


def main() -> int:
    if len(sys.argv) not in {2, 4}:
        print("usage: devops_harness_snapshot.py REPO [--compare SNAPSHOT]", file=sys.stderr)
        return 2
    repo = Path(sys.argv[1]).resolve()
    current = build_snapshot(repo)
    if len(sys.argv) == 2:
        print(json.dumps(current, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    baseline = json.loads(Path(sys.argv[3]).read_text(encoding="utf-8"))
    equal = current == baseline
    print(json.dumps({"unchanged": equal, "before": baseline, "after": current}, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if equal else 1


if __name__ == "__main__":
    raise SystemExit(main())
