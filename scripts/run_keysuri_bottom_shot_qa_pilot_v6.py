"""Key-Suri Bottom Shot QA Pilot v6 — manual-only, max 2 images.

Contract v6 anchor patch: 105936 is the primary fixed Bottom visual anchor.
Asset01 is secondary same-person continuity reference.
Weather drives wardrobe selection within the 105936-family premium closet.

Image generation: calls Vertex AI directly with multi-ref content_parts.
  Slot 0: 105936 (primary Bottom visual anchor)
  Slot 1: Asset01 (secondary continuity reference, if file exists)
  Slot 2: prompt text
Does NOT call image_generator.generate_image_file().
image_generator.py is untouched.

Does NOT:
  - call service_full_run
  - send any email
  - register assets
  - watermark images
  - copy to email/static
  - enable variation gate in Cloud Run
  - touch production delivery paths
  - touch top assets, scheduler, admin_store, secrets

Output folder:
  output/keysuri_preview/korea_bottom_rotation/qa_pilot_v6/family_a/

QA verdict: PASS or FAIL only. No CONDITIONAL_PASS.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from keysuri_bottom_shot_prompt_builder import (  # noqa: E402
    ASSET01_PATH,
    BOTTOM_ANCHOR_PATH,
    BOTTOM_ANCHOR_ROLE,
    ASSET01_ROLE,
    build_bottom_shot_prompt,
)

PROGRAM_ID = "keysuri_korea_tech"
FAMILY_ID = "family_a"
QA_OUTPUT_DIR = REPO / "output/keysuri_preview/korea_bottom_rotation/qa_pilot_v6/family_a"
BOTTOM_ANCHOR_ABS = REPO / BOTTOM_ANCHOR_PATH   # 105936 — slot 0 primary anchor
ASSET01_ABS = REPO / ASSET01_PATH               # Asset01 — slot 1 secondary

WEATHER_CASES = [
    {"weather_condition": "clear", "temperature_c": 12.0, "season": None,
     "label": "clear_cool_12c"},
    {"weather_condition": "cold", "temperature_c": 8.0, "season": None,
     "label": "cold_8c"},
]

MAX_IMAGES = 2
MODEL_NAME = "gemini-2.5-flash-image"
LOCATION = "global"
PROJECT_ID = (os.getenv("GENIE_VERTEX_PROJECT_ID") or os.getenv("GOOGLE_CLOUD_PROJECT") or "").strip()


def _stamp() -> str:
    return datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y%m%d_%H%M%S")


def _build_and_save_prompt(case: dict, out_dir: Path, stamp: str) -> Dict[str, Any]:
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


def _generate_image_bottom_anchor(
    prompt_result: Dict[str, Any],
    out_dir: Path,
    stamp: str,
    image_index: int,
) -> Dict[str, Any]:
    """Generate a Bottom image using multi-ref Vertex AI call.

    Content parts order:
      [0] 105936     — primary Bottom visual anchor (BOTTOM_ANCHOR_ABS)
      [1] Asset01    — secondary same-person continuity (ASSET01_ABS, if available)
      [2] prompt     — positive + negative prompt text

    Calls Vertex AI directly. Does NOT call image_generator.generate_image_file().
    image_generator.py is untouched.
    """
    import vertexai
    from vertexai.generative_models import GenerationConfig, GenerativeModel
    from vertexai.generative_models import Image as VxImage, Part
    from PIL import Image as PILImage

    vertexai.init(project=PROJECT_ID, location=LOCATION)
    model = GenerativeModel(MODEL_NAME)

    content_parts: list = []

    # Slot 0 — 105936 primary Bottom visual anchor
    if BOTTOM_ANCHOR_ABS.is_file():
        content_parts.append(Part.from_image(VxImage.load_from_file(str(BOTTOM_ANCHOR_ABS))))
        print(f"  [anchor slot 0] {BOTTOM_ANCHOR_ROLE}: {BOTTOM_ANCHOR_PATH}")
    else:
        print(f"  [WARNING] Bottom anchor not found: {BOTTOM_ANCHOR_ABS}")

    # Slot 1 — Asset01 secondary continuity reference
    if ASSET01_ABS.is_file():
        content_parts.append(Part.from_image(VxImage.load_from_file(str(ASSET01_ABS))))
        print(f"  [anchor slot 1] {ASSET01_ROLE}: {ASSET01_PATH}")

    # Slot 2 — prompt text
    positive = prompt_result["result"]["prompt_text"]
    negative = prompt_result["result"]["negative_prompt"]
    content_parts.append(f"{positive}\n\nNEGATIVE:\n{negative}")

    label = prompt_result["label"]
    out_path = out_dir / f"bottom_shot_qa_{label}_{stamp}_{image_index:02d}.jpg"
    print(f"  [generating] image {image_index} ({label}) → {out_path.relative_to(REPO)}")

    response = model.generate_content(
        content_parts,
        generation_config=GenerationConfig(response_modalities=["IMAGE"]),
    )

    # Extract image bytes
    raw: Optional[bytes] = None
    for cand in (getattr(response, "candidates", None) or []):
        content = getattr(cand, "content", None)
        for p in (getattr(content, "parts", None) or []):
            inline = getattr(p, "inline_data", None)
            if inline and getattr(inline, "data", None):
                raw = inline.data
                break
        if raw:
            break

    if not raw:
        raise RuntimeError(
            f"No image bytes in model response for {label}. "
            f"finish_reason={getattr((getattr(response, 'candidates', [None]) or [None])[0], 'finish_reason', 'unknown')}"
        )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with PILImage.open(BytesIO(raw)) as im:
        im.convert("RGB").save(out_path, format="JPEG", quality=92, optimize=True)

    print(f"  [saved]      {out_path.relative_to(REPO)}")
    return {"image_path": out_path, "label": label, "index": image_index}


def _make_contact_sheet(image_paths: List[Path], out_dir: Path, stamp: str) -> Optional[Path]:
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


# v6 QA checklist — persona-first ordered gates
CHECKLIST_V6 = {
    "gate_1_persona": [
        "private AI secretary — NOT executive, NOT consultant, NOT professor",
        "exclusive owner-facing closing moment — NOT public farewell",
        "restrained composed slight smile — NOT warm motherly, NOT guardian-like",
        "noble sensuality and premium presence — NOT corporate authority portrait",
        "same identity as 105936 reference anchor",
    ],
    "gate_2_identity": [
        "same face/presence family as 105936 anchor",
        "thin metal rectangular glasses visible",
        "side-parted short bob — NO inward C-curl, NO updos, NO bangs",
        "Korean woman, premium register",
    ],
    "gate_3_scene": [
        "closed CEO/chairman wooden door in background",
        "warm wood-paneled wall",
        "private closing moment at office threshold",
        "viewer is the owner (대표님) — not public",
    ],
    "gate_4_wardrobe_prop": [
        "luxury outfit inside 105936 premium closet family — NOT blazer, NOT casual",
        "premium handbag visible",
        "small restrained private gesture — NOT raised, NOT waving",
        "ivory/cream/champagne/camel/charcoal palette — NOT random office casual",
    ],
    "gate_5_framing": [
        "knee-up or 3/4 body — NOT headshot, NOT full-body",
        "face-first composition",
        "no tablet, no tech screen, no desk",
        "no outdoor scene",
    ],
}

HARD_FAIL_TERMS_V6 = [
    "executive portrait",
    "consultant headshot",
    "company profile",
    "professor portrait",
    "manager portrait",
    "blazer",
    "mock-neck",
    "corporate uniform",
    "warm motherly smile",
    "guardian-like",
    "matronly",
    "headshot crop",
    "inward-curled bob",
    "C-curl cute bob",
    "no handbag visible",
    "tablet",
    "briefing posture",
    "lobby",
    "full-body lookbook",
    "tight headshot",
    "cardigan",
    "ordinary office",
    "lifestyle blogger",
]


def _write_review_report(
    image_results: List[Dict[str, Any]],
    prompt_infos: List[Dict[str, Any]],
    out_dir: Path,
    stamp: str,
) -> Path:
    report: Dict[str, Any] = {
        "report_type": "keysuri_bottom_shot_qa_pilot_v6",
        "generated_at_kst": stamp,
        "program_id": PROGRAM_ID,
        "family_id": FAMILY_ID,
        "model": MODEL_NAME,
        "bottom_anchor_105936": BOTTOM_ANCHOR_PATH,
        "bottom_anchor_role": BOTTOM_ANCHOR_ROLE,
        "asset01_reference": ASSET01_PATH,
        "asset01_role": ASSET01_ROLE,
        "image_generation_method": "direct_vertex_ai_multi_ref — image_generator.py NOT called",
        "generation_allowed_flag": False,
        "runtime_enabled_flag": False,
        "image_api_called": True,
        "watermark_applied": False,
        "registry_updated": False,
        "email_sent": False,
        "service_full_run_called": False,
        "scheduler_triggered": False,
        "image_generator_py_touched": False,
        "contract_version": "v6",
        "review_checklist_v6": CHECKLIST_V6,
        "hard_fail_terms_v6": HARD_FAIL_TERMS_V6,
        "images": [],
        "owner_review_recommendation": "PENDING_VISUAL_INSPECTION",
        "verdict_options": ["PASS", "FAIL"],
        "no_conditional_pass": True,
    }

    for img_res, prompt_info in zip(image_results, prompt_infos):
        img_path = img_res["image_path"]
        label = img_res["label"]
        shell = prompt_info["result"]["weather_outfit_shell"]
        entry: Dict[str, Any] = {
            "image_index": img_res["index"],
            "label": label,
            "image_path": str(img_path.relative_to(REPO)) if img_path.is_file() else "MISSING",
            "prompt_path": str(prompt_info["prompt_path"].relative_to(REPO)),
            "meta_path": str(prompt_info["meta_path"].relative_to(REPO)),
            "weather_case": shell["weather_case"],
            "outfit_map_key": shell["outfit_map_key"],
            "review_checklist_v6": {gate: "REQUIRES_VISUAL_INSPECTION" for gate in CHECKLIST_V6},
            "hard_fail_detected": False,
            "overall_status": "REQUIRES_VISUAL_INSPECTION",
            "notes": (
                "Owner must inspect against v6 Gates 1-5 (anchor-first). "
                "Gate 1: does this match the 105936 identity/register? "
                "PASS or FAIL only — no CONDITIONAL_PASS."
            ),
        }
        report["images"].append(entry)

    report_path = out_dir / f"bottom_shot_qa_review_report_{stamp}.json"
    with report_path.open("w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"  [review report] {report_path.relative_to(REPO)}")
    return report_path


def run_qa_pilot() -> None:
    print("\n=== Key-Suri Bottom Shot QA Pilot v6 (105936 anchor patch) ===")
    print(f"program_id:      {PROGRAM_ID}")
    print(f"family_id:       {FAMILY_ID}")
    print(f"max_images:      {MAX_IMAGES}")
    print(f"model:           {MODEL_NAME}")
    print(f"anchor slot 0:   {BOTTOM_ANCHOR_PATH}  [{BOTTOM_ANCHOR_ROLE}]")
    print(f"anchor slot 1:   {ASSET01_PATH}  [{ASSET01_ROLE}]")
    print(f"output_dir:      output/keysuri_preview/korea_bottom_rotation/qa_pilot_v6/family_a/")
    print(f"image_generator: NOT called — direct Vertex AI multi-ref")
    print(f"verdict:         PASS / FAIL only (no CONDITIONAL_PASS)")
    print()

    if not BOTTOM_ANCHOR_ABS.is_file():
        print(f"[ERROR] Bottom anchor (105936) not found at {BOTTOM_ANCHOR_ABS}")
        sys.exit(1)

    if not PROJECT_ID:
        print("[ERROR] GENIE_VERTEX_PROJECT_ID or GOOGLE_CLOUD_PROJECT not set")
        sys.exit(1)

    QA_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = _stamp()

    prompt_infos = []
    for case in WEATHER_CASES[:MAX_IMAGES]:
        print(f"\n[Building prompt: {case['label']}]")
        info = _build_and_save_prompt(case, QA_OUTPUT_DIR, stamp)
        prompt_infos.append(info)

    image_results = []
    for i, prompt_info in enumerate(prompt_infos, start=1):
        print(f"\n[Generating image {i}/{MAX_IMAGES}: {prompt_info['label']}]")
        img_result = _generate_image_bottom_anchor(prompt_info, QA_OUTPUT_DIR, stamp, i)
        image_results.append(img_result)

    print("\n[Building contact sheet]")
    _make_contact_sheet([r["image_path"] for r in image_results], QA_OUTPUT_DIR, stamp)

    print("\n[Writing review report]")
    report_path = _write_review_report(image_results, prompt_infos, QA_OUTPUT_DIR, stamp)

    print("\n=== QA Pilot v6 Complete ===")
    print(f"Images generated: {len(image_results)}")
    for r in image_results:
        rel = r["image_path"].relative_to(REPO) if r["image_path"].is_file() else "MISSING"
        print(f"  [{r['index']}] {r['label']} → {rel}")
    print(f"Review report:    {report_path.relative_to(REPO)}")
    print()
    print("Confirmations:")
    print("  no watermark, no registry, no email, no service_full_run")
    print("  no Scheduler, no customer delivery, no secrets changed")
    print("  no image_generator.py called")
    print("  variation gate unchanged (KEYSURI_KOREA_BOTTOM_VARIATION_ENABLED not set)")
    print()
    print("Next step: owner visual inspection — PASS or FAIL only.")
    print("Gate 1 check: does output match 105936 identity/register?")


if __name__ == "__main__":
    run_qa_pilot()
