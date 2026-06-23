#!/usr/bin/env python3
"""
archive_gcs_generated_images.py
--------------------------------
Download/copy GCS-hosted generated images from the Genie artifact bucket
into a local _ops_image_archive/ folder for operator inspection.

SAFETY RULES (enforced in code):
  - Never deletes GCS objects.
  - Never changes lifecycle rules.
  - Never sends email / calls SMTP / triggers schedulers.
  - Never deploys or modifies Cloud Run.
  - Read-only against GCS; write-only to local archive directory.

Usage:
    # Dry-run only (list candidates, no download):
    python3 scripts/archive_gcs_generated_images.py --dry-run

    # List + download:
    python3 scripts/archive_gcs_generated_images.py

    # Custom bucket / prefix:
    python3 scripts/archive_gcs_generated_images.py \
        --bucket gen-lang-client-0667098249-genie-artifacts \
        --prefix admin_runs

    # Limit to specific modes:
    python3 scripts/archive_gcs_generated_images.py --modes today_genie keysuri_global_tech
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import re
import sys
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Repo-relative constants
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[1]
ARCHIVE_ROOT = REPO_ROOT / "_ops_image_archive"

DEFAULT_BUCKET = "gen-lang-client-0667098249-genie-artifacts"
DEFAULT_PREFIX = "admin_runs"

# Prefixes to search for generated images
SEARCH_PREFIXES = [
    # Run-level generated images: admin_runs/{run_id}.images/
    "{prefix}/",
    # Static approved Korea bottom asset
    "assets/keysuri/korea_bottom/",
]

IMAGE_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".webp"})

# Objects that are clearly non-generated static assets (exact suffix match)
KNOWN_STATIC_OBJECT_SUFFIXES = frozenset({
    # probe file written by artifact store health-check
    ".store_ready_probe",
})

# Known non-image prefixes to skip entirely (saves scanning time)
SKIP_PREFIXES = frozenset({
    "admin_config/",  # JSON config, not images
})

DRY_RUN_OBJECT_LIMIT = 1_000
DRY_RUN_BYTE_LIMIT = 2 * 1024 * 1024 * 1024  # 2 GB

# ---------------------------------------------------------------------------
# GCS helpers (uses google-cloud-storage if available, else falls back to
# gcloud subprocess — whichever is present in the runtime environment).
# ---------------------------------------------------------------------------


def _gcs_client_available() -> bool:
    try:
        from google.cloud import storage  # noqa: F401
        return True
    except ImportError:
        return False


def list_gcs_objects(bucket: str, prefix: str) -> List[Dict[str, Any]]:
    """
    Return a list of object metadata dicts for all objects under bucket/prefix.
    Each dict has: name, size, updated, etag.
    Uses google-cloud-storage when available, else gcloud CLI.
    """
    if _gcs_client_available():
        return _list_via_sdk(bucket, prefix)
    return _list_via_gcloud(bucket, prefix)


def _list_via_sdk(bucket: str, prefix: str) -> List[Dict[str, Any]]:
    from google.cloud import storage  # type: ignore[import]
    client = storage.Client()
    blobs = client.list_blobs(bucket, prefix=prefix)
    results = []
    for blob in blobs:
        results.append({
            "name": blob.name,
            "size": blob.size or 0,
            "updated": blob.updated.isoformat() if blob.updated else "",
            "etag": blob.etag or "",
        })
    return results


def _list_via_gcloud(bucket: str, prefix: str) -> List[Dict[str, Any]]:
    import subprocess
    uri = f"gs://{bucket}/{prefix}"
    cmd = ["gcloud", "storage", "ls", "-l", "-r", uri]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if proc.returncode != 0:
        raise RuntimeError(
            f"gcloud storage ls failed (rc={proc.returncode}):\n{proc.stderr}"
        )
    results = []
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line or line.startswith("TOTAL:") or line.endswith(":"):
            continue
        # gcloud -l output: SIZE DATE TIME GSURI
        parts = line.split()
        if len(parts) < 3:
            continue
        try:
            size = int(parts[0])
        except ValueError:
            continue
        name = parts[-1]
        if name.startswith("gs://"):
            name = name[len(f"gs://{bucket}/"):]
        updated = " ".join(parts[1:3]) if len(parts) >= 3 else ""
        results.append({"name": name, "size": size, "updated": updated, "etag": ""})
    return results


def download_gcs_object(bucket: str, object_name: str, dest: Path) -> None:
    """Download a single GCS object to dest (creates parent dirs)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if _gcs_client_available():
        _download_via_sdk(bucket, object_name, dest)
    else:
        _download_via_gcloud(bucket, object_name, dest)


def _download_via_sdk(bucket: str, object_name: str, dest: Path) -> None:
    from google.cloud import storage  # type: ignore[import]
    client = storage.Client()
    blob = client.bucket(bucket).blob(object_name)
    blob.download_to_filename(str(dest))


