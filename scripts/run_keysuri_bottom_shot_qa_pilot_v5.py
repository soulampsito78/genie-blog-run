"""Key-Suri Bottom Shot QA Pilot v5 — 2 images only.

Generates exactly 2 QA-only bottom-shot images using Contract v5.
Does NOT:
  - call service_full_run
  - send any email
  - register assets
  - watermark images
  - copy to email/static
  - enable variation gate in Cloud Run
  - touch production delivery paths

Reference:
  Asset01: assets/keysuri/reference/image_keysuri_asset_01_main_briefing.png
  105936:  direction reference only — NOT image input

Output folder:
  output/keysuri_preview/korea_bottom_rotation/qa_pilot_v5/family_a/
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

# --- repo root ---
REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from keysuri_bottom_shot_prompt_builder import (  # noqa: E402
    ASSET01_PATH,
    build_bottom_shot_prompt,
)

# -----------------------------------------------------------------------
# Config
# -----------------------------------------------------------------------
PROGRAM_ID = "keysuri_korea_tech"
FAMILY_ID = "family_a"
QA_OUTPUT_DIR = REPO / "output/keysuri_preview/korea_bottom_rotation/qa_pilot_v5/family_a"
ASSET01_ABS = REPO / ASSET01_PATH

# Two weather shells to test — pick controlled cases
WEATHER_CASES = [
    {"weather_condition": "clear", "temperature_c": 12.0, "season": None,    "label": "clear_cool"},
    {"weather_condition": "clear", "temperature_c": 12.0, "season": "autumn_evening", "label": "autumn_evening"},
]

MAX_IMAGES = 2
MODEL_NAME = "gemini-2.5-flash-image"
LOCATION = "global"
PROJECT_ID = (os.getenv("GENIE_VERTEX_PROJECT_ID") or os.getenv("GOOGLE_CLOUD_PROJECT") or "").strip()


# -----------------------------------------------------------------------
# Pilot generation
# -----------------------------------------------------------------------

def _stamp() -> str:
    return datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y%m%d_%H%M%S")


def _build_and_save_prompt(case: dict, out_dir: Path, stamp: str) -> Dict[str, Any]:
    """Build prompt via Contract v5 builder and write to disk."""
    result = build_bottom_shot_prompt(
        weather_condition=case["weather_condition"],
        temperature_c=case.get("temperature_c"),
        season=case.get("season"),
        program_id=PROGRAM_ID,
        family_id=FAMILY_ID,
    )
    label = case["label"]
    prompt_path = out_dir / f"bottom_shot_prompt_{label}_{stamp}.txt"
    meta_path = out_dir / f"bottom_shot_meta_{label}_{stamp}.json"

    prompt_path.write_text(
        f"POSITIVE:\n{result['prompt_text']}\n\nNEGATIVE:\n{result['negative_prompt']}",
        encoding="utf-8",
    )
    with meta_path.open("w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)

    print(f"  [prompt saved] {prompt_path.relative_to(REPO)}")
    print(f"  [meta  saved] {meta_path.relative_to(REPO)}")
    return {"result": result, "prompt_path": prompt_path, "meta_path": meta_path, "label": label}


def _generate_image(
    prompt_result: Dict[str, Any],
    out_dir: Path,
    stamp: str,
    image_index: int,
) -> Dict[str, Any]:
    """Call image_generator.generate_image_file for one image."""
    from image_generator import generate_image_file

    label = prompt_result["label"]
    out_path = out_dir / f"bottom_shot_qa_{label}_{stamp}_{image_index:02d}.jpg"
    positive = prompt_result["result"]["prompt_text"]
    negative = prompt_result["result"]["negative_prompt"]
    full_prompt = f"{positive}\n\nNEGATIVE:\n{negative}"

    print(f"  [generating] image {image_index} ({label}) → {out_path.relative_to(REPO)}")

    generate_image_file(
        prompt=full_prompt,
        output_path=out_path,
        model_name=MODEL_NAME,
        reference_image_path=ASSET01_ABS if ASSET01_ABS.is_file() else None,
        project_id=PROJECT_ID or None,
        location=LOCATION,
    )
    print(f"  [saved]      {out_path.relative_to(REPO)}")
    return {"image_path": out_path, "label": label, "index": image_index}


def _make_contact_sheet(image_paths: List[Path], out_dir: Path, stamp: str) -> Optional[Path]:
    """Compose a simple side-by-side contact sheet."""
    try:
        from PIL import Image as PILImage

        images = [PILImage.open(p).convert("RGB") for p in image_paths if p.is_file()]
        if not images:
            return None
        w = max(im.width for im in images)
        h = max(im.height for im in images)
        sheet = PILImage.new("RGB", (w * len(images), h), (30, 30, 30))
        for i, im in enumerate(images):
            sheet.paste(im.resize((w, h)), (i * w, 0))
        sheet_path = out_dir / f"bottom_shot_qa_contact_sheet_{stamp}.jpg"
        sheet.save(sheet_path, format="JPEG", quality=90)
        print(f"  [contact sheet] {sheet_path.relative_to(REPO)}")
        return sheet_path
    except Exception as exc:
        print(f"  [contact sheet FAILED] {exc}")
        return None


CHECKLIST = {
    "identity": [
        "mid-to-late thirties face",
        "chin-length bob (no updos, no bangs)",
        "thin metal rectangular glasses visible",
        "composed non-performative expression",
        "Korean woman, angular jaw, almond eyes",
    ],
    "role_scene": [
        "closed CEO/chairman wooden office door visible in background",
        "warm wood-paneled wall / visible premium wooden door",
        "farewell / closing ritual — leaving-work, not briefing",
        "viewer is the owner/representative (대표님) she is leaving toward",
        "off-duty after the briefing is finished",
        "no outdoor scene",
        "no open door leading to another room",
        "no full-body framing",
    ],
    "camera": [
        "knee-up / 3-4 body framing",
        "face-first, enough outfit visible below",
        "eye-level or 2-3 degrees above — not below chin",
        "background softly defocused",
        "no wide/establishing shot",
        "no full-body lookbook",
        "no tight mid-chest-to-crown top-shot crop",
    ],
    "environment_blocklist": [
        "no tablet",
        "no monitor wall / tech screen",
        "no monitor / multiple monitors / large screen background",
        "no desk / keyboard / reading device",
        "no lobby / atrium / open corridor",
        "no briefing posture",
    ],
    "weather_shell": [
        "outfit matches weather case",
        "professional off-duty (no casual/streetwear)",
        "no V-neck wrap / open-front / satin",
        "identity gene not distorted by outfit",
    ],
    "failure_blocklist": [
        "no V-neck wrap dress",
        "no décolleté",
        "no open hotel-like room",
        "no full-body lookbook",
        "no active wave",
        "no toothy smile",
        "no C-curl cute bob",
        "no young office worker appearance",
        "no glamour model appearance",
        "no outfit-first composition",
        "no round / oval glasses (must be thin metal rectangular)",
    ],
}

# Terms that must NOT be visible in the rendered IMAGE (visual inspection),
# NOT a prompt-text scan — several of these intentionally appear in the
# Contract v5 negative prompt.
HARD_FAIL_TERMS = [
    "tablet",
    "briefing tablet",
    "tech screen",
    "monitor wall",
    "monitor",
    "desk",
    "keyboard",
    "multiple monitors",
    "large screen background",
    "reading device",
    "lobby",
    "atrium",
    "open corridor",
    "briefing posture",
    "round glasses",
    "oval glasses",
    "V-neck wrap dress",
    "décolleté",
    "toothy smile",
    "active wave",
    "full-body lookbook",
]


def _write_review_report(
    image_results: List[Dict[str, Any]],
    prompt_infos: List[Dict[str, Any]],
    out_dir: Path,
    stamp: str,
) -> Path:
    """Write review report with Review Checklist v5 structure."""
    report: Dict[str, Any] = {
        "report_type": "keysuri_bottom_shot_qa_pilot_v5",
        "generated_at_kst": stamp,
        "program_id": PROGRAM_ID,
        "family_id": FAMILY_ID,
        "model": MODEL_NAME,
        "asset01_reference": ASSET01_PATH,
        "direction_ref_105936": "direction_reference_only — NOT image input",
        "generation_allowed_flag": False,
        "runtime_enabled_flag": False,
        "image_api_called": True,
        "watermark_applied": False,
        "registry_updated": False,
        "email_sent": False,
        "service_full_run_called": False,
        "scheduler_triggered": False,
        "contract_version": "v5",
        "review_checklist_v5": CHECKLIST,
        "hard_fail_terms": HARD_FAIL_TERMS,
        "images": [],
        "owner_review_recommendation": "PENDING_VISUAL_INSPECTION",
    }

    for img_res, prompt_info in zip(image_results, prompt_infos):
        img_path = img_res["image_path"]
        label = img_res["label"]
        entry: Dict[str, Any] = {
            "image_index": img_res["index"],
            "label": label,
            "image_path": str(img_path.relative_to(REPO)) if img_path.is_file() else "MISSING",
            "prompt_path": str(prompt_info["prompt_path"].relative_to(REPO)),
            "meta_path": str(prompt_info["meta_path"].relative_to(REPO)),
            "weather_case": prompt_info["result"]["weather_outfit_shell"]["weather_case"],
            "outfit_map_key": prompt_info["result"]["weather_outfit_shell"]["outfit_map_key"],
            "review_checklist_v5": {cat: "REQUIRES_VISUAL_INSPECTION" for cat in CHECKLIST},
            "hard_fail_detected": False,
            "overall_status": "REQUIRES_VISUAL_INSPECTION",
            "notes": (
                "Owner must inspect against Review Checklist v5 gates 1-5 before approval. "
                "HARD_FAIL_TERMS are visual-inspection targets for the rendered image, "
                "NOT a prompt-text scan (several intentionally appear in the negative prompt). "
                "Visual identity gene alignment with Asset01 requires human review."
            ),
        }
        report["images"].append(entry)

    report_path = out_dir / f"bottom_shot_qa_review_report_{stamp}.json"
    with report_path.open("w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"  [review report] {report_path.relative_to(REPO)}")
    return report_path


def run_qa_pilot() -> None:
    print("\n=== Key-Suri Bottom Shot QA Pilot v5 ===")
    print(f"program_id:  {PROGRAM_ID}")
    print(f"family_id:   {FAMILY_ID}")
    print(f"max_images:  {MAX_IMAGES}")
    print(f"model:       {MODEL_NAME}")
    print(f"asset01:     {ASSET01_PATH}")
    print(f"output_dir:  output/keysuri_preview/korea_bottom_rotation/qa_pilot_v5/family_a/")
    print()

    if not ASSET01_ABS.is_file():
        print(f"[ERROR] Asset01 not found at {ASSET01_ABS}")
        sys.exit(1)

    if not PROJECT_ID:
        print("[ERROR] GENIE_VERTEX_PROJECT_ID or GOOGLE_CLOUD_PROJECT not set")
        sys.exit(1)

    QA_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = _stamp()

    # Build prompts for both weather cases
    prompt_infos = []
    for case in WEATHER_CASES[:MAX_IMAGES]:
        print(f"\n[Building prompt: {case['label']}]")
        info = _build_and_save_prompt(case, QA_OUTPUT_DIR, stamp)
        prompt_infos.append(info)

    # Generate images — exactly MAX_IMAGES
    image_results = []
    for i, prompt_info in enumerate(prompt_infos, start=1):
        print(f"\n[Generating image {i}/{MAX_IMAGES}: {prompt_info['label']}]")
        img_result = _generate_image(prompt_info, QA_OUTPUT_DIR, stamp, i)
        image_results.append(img_result)

    # Contact sheet
    print("\n[Building contact sheet]")
    sheet_path = _make_contact_sheet(
        [r["image_path"] for r in image_results],
        QA_OUTPUT_DIR,
        stamp,
    )

    # Review report
    print("\n[Writing review report]")
    report_path = _write_review_report(image_results, prompt_infos, QA_OUTPUT_DIR, stamp)

    print("\n=== QA Pilot Complete ===")
    print(f"Images generated: {len(image_results)}")
    for r in image_results:
        rel = r["image_path"].relative_to(REPO) if r["image_path"].is_file() else "MISSING"
        print(f"  [{r['index']}] {r['label']} → {rel}")
    if sheet_path:
        print(f"Contact sheet:    {sheet_path.relative_to(REPO)}")
    print(f"Review report:    {report_path.relative_to(REPO)}")
    print()
    print("Confirmations:")
    print("  no watermark, no registry, no email, no service_full_run")
    print("  no Scheduler, no customer delivery, no secrets changed")
    print("  variation gate unchanged (KEYSURI_KOREA_BOTTOM_VARIATION_ENABLED not set)")
    print()
    print("Next step: owner visual inspection against Review Checklist v5 Gates 1-5.")


if __name__ == "__main__":
    run_qa_pilot()