def _download_via_gcloud(bucket: str, object_name: str, dest: Path) -> None:
    import subprocess
    src = f"gs://{bucket}/{object_name}"
    cmd = ["gcloud", "storage", "cp", src, str(dest)]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if proc.returncode != 0:
        raise RuntimeError(
            f"gcloud storage cp failed (rc={proc.returncode}):\n{proc.stderr}"
        )


# ---------------------------------------------------------------------------
# Classification helpers
# ---------------------------------------------------------------------------

MODE_PATTERNS: List[Tuple[str, str]] = [
    # (regex pattern on object name, mode name)
    (r"today_genie", "today_genie"),
    (r"keysuri_korea", "keysuri_korea_tech"),
    (r"keysuri_global", "keysuri_global_tech"),
    (r"keysuri", "keysuri_global_tech"),  # fallback keysuri without region
]

ROLE_PATTERNS: List[Tuple[str, str]] = [
    # Order matters: more specific first
    (r"korea_bottom", "korea_bottom"),
    (r"korea_top", "korea_top"),
    (r"(?<![a-z])bottom", "bottom"),
    (r"(?<![a-z])top(?![a-z])", "top"),
]


def classify_object(name: str) -> Tuple[str, str]:
    """Return (mode, role) for an object by its GCS name."""
    lower = name.lower()
    mode = "unknown"
    for pattern, m in MODE_PATTERNS:
        if re.search(pattern, lower):
            mode = m
            break
    role = "unknown"
    for pattern, r in ROLE_PATTERNS:
        if re.search(pattern, lower):
            role = r
            break
    return mode, role


def is_image_object(name: str) -> bool:
    return Path(name).suffix.lower() in IMAGE_EXTENSIONS


def is_static_asset(name: str) -> bool:
    """Heuristic: objects under assets/ are static approved assets, not generated."""
    # The Korea bottom baseline watermarked asset is a known approved static asset.
    # We include it, but flag confidence as 'low' for operator inspection.
    return False  # we include all images; classify confidence later


def should_skip(name: str) -> Tuple[bool, str]:
    """Return (skip, reason)."""
    for sfx in KNOWN_STATIC_OBJECT_SUFFIXES:
        if name.endswith(sfx):
            return True, "non_image_probe_file"
    for pfx in SKIP_PREFIXES:
        if name.startswith(pfx):
            return True, f"excluded_prefix_{pfx}"
    if not is_image_object(name):
        return True, "not_an_image_extension"
    return False, ""


def confidence_for_object(name: str) -> str:
    """High = clearly generated run artifact; Low = static/approved asset."""
    if re.search(r"\.images/", name):
        return "high"  # run_id.images/* is purely generated
    if name.startswith("assets/"):
        return "low"   # approved static asset
    return "medium"


def safe_local_name(gcs_name: str) -> str:
    """Convert GCS object name to a filename-safe local path fragment."""
    return gcs_name.replace("/", "__").replace(" ", "_")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Archive layout helpers
# ---------------------------------------------------------------------------

def local_dest_path(archive_root: Path, mode: str, gcs_name: str) -> Path:
    """Compute the local destination path for a downloaded image."""
    subfolder = archive_root / mode
    filename = safe_local_name(gcs_name)
    return subfolder / filename


# ---------------------------------------------------------------------------
# Main archive logic
# ---------------------------------------------------------------------------

def build_candidates(
    bucket: str,
    prefix: str,
    allowed_modes: Optional[List[str]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], int]:
    """
    List GCS objects and return:
      (candidates, skipped_objects, total_scanned_count)
    """
    print(f"[DRY-RUN] Listing gs://{bucket}/{prefix}/ ...", flush=True)

    raw_objects = list_gcs_objects(bucket, f"{prefix}/")

    # Also scan assets/keysuri/korea_bottom/ for the approved static asset
    try:
        raw_objects += list_gcs_objects(bucket, "assets/keysuri/korea_bottom/")
    except Exception as exc:
        print(f"  [WARN] Could not list assets/keysuri/korea_bottom/: {exc}", flush=True)

    total_scanned = len(raw_objects)
    candidates: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []

    for obj in raw_objects:
        name = obj["name"]
        skip, reason = should_skip(name)
        if skip:
            skipped.append({"gcs_object": name, "reason": reason})
            continue

        mode, role = classify_object(name)

        if allowed_modes and mode not in allowed_modes and mode != "unknown":
            skipped.append({
                "gcs_object": name,
                "reason": f"mode_filter ({mode} not in {allowed_modes})",
            })
            continue

        candidates.append({
            "gcs_object": name,
            "gcs_uri": f"gs://{bucket}/{name}",
            "mode": mode,
            "role": role,
            "size": obj.get("size", 0),
            "updated": obj.get("updated", ""),
            "confidence": confidence_for_object(name),
        })

    return candidates, skipped, total_scanned


def run_archive(
    bucket: str,
    prefix: str,
    dry_run: bool,
    allowed_modes: Optional[List[str]],
) -> None:
    # -----------------------------------------------------------------------
    # 1. List candidates
    # -----------------------------------------------------------------------
    candidates, skipped, total_scanned = build_candidates(bucket, prefix, allowed_modes)

    total_bytes = sum(c["size"] for c in candidates)

    print(f"\n=== DRY-RUN RESULTS ===")
    print(f"  Total objects scanned   : {total_scanned}")
    print(f"  Candidate images        : {len(candidates)}")
    print(f"  Skipped                 : {len(skipped)}")
    print(f"  Total candidate bytes   : {total_bytes:,} ({total_bytes / 1024 / 1024:.1f} MB)")

    # Safety stop
    if total_scanned > DRY_RUN_OBJECT_LIMIT:
        print(
            f"\n[SAFETY STOP] Object count {total_scanned} exceeds limit {DRY_RUN_OBJECT_LIMIT}.\n"
            "Please narrow the search with --prefix or --modes and re-run."
        )
        sys.exit(1)

    if total_bytes > DRY_RUN_BYTE_LIMIT:
        print(
            f"\n[SAFETY STOP] Candidate bytes {total_bytes:,} exceeds limit {DRY_RUN_BYTE_LIMIT:,} (2 GB).\n"
            "Please narrow the search and re-run."
        )
        sys.exit(1)

    # Mode breakdown
    mode_counts: Dict[str, int] = {}
    role_counts: Dict[str, int] = {}
    for c in candidates:
        mode_counts[c["mode"]] = mode_counts.get(c["mode"], 0) + 1
        role_counts[c["role"]] = role_counts.get(c["role"], 0) + 1

    print("\n  Breakdown by mode:")
    for m in sorted(mode_counts):
        print(f"    {m:30s} {mode_counts[m]:4d}")
    print("\n  Breakdown by role:")
    for r in sorted(role_counts):
        print(f"    {r:30s} {role_counts[r]:4d}")

    if skipped:
        print(f"\n  Skipped objects ({len(skipped)}):")
        for s in skipped[:20]:
            print(f"    {s['gcs_object']}  [{s['reason']}]")
        if len(skipped) > 20:
            print(f"    ... and {len(skipped) - 20} more")

    if dry_run:
        print("\n[DRY-RUN MODE] No files downloaded. Re-run without --dry-run to download.\n")
        # Write a dry-run manifest so operators can review before committing
        _write_manifest(candidates, skipped, ARCHIVE_ROOT, dry_run=True)
        return

    # -----------------------------------------------------------------------
    # 2. Download
    # -----------------------------------------------------------------------
    ARCHIVE_ROOT.mkdir(parents=True, exist_ok=True)
    for subfolder in ("today_genie", "keysuri_global_tech", "keysuri_korea_tech", "unknown"):
        (ARCHIVE_ROOT / subfolder).mkdir(exist_ok=True)

    downloaded = 0
    total_downloaded_bytes = 0
    failures: List[Dict[str, Any]] = []

    for i, c in enumerate(candidates, 1):
        dest = local_dest_path(ARCHIVE_ROOT, c["mode"], c["gcs_object"])
        print(f"  [{i}/{len(candidates)}] {c['gcs_object']}  → {dest.relative_to(REPO_ROOT)}", flush=True)
        try:
            download_gcs_object(bucket, c["gcs_object"], dest)
            c["local_path"] = str(dest.relative_to(REPO_ROOT))
            c["sha256"] = sha256_file(dest)
            downloaded += 1
            total_downloaded_bytes += dest.stat().st_size
        except Exception as exc:
            msg = str(exc)
            print(f"    [FAIL] {msg}", flush=True)
            failures.append({"gcs_object": c["gcs_object"], "error": msg})
            c["local_path"] = None
            c["download_error"] = msg

    print(f"\n=== DOWNLOAD COMPLETE ===")
    print(f"  Downloaded              : {downloaded}/{len(candidates)}")
    print(f"  Total bytes downloaded  : {total_downloaded_bytes:,} ({total_downloaded_bytes / 1024 / 1024:.1f} MB)")
    if failures:
        print(f"  Failures                : {len(failures)}")
        for f in failures:
            print(f"    {f['gcs_object']}: {f['error']}")

    # -----------------------------------------------------------------------
    # 3. Write manifest and README
    # -----------------------------------------------------------------------
    _write_manifest(candidates, skipped, ARCHIVE_ROOT, dry_run=False, failures=failures)
    _write_readme(
        ARCHIVE_ROOT,
        bucket=bucket,
        prefix=prefix,
        total_scanned=total_scanned,
        candidates=candidates,
        downloaded=downloaded,
        total_bytes=total_downloaded_bytes,
        mode_counts=mode_counts,
        role_counts=role_counts,
    )

    print(f"\n  Archive root            : {ARCHIVE_ROOT}")
    print(f"  Manifest                : {ARCHIVE_ROOT / 'manifest.json'}")
    print(f"  README                  : {ARCHIVE_ROOT / 'README.md'}")
    print()
    print("SAFETY CONFIRMATION:")
    print("  - No GCS objects deleted or mutated.")
    print("  - No lifecycle rules changed.")
    print("  - No email / SMTP / approve_run called.")
    print("  - No service_full_run / Scheduler triggered.")
    print("  - No Cloud Run / env / Secret changes.")
    print("  - No images generated.")


# ---------------------------------------------------------------------------
# Manifest / README writers
# ---------------------------------------------------------------------------

def _write_manifest(
    candidates: List[Dict[str, Any]],
    skipped: List[Dict[str, Any]],
    archive_root: Path,
    *,
    dry_run: bool,
    failures: Optional[List[Dict[str, Any]]] = None,
) -> None:
    archive_root.mkdir(parents=True, exist_ok=True)
    manifest = {
        "generated_at": datetime.datetime.utcnow().isoformat() + "Z",
        "dry_run": dry_run,
        "total_candidate_objects": len(candidates),
        "total_skipped_objects": len(skipped),
        "failures": failures or [],
        "images": candidates,
        "skipped": skipped,
    }
    path = archive_root / "manifest.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"  Manifest written        : {path}")


def _write_readme(
    archive_root: Path,
    *,
    bucket: str,
    prefix: str,
    total_scanned: int,
    candidates: List[Dict[str, Any]],
    downloaded: int,
    total_bytes: int,
    mode_counts: Dict[str, int],
    role_counts: Dict[str, int],
) -> None:
    now = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    lines = [
        "# GCS Generated Image Archive",
        "",
        f"Generated: {now}  ",
        f"Source bucket: `gs://{bucket}/{prefix}/`  ",
        f"Total objects scanned: {total_scanned}  ",
        f"Images downloaded: {downloaded} / {len(candidates)}  ",
        f"Total size: {total_bytes:,} bytes ({total_bytes / 1024 / 1024:.1f} MB)  ",
        "",
        "## DO NOT COMMIT",
        "",
        "This folder is a local operator inspection archive.",
        "Do not commit images or this README to the repository.",
        "",
        "## Folder Layout",
        "",
        "```",
        "_ops_image_archive/",
        "├── today_genie/         # today_genie generated images",
        "├── keysuri_global_tech/ # keysuri global tech generated images",
        "├── keysuri_korea_tech/  # keysuri korea tech generated images",
        "└── unknown/             # unclassified images",
        "```",
        "",
        "## Breakdown by Mode",
        "",
    ]
    for m in sorted(mode_counts):
        lines.append(f"- `{m}`: {mode_counts[m]}")
    lines += [
        "",
        "## Breakdown by Role",
        "",
    ]
    for r in sorted(role_counts):
        lines.append(f"- `{r}`: {role_counts[r]}")
    lines += [
        "",
        "## Safety",
        "",
        "- No GCS objects were deleted or mutated.",
        "- No lifecycle rules were changed.",
        "- See `manifest.json` for full object list and metadata.",
        "",
        "## Candidates Considered Safe to Delete Later",
        "",
        "Review manifest.json to identify objects to clean up.",
        "Do NOT delete from this document — use GCS console or `gcloud storage rm` after operator review.",
    ]
    path = archive_root / "README.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--bucket", default=DEFAULT_BUCKET, help="GCS bucket name")
    parser.add_argument("--prefix", default=DEFAULT_PREFIX, help="GCS object prefix (default: admin_runs)")
    parser.add_argument("--dry-run", action="store_true", help="List candidates only; do not download")
    parser.add_argument(
        "--modes",
        nargs="*",
        default=None,
        metavar="MODE",
        help="Limit to specific modes: today_genie keysuri_global_tech keysuri_korea_tech",
    )
    args = parser.parse_args()

    print("=" * 60)
    print("GCS Generated Image Archiver")
    print("=" * 60)
    print(f"  Bucket  : gs://{args.bucket}")
    print(f"  Prefix  : {args.prefix}")
    print(f"  Dry-run : {args.dry_run}")
    print(f"  Modes   : {args.modes or 'all'}")
    print()
    print("SAFETY: This script is READ-ONLY against GCS.")
    print("        It will NEVER delete or mutate any GCS object.")
    print()

    run_archive(
        bucket=args.bucket,
        prefix=args.prefix,
        dry_run=args.dry_run,
        allowed_modes=args.modes,
    )


if __name__ == "__main__":
    main()
