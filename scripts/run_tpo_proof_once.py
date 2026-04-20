"""One-shot: full today_genie feeds → text → validate → images → timestamped artifacts under output/.

Reader-facing handoff HTML is assembled in `_proof_html_body` (success: failure_mode False;
failure: failure_mode True). Operator/raw diagnostics stay in `.operator.txt` or optional debug HTML.
See ops/TODAY_GENIE_TPO_PROOF_SPEC.md.
"""
from __future__ import annotations

import html
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo

from fastapi import HTTPException

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from prompts import today_genie_json_recovery_suffix
_FEED_FILES = [
    ("TODAY_GENIE_OVERNIGHT_US_MARKET_JSON", "overnight_us_market.json"),
    ("TODAY_GENIE_MACRO_INDICATORS_JSON", "macro_indicators.json"),
    ("TODAY_GENIE_TOP_MACRO_ISSUES_JSON", "top_macro_issues.json"),
    ("TODAY_GENIE_TOP_MARKET_NEWS_JSON", "top_market_news.json"),
    ("TODAY_GENIE_KOREA_MARKET_SCHEDULE_JSON", "korea_market_schedule.json"),
    ("TODAY_GENIE_RISK_FACTORS_JSON", "risk_factors.json"),
    ("TODAY_GENIE_KOREA_JAPAN_INDICES_JSON", "korea_japan_indices.json"),
]


def _load_feeds_or_exit() -> dict[str, object]:
    feeds_dir = _REPO / "ops/feeds"
    out: dict[str, object] = {}
    for env_key, fname in _FEED_FILES:
        path = feeds_dir / fname
        if not path.is_file():
            print(json.dumps({"error": "missing_feed_file", "path": str(path)}, ensure_ascii=False))
            sys.exit(10)
        try:
            val = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            print(json.dumps({"error": "invalid_feed_json", "path": str(path), "message": str(e)}, ensure_ascii=False))
            sys.exit(11)
        if val is None or (isinstance(val, dict) and len(val) == 0) or (isinstance(val, list) and len(val) == 0):
            print(json.dumps({"error": "empty_feed", "path": str(path)}, ensure_ascii=False))
            sys.exit(12)
        out[env_key] = val
        os.environ[env_key] = json.dumps(val, ensure_ascii=False, separators=(",", ":"))
    return out


def _feed_anchors(ri: dict[str, object]) -> list[str]:
    parts: list[str] = []
    for key in (
        "overnight_us_market",
        "macro_indicators",
        "top_macro_issues",
        "top_market_news",
        "risk_factors",
        "korea_japan_indices",
    ):
        parts.append(json.dumps(ri.get(key, ""), ensure_ascii=False)[:4000])
    sched = ri.get("korea_market_schedule")
    if isinstance(sched, dict):
        parts.append(json.dumps(sched, ensure_ascii=False)[:2000])
    blob = " ".join(parts).lower()
    found: set[str] = set()
    found.update(re.findall(r"\b\d{3,5}\.\d{1,2}\b", blob))
    found.update(
        re.findall(
            r"\b(?:cpi|nasdaq|spx|s&p|inflation|geopolitics|ust|fed|kosdaq|kospi|krx)\b",
            blob,
        )
    )
    return sorted(found)


def _prompts_content_reactive(
    ri: dict[str, object], p_studio: str, p_out: str, data: dict[str, object] | None = None
) -> bool:
    comb = (p_studio + "\n" + p_out).lower()
    comb_raw = p_studio + "\n" + p_out
    for a in _feed_anchors(ri):
        al = a.lower().strip()
        if len(al) >= 3 and al in comb:
            return True
    for n in ri.get("top_market_news", []) or []:
        if not isinstance(n, dict):
            continue
        h = (n.get("headline") or "").lower()
        if len(h) >= 12:
            for piece in re.split(r"[^\w]+", h):
                if len(piece) >= 6 and piece in comb:
                    return True
    if data:
        for w in (data.get("key_watchpoints") or [])[:3]:
            if not isinstance(w, dict):
                continue
            hl = str(w.get("headline") or "")
            for m in re.finditer(r"[가-힣]{3,}", hl):
                frag = m.group()
                if len(frag) >= 3 and frag in comb_raw:
                    return True
    return False


def _roulette_judgment(
    ri: dict[str, object],
    p_studio: str,
    p_out: str,
    *,
    data: dict[str, object] | None = None,
) -> tuple[str, list[str]]:
    comb = (p_studio + "\n" + p_out).lower()
    clichés = ("cafe terrace", "coffee shop", "rooftop bar", "blue cyclorama", "identical blazer")
    cliché_hits = [c for c in clichés if c in comb]
    reactive = _prompts_content_reactive(ri, p_studio, p_out, data=data)
    reasons: list[str] = []
    if reactive:
        reasons.append("스튜디오/야외 프롬프트에 피드에서 온 구체 토큰(뉴스·수치·매크로 단어)이 일부 반영됨.")
    else:
        reasons.append("프롬프트에 피드 헤드라인/수치/매크로 키워드가 직접적으로 드러나지 않음(한글 재서술만일 수 있음).")
    if "terrace" in comb and ("cafe" in comb or "coffee" in comb):
        reasons.append("하단에 terrace/cafe 조합 → 자주 반복되는 야외 슬롯으로 읽힘.")
    if len(cliché_hits) >= 2:
        reasons.append("고정 룰렛 클리셔 다중: " + ", ".join(cliché_hits))
        return "FAIL", reasons
    if reactive:
        reasons.append("배경·톤은 무드 레이어와 함께 피드 근거와 연동된 방향으로 읽힘.")
        return "PASS", reasons
    reasons.append("내용-반응 연결이 약해 룰렛 반복 위험이 남음.")
    return "FAIL", reasons


def _tpo_judgment_text(
    *,
    title: str,
    summary: str,
    mood: str,
    basis: str,
    p_studio: str,
    p_out: str,
    images_ok: bool,
) -> tuple[str, list[str]]:
    reasons: list[str] = []
    low = (title + " " + summary).lower()
    if _summary_watch_wait_filler(summary):
        reasons.append("요약이 관망·신중 완충형으로만 읽힘.")
        return "FAIL", reasons
    if len([x for x in (title, summary) if x.strip()]) < 2:
        reasons.append("타이틀/요약 공백.")
        return "FAIL", reasons
    if mood in ("risk_heavy_tense", "mixed_cautious", "optimistic_energetic", "soft_lifestyle_human"):
        reasons.append(f"무드 상태 {mood}가 브리핑 톤과 연동 가능.")
    else:
        reasons.append("무드 상태가 허용 집합 밖.")
        return "FAIL", reasons
    ps = p_studio.lower()
    if (
        "studio" in ps
        or "broadcast" in ps
        or "스튜디오" in p_studio
        or "city morning" in ps
        or "urban morning" in ps
        or "downtown" in ps
        or "morning commute" in ps
        or "도심" in p_studio
        or "아침 거리" in p_studio
    ):
        reasons.append("상단: 스튜디오 앵커 또는 도심 아침 히어로 맥락.")
    else:
        reasons.append("상단 프롬프트에 스튜디오/도심 아침 히어로 맥락이 약함.")
    if any(x in p_out.lower() for x in ("outdoor", "urban", "street", "city", "terrace", "야외")):
        reasons.append("하단: 도심/야외 금융·라이프스타일 맥락.")
    else:
        reasons.append("하단 야외/도심 맥락이 약함.")
    if not images_ok:
        reasons.append("이미지 파일 생성 실패로 시각 TPO 확정 불가.")
        return "FAIL", reasons
    return "PASS", reasons


def _mood_prefix_for_image_prompts(data: dict) -> str:
    """Align with output/render_bottom_tpo_once._mood_prefix (main.py has no export)."""
    mood = (data.get("image_briefing_mood_state") or "").strip()
    basis = (data.get("image_mood_basis") or "").strip()
    if not mood and not basis:
        return ""
    parts: list[str] = []
    if mood:
        parts.append(f"BRIEFING_MOOD_STATE={mood}")
    if basis:
        parts.append(f"MOOD_BASIS={basis}")
    return "[" + " | ".join(parts) + "]\n\n"


def _today_genie_local_stamp(kst: datetime) -> str:
    """Local artifact timestamp: MMDD_HHMM (KST)."""
    return kst.strftime("%m%d_%H%M")


def _repo_rel(path: Path) -> str:
    return path.resolve().relative_to(_REPO.resolve()).as_posix()


def _summary_watch_wait_filler(summary: str) -> bool:
    s = summary.strip()
    if len(s) < 100:
        return True
    vague = ("명확한 신호", "관망", "신중", "섣부른", "흐름을 확인", "단정하지")
    hits = sum(1 for v in vague if v in s)
    digits = len(re.findall(r"\d", s))
    return hits >= 4 and digits < 2


def main() -> int:
    os.chdir(_REPO)
    sys.path.insert(0, str(_REPO))
    prof: dict[str, float] = {}
    t_wall = time.perf_counter()
    t = time.perf_counter()
    _load_feeds_or_exit()
    prof["feed_load_sec"] = round(time.perf_counter() - t, 4)

    from image_exec_suffixes import today_genie_suffix_outdoor_daily, today_genie_suffix_studio_hero
    from image_generator import generate_image_file
    from main import (
        PROJECT_ID,
        VERTEX_LOCATION,
        VERTEX_MODEL,
        build_full_prompt,
        build_runtime_input,
        call_gemini,
        parse_model_json,
        validate_today_genie,
    )
    from renderers import finalize_today_genie_hashtag_list

    image_model = os.getenv("VERTEX_IMAGE_MODEL", "gemini-2.5-flash-image")

    kst = datetime.now(ZoneInfo("Asia/Seoul"))
    run_id = kst.strftime("%Y-%m-%d %H:%M:%S %Z")
    stamp = _today_genie_local_stamp(kst)
    out_dir = _REPO / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_json = out_dir / f"today_genie_preview_{stamp}.json"
    top_img = out_dir / f"GENIE_EMAIL_today_genie_top_tpo_run_{stamp}.jpg"
    bot_img = out_dir / f"GENIE_EMAIL_today_genie_bottom_tpo_run_{stamp}.jpg"
    proof_html = out_dir / f"today_genie_tpo_proof_{stamp}.html"
    json_snapshot_rel = _repo_rel(out_json)
    ref = _REPO / "static/email/GENIE_REF_today_genie_master_v1.jpg"
    status = {"content": "failure", "image": "failure", "html": "failure"}
    err: list[str] = []
    mode = "today_genie"
    ri: dict[str, object] = {}
    data: dict[str, object] = {}
    val = None
    raw: str | None = None

    t = time.perf_counter()
    ri = build_runtime_input(mode)
    prof["runtime_input_build_sec"] = round(time.perf_counter() - t, 4)
    if ri.get("input_feed_status") != "full":
        err.append(f"input_feed_status={ri.get('input_feed_status')} (need full feeds)")
        image_run = _image_run_skipped_both("input_feed_not_full", top_img, bot_img)
        out_json.write_text(
            json.dumps(
                {
                    "error": err,
                    "runtime_input": ri,
                    "image_run": image_run,
                    "artifacts": {
                        "preview_json": json_snapshot_rel,
                        "proof_html": _repo_rel(proof_html),
                        "top_image": _repo_rel(top_img),
                        "bottom_image": _repo_rel(bot_img),
                    },
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        _write_fail_proof(
            proof_html,
            run_id,
            err,
            ri,
            status,
            top_img,
            bot_img,
            json_snapshot_rel=json_snapshot_rel,
            tpo_verdict="FAIL",
            tpo_reasons=err,
            roulette_verdict="FAIL",
            roulette_reasons=err,
            image_run=image_run,
            stage_timings_sec=prof,
            wall_start=t_wall,
            raw_text=None,
        )
        print(
            json.dumps(
                {
                    "status": status,
                    "errors": err,
                    "run_profile_sec": prof,
                    "artifacts": {
                        "preview_json": json_snapshot_rel,
                        "proof_html": _repo_rel(proof_html),
                        "operator_diagnostic": _repo_rel(_operator_diagnostic_file(proof_html)),
                    },
                },
                ensure_ascii=False,
            )
        )
        return 20

    try:
        t = time.perf_counter()
        prompt = build_full_prompt(mode, ri)
        prof["prompt_build_sec"] = round(time.perf_counter() - t, 4)
        t = time.perf_counter()
        raw = call_gemini(prompt, mode)
        prof["model_inference_sec"] = round(time.perf_counter() - t, 4)
        t = time.perf_counter()
        try:
            data = parse_model_json(raw, mode)
        except HTTPException as e_parse:
            det = e_parse.detail if isinstance(e_parse.detail, dict) else {}
            if det.get("reason") == "json_parse_error":
                t_rec = time.perf_counter()
                raw = call_gemini(prompt + today_genie_json_recovery_suffix(), mode)
                prof["model_inference_recovery_sec"] = round(time.perf_counter() - t_rec, 4)
                prof["json_recovery_second_call"] = True
                data = parse_model_json(raw, mode)
            else:
                raise
        else:
            prof["json_recovery_second_call"] = False
        data["hashtags"] = finalize_today_genie_hashtag_list(data, ri)
        val = validate_today_genie(data, ri)
        prof["parse_finalize_validate_sec"] = round(time.perf_counter() - t, 4)
        if val.result == "block":
            err.append(
                "validation_block: "
                + json.dumps([{"code": i.code, "message": i.message} for i in val.issues[:20]], ensure_ascii=False)
            )
            image_run = _image_run_skipped_both("validation_block", top_img, bot_img)
            snap = {
                "run_meta": {
                    "datetime": run_id,
                    "mode": mode,
                    "validation": "block",
                    "local_stamp": stamp,
                },
                "runtime_input": ri,
                "data": data,
                "issues": [{"code": i.code, "message": i.message, "severity": i.severity} for i in val.issues],
                "raw_preview": raw[:6000],
                "image_run": image_run,
                "artifacts": {
                    "preview_json": json_snapshot_rel,
                    "proof_html": _repo_rel(proof_html),
                    "top_image": _repo_rel(top_img),
                    "bottom_image": _repo_rel(bot_img),
                },
            }
            out_json.write_text(json.dumps(snap, ensure_ascii=False, indent=2), encoding="utf-8")
            status["html"] = "success"
            _write_fail_proof(
                proof_html,
                run_id,
                err,
                ri,
                status,
                top_img,
                bot_img,
                json_snapshot_rel=json_snapshot_rel,
                tpo_verdict="FAIL",
                tpo_reasons=[i.message for i in val.issues if i.severity == "error"][:12],
                roulette_verdict="FAIL",
                roulette_reasons=["콘텐츠 생성 단계 validation_block"],
                data=data,
                image_run=image_run,
                validation_result=val.result,
                stage_timings_sec=prof,
                wall_start=t_wall,
                raw_text=raw,
            )
            print(
                json.dumps(
                    {
                        "status": status,
                        "errors": err,
                        "run_profile_sec": prof,
                        "artifacts": {
                            "preview_json": json_snapshot_rel,
                            "proof_html": _repo_rel(proof_html),
                            "operator_diagnostic": _repo_rel(_operator_diagnostic_file(proof_html)),
                        },
                    },
                    ensure_ascii=False,
                )
            )
            return 2
        if val.result == "draft_only":
            err.append(
                "validation_draft_only: "
                + json.dumps([{"code": i.code, "message": i.message} for i in val.issues[:24]], ensure_ascii=False)
            )
            image_run = _image_run_skipped_both("validation_draft_only", top_img, bot_img)
            snap = {
                "run_meta": {
                    "datetime": run_id,
                    "mode": mode,
                    "validation": "draft_only",
                    "local_stamp": stamp,
                },
                "runtime_input": ri,
                "data": data,
                "issues": [{"code": i.code, "message": i.message, "severity": i.severity} for i in val.issues],
                "raw_preview": raw[:6000],
                "image_run": image_run,
                "artifacts": {
                    "preview_json": json_snapshot_rel,
                    "proof_html": _repo_rel(proof_html),
                    "top_image": _repo_rel(top_img),
                    "bottom_image": _repo_rel(bot_img),
                },
            }
            out_json.write_text(json.dumps(snap, ensure_ascii=False, indent=2), encoding="utf-8")
            status["html"] = "success"
            _write_fail_proof(
                proof_html,
                run_id,
                err,
                ri,
                status,
                top_img,
                bot_img,
                json_snapshot_rel=json_snapshot_rel,
                tpo_verdict="FAIL",
                tpo_reasons=[i.message for i in val.issues][:16],
                roulette_verdict="FAIL",
                roulette_reasons=["자동 검수 경고(draft_only): 게시 확정 전 확인 필요"],
                data=data,
                image_run=image_run,
                validation_result=val.result,
                stage_timings_sec=prof,
                wall_start=t_wall,
                raw_text=raw,
            )
            print(
                json.dumps(
                    {
                        "status": status,
                        "errors": err,
                        "run_profile_sec": prof,
                        "artifacts": {
                            "preview_json": json_snapshot_rel,
                            "proof_html": _repo_rel(proof_html),
                            "operator_diagnostic": _repo_rel(_operator_diagnostic_file(proof_html)),
                        },
                    },
                    ensure_ascii=False,
                )
            )
            return 7
        status["content"] = "success"
    except HTTPException as e:
        err.append(f"http:{e.detail}")
        image_run = _image_run_skipped_both("http_exception", top_img, bot_img)
        out_json.write_text(
            json.dumps(
                {
                    "run_meta": {
                        "datetime": run_id,
                        "mode": mode,
                        "local_stamp": stamp,
                        "phase": "http",
                    },
                    "errors": err,
                    "runtime_input": ri,
                    "data": data,
                    "validation_result": getattr(val, "result", None) if val else None,
                    "image_run": image_run,
                    "artifacts": {
                        "preview_json": json_snapshot_rel,
                        "proof_html": _repo_rel(proof_html),
                        "top_image": _repo_rel(top_img),
                        "bottom_image": _repo_rel(bot_img),
                    },
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        status["html"] = "success"
        raw_blob = raw
        if raw_blob is None and isinstance(e.detail, dict):
            rp = e.detail.get("raw_preview")
            if isinstance(rp, str):
                raw_blob = rp
        _write_fail_proof(
            proof_html,
            run_id,
            err,
            ri,
            status,
            top_img,
            bot_img,
            json_snapshot_rel=json_snapshot_rel,
            tpo_verdict="FAIL",
            tpo_reasons=err,
            roulette_verdict="FAIL",
            roulette_reasons=err,
            data=data,
            image_run=image_run,
            validation_result=getattr(val, "result", None) if val else None,
            stage_timings_sec=prof,
            wall_start=t_wall,
            raw_text=raw_blob,
        )
        print(
            json.dumps(
                {
                    "status": status,
                    "errors": err,
                    "run_profile_sec": prof,
                    "artifacts": {
                        "preview_json": json_snapshot_rel,
                        "proof_html": _repo_rel(proof_html),
                        "operator_diagnostic": _repo_rel(_operator_diagnostic_file(proof_html)),
                    },
                },
                ensure_ascii=False,
            )
        )
        return 1
    except Exception as e:
        err.append(f"content:{type(e).__name__}:{e}")
        image_run = _image_run_skipped_both("content_pipeline_exception", top_img, bot_img)
        out_json.write_text(
            json.dumps(
                {
                    "run_meta": {
                        "datetime": run_id,
                        "mode": mode,
                        "local_stamp": stamp,
                        "phase": "exception",
                    },
                    "errors": err,
                    "runtime_input": ri,
                    "data": data,
                    "validation_result": getattr(val, "result", None) if val else None,
                    "image_run": image_run,
                    "artifacts": {
                        "preview_json": json_snapshot_rel,
                        "proof_html": _repo_rel(proof_html),
                        "top_image": _repo_rel(top_img),
                        "bottom_image": _repo_rel(bot_img),
                    },
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        status["html"] = "success"
        _write_fail_proof(
            proof_html,
            run_id,
            err,
            ri,
            status,
            top_img,
            bot_img,
            json_snapshot_rel=json_snapshot_rel,
            tpo_verdict="FAIL",
            tpo_reasons=err,
            roulette_verdict="FAIL",
            roulette_reasons=err,
            data=data,
            image_run=image_run,
            validation_result=getattr(val, "result", None) if val else None,
            stage_timings_sec=prof,
            wall_start=t_wall,
            raw_text=raw,
        )
        print(
            json.dumps(
                {
                    "status": status,
                    "errors": err,
                    "run_profile_sec": prof,
                    "artifacts": {
                        "preview_json": json_snapshot_rel,
                        "proof_html": _repo_rel(proof_html),
                        "operator_diagnostic": _repo_rel(_operator_diagnostic_file(proof_html)),
                    },
                },
                ensure_ascii=False,
            )
        )
        return 1

    snap = {
        "run_meta": {
            "datetime": run_id,
            "mode": mode,
            "project_id": PROJECT_ID,
            "vertex_location": VERTEX_LOCATION,
            "text_model": VERTEX_MODEL,
            "image_model": image_model,
            "validation_result": val.result,
            "local_stamp": stamp,
        },
        "runtime_input": ri,
        "data": data,
        "image_run": {},
        "artifacts": {
            "preview_json": json_snapshot_rel,
            "proof_html": _repo_rel(proof_html),
            "operator_diagnostic": _repo_rel(_operator_diagnostic_file(proof_html)),
            "top_image": _repo_rel(top_img),
            "bottom_image": _repo_rel(bot_img),
        },
    }

    mood = (data.get("image_briefing_mood_state") or "").strip()
    basis = (data.get("image_mood_basis") or "").strip()
    p_studio = (data.get("image_prompt_studio") or "").strip()
    p_out = (data.get("image_prompt_outdoor") or "").strip()
    prefix = _mood_prefix_for_image_prompts(data)

    if not p_studio or not p_out:
        err.append("missing_image_prompts_after_validation")
        status["html"] = "success"
        image_run = _image_run_skipped_both("missing_image_prompts_after_validation", top_img, bot_img)
        snap["image_run"] = image_run
        out_json.write_text(json.dumps(snap, ensure_ascii=False, indent=2), encoding="utf-8")
        _write_fail_proof(
            proof_html,
            run_id,
            err,
            ri,
            status,
            top_img,
            bot_img,
            json_snapshot_rel=json_snapshot_rel,
            tpo_verdict="FAIL",
            tpo_reasons=err,
            roulette_verdict="FAIL",
            roulette_reasons=err,
            data=data,
            image_run=image_run,
            validation_result=val.result,
            stage_timings_sec=prof,
            wall_start=t_wall,
            raw_text=raw,
        )
        print(
            json.dumps(
                {
                    "status": status,
                    "errors": err,
                    "run_profile_sec": prof,
                    "artifacts": {
                        "preview_json": json_snapshot_rel,
                        "proof_html": _repo_rel(proof_html),
                        "operator_diagnostic": _repo_rel(_operator_diagnostic_file(proof_html)),
                    },
                },
                ensure_ascii=False,
            )
        )
        return 3

    images_ok = False
    top_done = False
    bot_done = False
    top_err: str | None = None
    bot_err: str | None = None
    try:
        t = time.perf_counter()
        generate_image_file(
            prompt=prefix + p_studio + "\n\n" + today_genie_suffix_studio_hero(),
            output_path=top_img,
            model_name=image_model,
            reference_image_path=ref,
            project_id=PROJECT_ID or None,
            location=VERTEX_LOCATION,
        )
        prof["image_generation_top_sec"] = round(time.perf_counter() - t, 4)
        top_done = True
    except Exception as e:
        top_err = f"{type(e).__name__}:{e}"
        err.append(f"image_top:{top_err}")
    try:
        t = time.perf_counter()
        generate_image_file(
            prompt=prefix
            + p_out
            + "\n\n"
            + today_genie_suffix_outdoor_daily(ri, variation_seed=stamp),
            output_path=bot_img,
            model_name=image_model,
            reference_image_path=ref,
            project_id=PROJECT_ID or None,
            location=VERTEX_LOCATION,
        )
        prof["image_generation_bottom_sec"] = round(time.perf_counter() - t, 4)
        bot_done = True
    except Exception as e:
        bot_err = f"{type(e).__name__}:{e}"
        err.append(f"image_bottom:{bot_err}")
    images_ok = top_done and bot_done
    if images_ok:
        status["image"] = "success"
    image_run = _image_run_from_attempts(
        top_done=top_done,
        bottom_done=bot_done,
        top_error=top_err,
        bottom_error=bot_err,
        top_path=top_img,
        bottom_path=bot_img,
    )
    snap["image_run"] = image_run
    out_json.write_text(json.dumps(snap, ensure_ascii=False, indent=2), encoding="utf-8")

    title = (data.get("title") or "").strip()
    summary = (data.get("summary") or "").strip()
    wps = data.get("key_watchpoints") or []
    rks = data.get("risk_check") or []

    tpo_verdict, tpo_reasons = _tpo_judgment_text(
        title=title,
        summary=summary,
        mood=mood,
        basis=basis,
        p_studio=p_studio,
        p_out=p_out,
        images_ok=images_ok,
    )
    roulette_verdict, roulette_reasons = _roulette_judgment(ri, p_studio, p_out, data=data)

    wp_html = _format_watchpoints(wps)
    rk_html = _format_risks(rks)

    t = time.perf_counter()
    body = _proof_html_body(
        run_id=run_id,
        ri=ri,
        eyebrow_line=_briefing_eyebrow_line(ri, run_id),
        val=val,
        title=title,
        summary=summary,
        wp_html=wp_html,
        rk_html=rk_html,
        mood=mood,
        basis=basis,
        p_studio=p_studio,
        p_out=p_out,
        prefix_display=html.escape(prefix.strip() or "없음"),
        proof_html=proof_html,
        json_snapshot_rel=json_snapshot_rel,
        tpo_verdict=tpo_verdict,
        tpo_reasons=tpo_reasons,
        roulette_verdict=roulette_verdict,
        roulette_reasons=roulette_reasons,
        extra_errors=err,
        image_run=image_run,
        hashtag_block=_proof_hashtag_html(data.get("hashtags"), omit_muted_label=True),
        failure_mode=False,
        handoff_data=data,
        validation_result=getattr(val, "result", None),
    )
    prof["proof_html_body_sec"] = round(time.perf_counter() - t, 4)
    # Hard guarantee: generated bottom JPEG must appear in customer handoff HTML.
    bs = image_run.get("bottom") if isinstance(image_run, dict) else None
    if isinstance(bs, dict) and bs.get("generated_this_run") is True:
        bn = Path(str(bs.get("path", ""))).name
        if bn and bn not in body:
            raise RuntimeError(
                "today_genie customer HTML omitted the bottom image block despite successful bottom generation"
            )
    _write_proof_bundle(
        proof_html,
        body,
        run_id=run_id,
        ri=ri,
        extra_errors=err,
        tpo_reasons=tpo_reasons,
        roulette_reasons=roulette_reasons,
        validation_result=val.result,
        json_snapshot_rel=json_snapshot_rel,
        stage_timings_sec=prof,
        wall_start=t_wall,
    )
    status["html"] = "success"
    print(
        json.dumps(
            {
                "status": status,
                "errors": err,
                "tpo": tpo_verdict,
                "roulette": roulette_verdict,
                "run_profile_sec": prof,
                "artifacts": {
                    "preview_json": json_snapshot_rel,
                    "proof_html": _repo_rel(proof_html),
                    "operator_diagnostic": _repo_rel(_operator_diagnostic_file(proof_html)),
                    "top_image": _repo_rel(top_img),
                    "bottom_image": _repo_rel(bot_img),
                },
            },
            ensure_ascii=False,
        )
    )
    return 0 if status["image"] == "success" and val.result == "pass" else 4


def _image_run_skipped_both(reason: str, top_path: Path, bottom_path: Path) -> dict[str, Any]:
    """No image bytes written this run (feeds, validation, or missing prompts)."""
    return {
        "top": {
            "generated_this_run": False,
            "status": "skipped",
            "reason": reason,
            "path": _repo_rel(top_path),
        },
        "bottom": {
            "generated_this_run": False,
            "status": "skipped",
            "reason": reason,
            "path": _repo_rel(bottom_path),
        },
    }


_MOOD_STATE_LABEL_KO: dict[str, str] = {
    "risk_heavy_tense": "리스크가 무겁고 긴장감이 큰 국면",
    "mixed_cautious": "혼조세 속 신중한 국면",
    "optimistic_energetic": "낙관적이고 활기 있는 국면",
    "soft_lifestyle_human": "부드러운 라이프스타일·휴먼 톤",
}

_PROOF_IMAGE_STATUS_KO: dict[str, str] = {
    "generated": "이번 실행에서 생성됨",
    "skipped": "건너뜀",
    "failed": "실패",
    "unknown": "알 수 없음",
}

_PROOF_IMAGE_REASON_KO: dict[str, str] = {
    "validation_block": "검증에서 차단되어 이미지를 생성하지 않음",
    "validation_draft_only": "자동 검수 경고로 게시 확정 전 단계로 분류되어 이미지를 생성하지 않음",
    "input_feed_not_full": "입력 피드가 완전하지 않아 이미지를 생성하지 않음",
    "missing_image_prompts_after_validation": "검증 후 이미지용 문구가 없어 생성하지 않음",
    "http_exception": "연결(HTTP) 오류로 중단됨",
    "content_pipeline_exception": "본문 생성 단계에서 예외가 발생함",
    "missing_image_run_metadata": "이미지 실행 정보가 없음",
    "not_attempted": "이번 실행에서 시도하지 않음",
    "unspecified_proof_path": "증빙 경로가 지정되지 않음",
}


def _proof_image_status_ko(status: str) -> str:
    s = (status or "").strip().lower()
    if not s:
        return "알 수 없음"
    return _PROOF_IMAGE_STATUS_KO.get(s, "기타 상태")


def _proof_image_reason_ko(reason: str) -> str:
    """Map internal reason codes to Korean; avoid dumping long English traces on the default surface."""
    r = (reason or "").strip()
    if not r:
        return ""
    if r in _PROOF_IMAGE_REASON_KO:
        return _PROOF_IMAGE_REASON_KO[r]
    low = r.lower()
    if low.startswith("image_top:"):
        return "상단(스튜디오) 이미지 생성 중 오류. 자세한 내용은 미리보기 기록을 확인하세요."
    if low.startswith("image_bottom:"):
        return "하단(야외) 이미지 생성 중 오류. 자세한 내용은 미리보기 기록을 확인하세요."
    if low.startswith("http:"):
        return "연결(HTTP) 오류가 발생함. 미리보기 기록을 확인하세요."
    if low.startswith("content:"):
        return "본문 생성 중 오류가 발생함. 미리보기 기록을 확인하세요."
    if "validation_block" in low:
        return _PROOF_IMAGE_REASON_KO["validation_block"]
    if all(ord(c) < 128 for c in r) and len(r) > 80:
        return "기술 사유가 있습니다. 미리보기 기록의 오류 내용을 확인하세요."
    if "missing_image_run_metadata" in r:
        return _PROOF_IMAGE_REASON_KO["missing_image_run_metadata"]
    return r


def _pass_fail_ko(label: str) -> str:
    v = (label or "").strip().upper()
    if v == "PASS":
        return "통과"
    if v == "FAIL":
        return "불합격"
    return label or "—"


def _validation_gate_ko(vr: object) -> str:
    s = str(vr or "").strip().lower()
    if s == "block":
        return "차단"
    if s == "pass":
        return "통과"
    if s == "draft_only":
        return "초안만 허용"
    if s in ("n/a", "none", ""):
        return "해당 없음"
    return str(vr)


def _feed_status_ko(val: object) -> str:
    s = str(val or "").strip().lower()
    if s == "full":
        return "완전"
    if s == "partial":
        return "일부"
    if s == "none":
        return "없음"
    return str(val)


def _proof_image_direction_html(mood: str, basis: str, p_studio: str, p_out: str) -> str:
    """Default proof: Korean-only; raw English prompts only in TODAY_GENIE_PROOF_IMAGE_DEBUG."""
    mood_key = (mood or "").strip()
    mood_ko = _MOOD_STATE_LABEL_KO.get(mood_key, "지정되지 않은 무드")
    intro = (
        '<p class="muted">이미지는 생성 파이프라인에서 <strong>영문 프롬프트</strong>로 호출됩니다. '
        "이 증빙의 기본 화면에서는 원문을 숨기고, 한국어로 읽을 수 있는 요약만 보여 줍니다. "
        "원문이 필요하면 <code>TODAY_GENIE_PROOF_IMAGE_DEBUG=1</code>을 설정하세요.</p>"
    )
    mood_block = (
        "<p><strong>이미지 분위기 요약</strong></p>"
        f'<div class="box">{html.escape(mood_ko)}</div>'
    )
    basis_block = (
        "<p><strong>브리핑 톤·이미지 연결 요약</strong></p>"
        f'<div class="box">{html.escape(basis or "(없음)")}</div>'
    )
    slot_hint = (
        "<p><strong>스튜디오 이미지 방향</strong></p>"
        '<p class="muted">장전 브리핑 무드에 맞춘 상단(스튜디오·도심 아침) 장면으로 생성하도록 지시합니다. '
        "영문 프롬프트 원문은 디버그 모드에서만 표시합니다.</p>"
        "<p><strong>야외 이미지 방향</strong></p>"
        '<p class="muted">같은 인물의 야외·일상 슬롯으로, 날씨·톤에 맞춘 하단 장면으로 생성하도록 지시합니다. '
        "영문 프롬프트 원문은 디버그 모드에서만 표시합니다.</p>"
    )
    core = intro + mood_block + basis_block + slot_hint
    if os.environ.get("TODAY_GENIE_PROOF_IMAGE_DEBUG", "").strip().lower() in ("1", "true", "yes"):
        token_line = (
            f'<p class="muted"><strong>디버그: 내부 무드 토큰</strong> <code>{html.escape(mood_key or "(없음)")}</code></p>'
        )
        raw = (
            token_line
            + "<h2>6a) 원문 스튜디오 프롬프트 (디버그)</h2>"
            + f'<div class="box">{html.escape(p_studio)}</div>'
            + "<h2>6b) 원문 야외 프롬프트 (디버그)</h2>"
            + f'<div class="box">{html.escape(p_out)}</div>'
        )
    else:
        raw = ""
    return core + raw


def _image_run_from_attempts(
    *,
    top_done: bool,
    bottom_done: bool,
    top_error: Optional[str],
    bottom_error: Optional[str],
    top_path: Path,
    bottom_path: Path,
) -> dict[str, Any]:
    def _slot(done: bool, err: Optional[str], path: Path) -> dict[str, Any]:
        rel = _repo_rel(path)
        if done:
            return {"generated_this_run": True, "status": "generated", "reason": "", "path": rel}
        if err:
            return {"generated_this_run": False, "status": "failed", "reason": err, "path": rel}
        return {
            "generated_this_run": False,
            "status": "skipped",
            "reason": "not_attempted",
            "path": rel,
        }

    return {
        "top": _slot(top_done, top_error, top_path),
        "bottom": _slot(bottom_done, bottom_error, bottom_path),
    }


def _proof_top_hero_html(
    image_run: dict[str, Any], *, include_status_caption: bool = False
) -> str:
    """Hero preview under title; only if this run wrote the top JPEG (no empty block).

    Reader-facing proofs omit 운영/상태 caption unless include_status_caption is True (debug).
    """
    if not isinstance(image_run, dict):
        return ""
    slot = image_run.get("top")
    if not isinstance(slot, dict) or slot.get("generated_this_run") is not True:
        return ""
    path = str(slot.get("path", ""))
    if not path:
        return ""
    img_src = Path(path).name
    img_part = (
        f'<p class="hero-img-wrap"><img src="{html.escape(img_src)}" '
        'alt="장전 브리핑 상단 이미지" /></p>'
    )
    if include_status_caption:
        return (
            '<p class="muted">상단(스튜디오) — 이번 실행에서 생성됨</p>'
            + img_part
        )
    return img_part


_HANDOFF_CSS = """
:root { color-scheme: light; }
body.handoff-page { font-family: system-ui, -apple-system, sans-serif; margin: 0; padding: 32px 24px 48px;
  background: linear-gradient(180deg, #f8fafc 0%, #f1f5f9 40%); color: #0f172a; max-width: 46rem;
  margin-left: auto; margin-right: auto; line-height: 1.65; font-size: 1rem; }
.handoff-header { margin-bottom: 2rem; }
.eyebrow { margin: 0 0 8px 0; font-size: 0.82rem; letter-spacing: 0.04em; text-transform: uppercase;
  color: #64748b; font-weight: 600; }
.handoff-title { margin: 0; font-size: 1.65rem; font-weight: 750; line-height: 1.35; letter-spacing: -0.02em; }
.draft-banner { background: #fff7ed; border: 1px solid #fdba74; border-radius: 12px; padding: 16px 18px;
  margin-bottom: 2rem; color: #9a3412; font-size: 0.95rem; }
.handoff-section { margin-bottom: 2.35rem; }
.handoff-section:last-of-type { margin-bottom: 0; }
.section-heading { margin: 0 0 10px 0; font-size: 1.12rem; font-weight: 700; color: #1e293b;
  padding-bottom: 8px; border-bottom: 1px solid #e2e8f0; }
.section-lede { margin: 0 0 14px 0; font-size: 0.92rem; color: #64748b; line-height: 1.55; }
.box { background: #fff; border: 1px solid #e2e8f0; border-radius: 12px; padding: 18px 20px;
  margin-top: 6px; white-space: pre-wrap; word-break: break-word;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04); }
.summary-box { font-size: 1.02rem; line-height: 1.7; }
.hero-img-wrap { margin: 12px 0 0 0; text-align: center; }
.hero-img-wrap img { max-width: 100%; height: auto; border: 1px solid #cbd5e1; border-radius: 12px;
  background: #e2e8f0; box-shadow: 0 4px 14px rgba(15, 23, 42, 0.06); }
.meta, .muted { color: #64748b; font-size: 0.9rem; line-height: 1.55; }
ul.handoff-list { margin: 10px 0 0 0; padding-left: 1.25rem; }
ul.handoff-list li { margin-bottom: 12px; }
ul.handoff-list li:last-child { margin-bottom: 0; }
.handoff-table-wrap { margin-top: 8px; overflow-x: auto; }
table.handoff-table { width: 100%; border-collapse: collapse; font-size: 0.98rem; background: #fff;
  border: 1px solid #e2e8f0; border-radius: 12px; overflow: hidden; }
.handoff-table td { padding: 12px 16px; border-bottom: 1px solid #f1f5f9; vertical-align: top; }
.handoff-table tr:last-child td { border-bottom: none; }
.handoff-table td:first-child { font-weight: 600; color: #334155; width: 36%; }
.indices-group-label { margin: 0 0 8px 0; font-size: 0.82rem; font-weight: 700; color: #475569;
  letter-spacing: 0.02em; }
.indices-group-label-global { margin-top: 1.25rem; }
.customer-admin-panel { margin-top: 3rem; padding: 22px 20px 18px; background: #f8fafc;
  border: 1px solid #cbd5e1; border-radius: 12px;
  box-shadow: 0 2px 8px rgba(15, 23, 42, 0.06); }
.customer-admin-panel .section-heading { margin-top: 0; font-size: 1rem; color: #334155; border-bottom-color: #cbd5e1; }
.customer-admin-panel .admin-grid { gap: 14px; }
.regen-request-slot { margin-top: 16px; padding-top: 16px; border-top: 1px dashed #cbd5e1; }
.regen-slot-label { margin: 0 0 10px 0; font-size: 0.82rem; font-weight: 600; color: #64748b; }
.regen-placeholder { display: inline-block; min-width: 12rem; padding: 10px 18px; text-align: center;
  font-size: 0.88rem; color: #94a3b8; background: #fff; border: 1px dashed #94a3b8; border-radius: 10px;
  cursor: default; user-select: none; }
.reader-admin { margin-top: 3rem; padding: 22px 20px; background: #fff; border: 1px solid #e2e8f0;
  border-radius: 12px; box-shadow: 0 1px 3px rgba(15, 23, 42, 0.05); }
.reader-admin .section-heading { border-bottom: none; padding-bottom: 4px; margin-bottom: 14px; font-size: 1rem; }
.admin-grid { display: flex; flex-direction: column; gap: 12px; }
.admin-row { display: grid; grid-template-columns: 7.5rem 1fr; gap: 12px; align-items: start; font-size: 0.92rem; }
.admin-label { color: #64748b; font-weight: 600; font-size: 0.82rem; line-height: 1.45; }
.admin-value { color: #0f172a; line-height: 1.5; word-break: break-word; }
@media (max-width: 520px) {
  .admin-row { grid-template-columns: 1fr; gap: 4px; }
}
.operator-debug-append { margin-top: 2.5rem; padding-top: 2rem; border-top: 2px dashed #cbd5e1; }
.tpo-pass { color: #15803d; font-weight: 700; }
.tpo-fail { color: #b91c1c; font-weight: 700; }
.investment-disclaimer { margin-top: 2rem; margin-bottom: 0; padding: 14px 16px 4px;
  border-top: 1px solid #e2e8f0; font-size: 0.84rem; line-height: 1.55; color: #64748b; }
"""


def _customer_investment_disclaimer_html() -> str:
    """Fixed customer-safe notice — not model-generated; not operator/debug."""
    return (
        '<p class="muted investment-disclaimer" role="note">'
        "본 브리핑은 시장 흐름과 정보를 빠르게 정리한 참고 자료이며, "
        "특정 금융상품의 매수·매도 등 투자 판단을 대신하거나 권유하지 않습니다. "
        "투자 결정과 그 결과에 대한 책임은 전적으로 본인에게 있습니다."
        "</p>"
    )


def _briefing_eyebrow_line(ri: dict[str, object], run_id: str) -> str:
    """Fixed eyebrow: 오늘의 지니 · 장전 브리핑 | YYYY년 M월 D일 (KST 기준 브리핑 일자)."""
    date_ko = ""
    td = ri.get("target_date")
    if isinstance(td, str) and len(td) >= 10:
        try:
            y, mo, d = td[:10].split("-")
            date_ko = f"{int(y)}년 {int(mo)}월 {int(d)}일"
        except (ValueError, IndexError):
            date_ko = ""
    if not date_ko:
        m = re.match(r"^\s*(\d{4})-(\d{2})-(\d{2})", run_id.strip())
        if m:
            date_ko = f"{int(m.group(1))}년 {int(m.group(2))}월 {int(m.group(3))}일"
    if not date_ko:
        date_ko = "일자 확인 필요"
    return f"오늘의 지니 · 장전 브리핑 | {date_ko}"


def _customer_reader_admin_panel(run_id: str) -> str:
    """Reader-safe admin/info box — no paths, codes, or operator language."""
    t = html.escape(run_id.strip())
    return "\n".join(
        [
            '<aside class="customer-admin-panel" aria-label="브리핑 안내">',
            '<h2 class="section-heading">브리핑 안내</h2>',
            '<div class="admin-grid">',
            '<div class="admin-row"><span class="admin-label">서비스</span>'
            '<span class="admin-value">오늘의 지니 장전 브리핑</span></div>',
            '<div class="admin-row"><span class="admin-label">상태</span>'
            '<span class="admin-value">브리핑이 준비되었습니다.</span></div>',
            f'<div class="admin-row"><span class="admin-label">생성 기준 시각</span><span class="admin-value">{t}</span></div>',
            '<div class="admin-row"><span class="admin-label">포함 항목</span>'
            '<span class="admin-value">장전 브리핑 본문과 상·하단 이미지가 함께 담겨 있습니다.</span></div>',
            "</div>",
            '<div class="regen-request-slot">',
            '<p class="regen-slot-label">다시 만들기</p>',
            '<div class="regen-placeholder" role="button" tabindex="0" aria-disabled="true">'
            "준비 중"
            "</div>",
            '<p class="muted" style="margin:8px 0 0 0;font-size:0.8rem;">'
            "같은 맥락으로 한 번 더 받아보실 수 있는 기능은 이후 이 자리에서 안내될 예정입니다. "
            "이 페이지는 오늘 장전 브리핑을 확인하는 용도입니다."
            "</p>",
            "</div>",
            "</aside>",
        ]
    )


def _proof_bottom_reader_html(image_run: dict[str, Any]) -> str:
    """Customer handoff: bottom daily image only when this run wrote the bottom JPEG."""
    if not isinstance(image_run, dict):
        return ""
    slot = image_run.get("bottom")
    if not isinstance(slot, dict) or slot.get("generated_this_run") is not True:
        return ""
    path = str(slot.get("path", ""))
    if not path:
        return ""
    img_src = Path(path).name
    inner = (
        '<section class="handoff-section handoff-visual">\n'
        f'<p class="hero-img-wrap"><img src="{html.escape(img_src)}" '
        'alt="장전 브리핑 하단 이미지" /></p>\n'
        "</section>"
    )
    return inner


_PLACEHOLDER_INDEX_CELL = "—"


def _format_overnight_index_slot(slot: object) -> str:
    if not isinstance(slot, dict):
        return ""
    close = slot.get("close")
    if close is None:
        return ""
    pct = slot.get("change_pct")
    pts = slot.get("change_pts")
    extras: list[str] = []
    if isinstance(pct, (int, float)):
        sign = "+" if pct > 0 else ""
        extras.append(f"{sign}{pct}%")
    if isinstance(pts, (int, float)) and pts != 0:
        extras.append(f"{pts:+.2f}pt" if isinstance(pts, float) else f"{pts:+d}pt")
    val = str(close)
    if extras:
        val = f"{val} ({', '.join(extras)})"
    return val


def _canonical_index_key_from_label(lab: str) -> str | None:
    t = lab.strip()
    if not t:
        return None
    u = t.upper().replace(" ", "")
    if "KOSPI" in u or "코스피" in t:
        return "KOSPI"
    if "KOSDAQ" in u or "코스닥" in t:
        return "KOSDAQ"
    if "NIKKEI" in u or "니케이" in t or "日経" in t:
        return "NIKKEI"
    if "NASDAQ" in u or "나스닥" in t:
        return "NASDAQ"
    if t.upper() == "DJI" or "다우" in t or ("DOW" in u and "JONES" in u):
        return "DJI"
    if "S&P" in t or "S＆P" in t or u == "SPX":
        return "SPX"
    return None


def _market_snapshot_canonical_values(ms: object) -> dict[str, str]:
    out: dict[str, str] = {}
    if not isinstance(ms, list):
        return out
    for item in ms:
        if not isinstance(item, dict):
            continue
        lab = str(item.get("label", "")).strip()
        val = str(item.get("value", "")).strip()
        key = _canonical_index_key_from_label(lab)
        if key and val:
            out[key] = val
    return out


def _index_cells_from_indices_dict(idx: object) -> dict[str, str]:
    """Map feed index objects (US + Korea/Japan) to canonical snapshot cells."""
    out: dict[str, str] = {}
    if not isinstance(idx, dict):
        return out
    wire = [
        ("SPX", "SPX"),
        ("NASDAQ", "NASDAQ"),
        ("DJI", "DJI"),
        ("NIKKEI", "NIKKEI"),
        ("N225", "NIKKEI"),
        ("NI225", "NIKKEI"),
        ("KOSPI", "KOSPI"),
        ("KOSDAQ", "KOSDAQ"),
    ]
    for raw_key, canon in wire:
        if canon in out:
            continue
        cell = _format_overnight_index_slot(idx.get(raw_key))
        if cell:
            out[canon] = cell
    return out


def _resolve_major_index_cells(ri: dict[str, object], hd: dict[str, object]) -> dict[str, str]:
    ov = ri.get("overnight_us_market") if isinstance(ri.get("overnight_us_market"), dict) else {}
    ov_idx = ov.get("indices") if isinstance(ov.get("indices"), dict) else {}
    kj = ri.get("korea_japan_indices") if isinstance(ri.get("korea_japan_indices"), dict) else {}
    kj_idx = kj.get("indices") if isinstance(kj.get("indices"), dict) else {}
    base: dict[str, str] = {}
    base.update(_index_cells_from_indices_dict(ov_idx))
    base.update(_index_cells_from_indices_dict(kj_idx))
    snap = _market_snapshot_canonical_values(hd.get("market_snapshot"))
    merged = {**base, **snap}
    keys = ("KOSPI", "KOSDAQ", "SPX", "NASDAQ", "NIKKEI", "DJI")
    return {k: merged.get(k) or _PLACEHOLDER_INDEX_CELL for k in keys}


def _proof_indices_snapshot_groups_html(ri: dict[str, object], data: dict[str, object] | None) -> str:
    """Domestic (KOSPI, KOSDAQ) then global (S&P 500, NASDAQ, Nikkei, DJI); two tables, never one mixed table."""
    cells = _resolve_major_index_cells(ri, dict(data or {}))
    domestic_rows = (
        ("코스피", cells["KOSPI"]),
        ("코스닥", cells["KOSDAQ"]),
    )
    global_rows = (
        ("S&P 500", cells["SPX"]),
        ("나스닥", cells["NASDAQ"]),
        ("니케이", cells["NIKKEI"]),
        ("다우존스", cells["DJI"]),
    )

    def _one_table(rows: tuple[tuple[str, str], ...]) -> str:
        tbody = "".join(
            f"<tr><td>{html.escape(a)}</td><td>{html.escape(b)}</td></tr>" for a, b in rows
        )
        return (
            '<div class="handoff-table-wrap">'
            '<table class="handoff-table" role="presentation">'
            f"<tbody>{tbody}</tbody></table></div>"
        )

    return "\n".join(
        [
            '<p class="muted indices-group-label">국내</p>',
            _one_table(domestic_rows),
            '<p class="muted indices-group-label indices-group-label-global">글로벌</p>',
            _one_table(global_rows),
        ]
    )


def _indices_section_has_any_source(ri: dict[str, object], hd: dict[str, object]) -> bool:
    ms = hd.get("market_snapshot")
    if isinstance(ms, list) and len(ms) > 0:
        return True
    ov = ri.get("overnight_us_market") if isinstance(ri.get("overnight_us_market"), dict) else {}
    idx = ov.get("indices") if isinstance(ov.get("indices"), dict) else {}
    if len(idx) > 0:
        return True
    kj = ri.get("korea_japan_indices") if isinstance(ri.get("korea_japan_indices"), dict) else {}
    kj_idx = kj.get("indices") if isinstance(kj.get("indices"), dict) else {}
    return len(kj_idx) > 0


def _proof_customer_major_indices_section(ri: dict[str, object], hd: dict[str, object]) -> str:
    """Customer handoff: interpretive copy (market_setup) + 국내/글로벌 스냅샷(고정 행, 두 표)."""
    narrative = str(hd.get("market_setup") or "").strip()
    if not narrative and not _indices_section_has_any_source(ri, hd):
        return ""
    snapshot_html = _proof_indices_snapshot_groups_html(ri, hd)
    parts: list[str] = [
        '<section class="handoff-section">',
        '<h2 class="section-heading">주요 지수 브리핑</h2>',
    ]
    if narrative:
        parts.append(f'<div class="box summary-box">{html.escape(narrative)}</div>')
    parts.append('<p class="muted section-lede">주요 지표 스냅샷</p>')
    parts.append(snapshot_html)
    parts.append("</section>")
    return "\n".join(parts)


def _operator_hold_footer(
    *,
    run_id: str,
    json_snapshot_rel: str,
    validation_result: object | None,
) -> str:
    """Operator-oriented footer for blocked/draft pipeline outputs (not customer-deliverable)."""
    vr = str(validation_result or "").strip().lower()
    vr_ko = _validation_gate_ko(vr) if vr else "해당 없음"
    parts: list[str] = [
        '<footer class="reader-admin" aria-label="운영 기록">',
        '<h2 class="section-heading">운영 기록</h2>',
        '<div class="admin-grid">',
        f'<div class="admin-row"><span class="admin-label">실행 시각</span><span class="admin-value">{html.escape(run_id)}</span></div>',
        f'<div class="admin-row"><span class="admin-label">검증 게이트</span><span class="admin-value">{html.escape(vr_ko)}</span></div>',
        f'<div class="admin-row"><span class="admin-label">미리보기 JSON</span><span class="admin-value"><code>{html.escape(json_snapshot_rel)}</code></span></div>',
        "</div>",
        "</footer>",
    ]
    return "\n".join(parts)


def _proof_bottom_image_slot_html(image_run: dict[str, Any]) -> str:
    """Operator debug: bottom slot status + img; top is status-only here (hero is under header in handoff)."""
    parts: list[str] = []
    parts.append(
        '<p class="muted">하단 슬롯의 <strong>이번 실행</strong> 결과입니다. '
        "상단 히어로는 <strong>브리핑 제목 바로 아래</strong>에만 붙습니다(생성된 실행만). "
        "이 섹션에서는 상단을 <strong>중복 미리보기하지 않습니다</strong>.</p>"
    )
    top_slot = image_run.get("top") if isinstance(image_run, dict) else None
    if not isinstance(top_slot, dict):
        top_slot = {
            "generated_this_run": False,
            "status": "unknown",
            "reason": "missing_image_run_metadata",
            "path": "output/(unknown)",
        }
    t_path = str(top_slot.get("path", ""))
    t_status = str(top_slot.get("status", "unknown"))
    t_reason = str(top_slot.get("reason", ""))
    t_gen = top_slot.get("generated_this_run") is True
    t_status_ko = _proof_image_status_ko(t_status)
    t_reason_ko = _proof_image_reason_ko(t_reason)
    parts.append(
        "<p><strong>상단(스튜디오)</strong> — 상태만(미리보기는 1절 제목 아래)<br/>"
        f"상태: {html.escape(t_status_ko)}"
        + (f"<br/>사유: {html.escape(t_reason_ko)}" if t_reason_ko else "")
        + f'<br/><span class="muted">참고 경로:</span> <code>{html.escape(t_path)}</code></p>'
    )
    if t_gen:
        parts.append('<p class="muted">상단 미리보기 &lt;img&gt;는 제목 직후에만 있습니다.</p>')
    else:
        parts.append(
            '<p class="muted">상단은 이번 실행에서 생성되지 않아 제목 아래 히어로 블록이 없습니다.</p>'
        )

    key, label = ("bottom", "하단(야외·일상)")
    slot = image_run.get(key) if isinstance(image_run, dict) else None
    if not isinstance(slot, dict):
        slot = {
            "generated_this_run": False,
            "status": "unknown",
            "reason": "missing_image_run_metadata",
            "path": "output/(unknown)",
        }
    path = str(slot.get("path", ""))
    status = str(slot.get("status", "unknown"))
    reason = str(slot.get("reason", ""))
    gen = slot.get("generated_this_run") is True
    status_ko = _proof_image_status_ko(status)
    reason_ko = _proof_image_reason_ko(reason)
    parts.append(
        f"<p><strong>{html.escape(label)}</strong><br/>"
        f"상태: {html.escape(status_ko)}"
        + (f"<br/>사유: {html.escape(reason_ko)}" if reason_ko else "")
        + f'<br/><span class="muted">참고 경로:</span> <code>{html.escape(path)}</code></p>'
    )
    if gen:
        img_src = Path(path).name
        parts.append(f'<p><img src="{html.escape(img_src)}" alt="{html.escape(label)} 미리보기" /></p>')
    else:
        parts.append(
            '<p class="muted">이번 실행에서 생성되지 않았습니다. '
            "이전 실행 파일이 디스크에 남아 있더라도 이번 결과로 표시하지 않습니다.</p>"
        )
    return "\n".join(parts)


def _format_watchpoints(wps: object) -> str:
    parts: list[str] = ["<ul>"]
    if isinstance(wps, list):
        for w in wps[:8]:
            if isinstance(w, dict):
                parts.append(
                    "<li><strong>"
                    + html.escape(str(w.get("headline", "")))
                    + "</strong> — "
                    + html.escape(str(w.get("detail", "")))
                    + "</li>"
                )
    parts.append("</ul>")
    return "".join(parts)


def _format_risks(rks: object) -> str:
    parts: list[str] = ["<ul>"]
    if isinstance(rks, list):
        for r in rks[:8]:
            if isinstance(r, dict):
                parts.append(
                    "<li><strong>"
                    + html.escape(str(r.get("risk", "")))
                    + "</strong> — "
                    + html.escape(str(r.get("detail", "")))
                    + "</li>"
                )
    parts.append("</ul>")
    return "".join(parts)


def _read_json_string_value(blob: str, key: str) -> str | None:
    """Read a JSON string value for key from possibly truncated/invalid JSON (best-effort)."""
    m = re.search(rf'"{re.escape(key)}"\s*:\s*"', blob)
    if not m:
        return None
    i = m.end()
    out: list[str] = []
    while i < len(blob):
        c = blob[i]
        if c == '"':
            return "".join(out)
        if c == "\\" and i + 1 < len(blob):
            nxt = blob[i + 1]
            if nxt == "n":
                out.append("\n")
            elif nxt == "t":
                out.append("\t")
            elif nxt == '"':
                out.append('"')
            elif nxt == "\\":
                out.append("\\")
            elif nxt == "/":
                out.append("/")
            else:
                out.append(nxt)
            i += 2
            continue
        out.append(c)
        i += 1
    return "".join(out)


def _scrape_json_string_fields(blob: str, keys: tuple[str, ...]) -> dict[str, str]:
    out: dict[str, str] = {}
    if not blob or not blob.strip():
        return out
    for key in keys:
        val = _read_json_string_value(blob, key)
        if val is not None and val.strip():
            out[key] = val.strip()
    return out


def _failure_merge_display_fields(display_data: dict[str, object], raw_text: str) -> None:
    scraped = _scrape_json_string_fields(
        raw_text,
        ("title", "summary", "greeting", "market_setup", "closing_message"),
    )
    for k, v in scraped.items():
        cur = display_data.get(k)
        if not isinstance(cur, str) or not cur.strip():
            display_data[k] = v


def _format_watchpoints_with_feed_fallback(wps: object, ri: dict[str, object]) -> str:
    base = _format_watchpoints(wps)
    nonempty = 0
    if isinstance(wps, list):
        for w in wps:
            if isinstance(w, dict) and (
                str(w.get("headline", "")).strip() or str(w.get("detail", "")).strip()
            ):
                nonempty += 1
    if nonempty > 0:
        return base
    news = ri.get("top_market_news")
    if not isinstance(news, list) or not news:
        return (
            base
            + '<p class="muted"><strong>초안 상태</strong> TOP3 배열이 비어 있거나 복구되지 않았고, '
            "입력 <code>top_market_news</code>도 없습니다.</p>"
        )
    lines: list[str] = [
        '<p class="muted"><strong>초안 상태</strong> 구조화된 TOP3를 표시할 수 없습니다. '
        "아래는 <strong>입력 피드</strong> 상위 뉴스 헤드라인 인용입니다(모델 확정 산출물이 아님).</p>",
        "<ul>",
    ]
    for item in news[:5]:
        if isinstance(item, dict):
            h = str(item.get("headline", "")).strip()
            if h:
                lines.append(f"<li>{html.escape(h)}</li>")
    lines.append("</ul>")
    return base + "".join(lines)


def _format_risks_with_feed_fallback(rks: object, ri: dict[str, object]) -> str:
    base = _format_risks(rks)
    nonempty = 0
    if isinstance(rks, list):
        for r in rks:
            if isinstance(r, dict) and (
                str(r.get("risk", "")).strip() or str(r.get("detail", "")).strip()
            ):
                nonempty += 1
    if nonempty > 0:
        return base
    rf = ri.get("risk_factors")
    if not isinstance(rf, list) or not rf:
        return (
            base
            + '<p class="muted"><strong>초안 상태</strong> risk_check가 비어 있고, 입력 <code>risk_factors</code>도 없습니다.</p>'
        )
    lines: list[str] = [
        '<p class="muted"><strong>초안 상태</strong> 리스크 블록을 표시할 수 없습니다. '
        "아래는 <strong>입력 피드</strong> <code>risk_factors</code> 인용입니다(모델 확정 산출물이 아님).</p>",
        "<ul>",
    ]
    for item in rf[:6]:
        if isinstance(item, dict):
            t = str(item.get("risk", "") or item.get("title", "")).strip()
            d = str(item.get("detail", "") or item.get("summary", "")).strip()
            if t or d:
                lines.append(
                    "<li><strong>"
                    + html.escape(t or "(제목 없음)")
                    + "</strong> — "
                    + html.escape(d)
                    + "</li>"
                )
        elif isinstance(item, str) and item.strip():
            lines.append(f"<li>{html.escape(item.strip())}</li>")
    lines.append("</ul>")
    return base + "".join(lines)


READER_REASON_PLACEHOLDER = (
    "독자용 증빙에서는 운영·디버그 성격의 세부 정보를 표시하지 않습니다. "
    "미리보기 JSON 또는 증빙 HTML과 같은 이름의 `.operator.txt` 파일을 확인하세요."
)


def _operator_diagnostic_file(proof_html: Path) -> Path:
    return proof_html.with_name(proof_html.stem + ".operator.txt")


def _proof_operator_body_debug_enabled() -> bool:
    return os.environ.get("TODAY_GENIE_PROOF_OPERATOR_DEBUG", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def _is_operator_raw_reason(line: str) -> bool:
    s = line.strip()
    if not s:
        return True
    low = s.lower()
    if s.startswith(
        (
            "content:",
            "http:",
            "image_top:",
            "image_bottom:",
            "validation_block:",
        )
    ):
        return True
    if s == "missing_image_prompts_after_validation":
        return True
    if "input_feed_status=" in s and "need full feeds" in s:
        return True
    if "runtimeerror" in low or "traceback" in low:
        return True
    if "project_id" in low and "required" in low:
        return True
    if "environment variable" in low or "env-var" in low:
        return True
    return False


def _sanitize_reader_reason_list(reasons: list[str]) -> list[str]:
    kept = [x for x in reasons if x.strip() and not _is_operator_raw_reason(x)]
    if kept:
        return kept
    if not reasons:
        return []
    return [READER_REASON_PLACEHOLDER]


def _write_operator_diagnostic_log(
    path: Path,
    *,
    run_id: str,
    proof_html: Path,
    json_snapshot_rel: str,
    ri: dict[str, object],
    extra_errors: list[str],
    tpo_reasons: list[str],
    roulette_reasons: list[str],
    validation_result: object | None,
    stage_timings_sec: dict[str, float] | None = None,
) -> None:
    lines_out = [
        f"run_id: {run_id}",
        f"proof_html: {_repo_rel(proof_html)}",
        f"preview_json: {json_snapshot_rel}",
        f"operator_diagnostic_txt: {_repo_rel(path)}",
        f"validation_result: {validation_result!r}",
        "",
        "-- run_stage_timings_sec (wall time per stage; see script main) --",
        json.dumps(stage_timings_sec or {}, ensure_ascii=False, indent=2),
        "",
        "-- errors (raw) --",
        "\n".join(extra_errors) if extra_errors else "(none)",
        "",
        "-- tpo_reasons (raw, as recorded for this proof) --",
        "\n".join(tpo_reasons) if tpo_reasons else "(none)",
        "",
        "-- roulette_reasons (raw, as recorded for this proof) --",
        "\n".join(roulette_reasons) if roulette_reasons else "(none)",
        "",
        "-- runtime_input (JSON) --",
        json.dumps(ri, ensure_ascii=False, indent=2),
        "",
    ]
    path.write_text("\n".join(lines_out), encoding="utf-8")


def _write_proof_bundle(
    proof_html: Path,
    html_body: str,
    *,
    run_id: str,
    ri: dict[str, object],
    extra_errors: list[str],
    tpo_reasons: list[str],
    roulette_reasons: list[str],
    validation_result: object | None,
    json_snapshot_rel: str,
    stage_timings_sec: dict[str, float] | None = None,
    wall_start: float | None = None,
) -> Path:
    timings: dict[str, float] = stage_timings_sec if isinstance(stage_timings_sec, dict) else {}
    proof_html.write_text(html_body, encoding="utf-8")
    if wall_start is not None:
        timings["total_wall_sec"] = round(time.perf_counter() - wall_start, 4)
    diag_path = _operator_diagnostic_file(proof_html)
    _write_operator_diagnostic_log(
        diag_path,
        run_id=run_id,
        proof_html=proof_html,
        json_snapshot_rel=json_snapshot_rel,
        ri=ri,
        extra_errors=extra_errors,
        tpo_reasons=tpo_reasons,
        roulette_reasons=roulette_reasons,
        validation_result=validation_result,
        stage_timings_sec=timings,
    )
    return diag_path


def _proof_hashtag_html(tags: object, *, omit_muted_label: bool = False) -> str:
    try:
        from renderers import TODAY_GENIE_HASHTAG_COUNT
    except ImportError:
        TODAY_GENIE_HASHTAG_COUNT = 7
    if not isinstance(tags, list) or len(tags) != TODAY_GENIE_HASHTAG_COUNT:
        return ""
    lines = "".join(
        f'<p style="margin:2px 0;font-size:14px;line-height:1.65;">{html.escape(str(x))}</p>'
        for x in tags
    )
    inner = f'<div class="box">{lines}</div>\n'
    if omit_muted_label:
        return inner
    return f'<p class="muted">해시태그 (7)</p>\n{inner}'


def _write_fail_proof(
    proof_html: Path,
    run_id: str,
    err: list[str],
    ri: dict[str, object],
    status: dict[str, str],
    top_img: Path,
    bot_img: Path,
    *,
    json_snapshot_rel: str,
    tpo_verdict: str,
    tpo_reasons: list[str],
    roulette_verdict: str,
    roulette_reasons: list[str],
    data: dict[str, object] | None = None,
    image_run: Optional[dict[str, Any]] = None,
    validation_result: object | None = None,
    stage_timings_sec: dict[str, float] | None = None,
    wall_start: float | None = None,
    raw_text: str | None = None,
) -> None:
    from renderers import finalize_today_genie_hashtag_list

    data = dict(data or {})
    data["hashtags"] = finalize_today_genie_hashtag_list(data, ri)
    display = dict(data)
    if raw_text:
        _failure_merge_display_fields(display, raw_text)
    title = (display.get("title") or "").strip()
    summary = (display.get("summary") or "").strip()
    if not title:
        title = "[구조화 본문 미확보] 참고 초안"
    if not summary:
        summary = (
            "이번 실행에서 게시 확정용 전체 JSON을 끝까지 확보하지 못했거나 검증 전 단계에서 중단되었습니다. "
            "아래 TOP3·리스크 칸의 피드 인용, 보완 사유, 미리보기 JSON을 함께 확인하세요."
        )
    mood = (display.get("image_briefing_mood_state") or "").strip()
    basis = (display.get("image_mood_basis") or "").strip()
    p_studio = (display.get("image_prompt_studio") or "").strip()
    p_out = (display.get("image_prompt_outdoor") or "").strip()
    if image_run is None:
        image_run = _image_run_skipped_both("unspecified_proof_path", top_img, bot_img)
    body = _proof_html_body(
        run_id=run_id,
        ri=ri,
        eyebrow_line=_briefing_eyebrow_line(ri, run_id),
        val=None,
        title=title,
        summary=summary,
        wp_html=_format_watchpoints_with_feed_fallback(display.get("key_watchpoints"), ri),
        rk_html=_format_risks_with_feed_fallback(display.get("risk_check"), ri),
        mood=mood,
        basis=basis,
        p_studio=p_studio or "없음",
        p_out=p_out or "없음",
        prefix_display="(n/a)",
        proof_html=proof_html,
        json_snapshot_rel=json_snapshot_rel,
        tpo_verdict=tpo_verdict,
        tpo_reasons=tpo_reasons or err,
        roulette_verdict=roulette_verdict,
        roulette_reasons=roulette_reasons or err,
        extra_errors=err,
        image_run=image_run,
        hashtag_block=_proof_hashtag_html(display.get("hashtags"), omit_muted_label=True),
        failure_mode=True,
        handoff_data=display,
        validation_result=validation_result,
    )
    _write_proof_bundle(
        proof_html,
        body,
        run_id=run_id,
        ri=ri,
        extra_errors=err,
        tpo_reasons=tpo_reasons or err,
        roulette_reasons=roulette_reasons or err,
        validation_result=validation_result,
        json_snapshot_rel=json_snapshot_rel,
        stage_timings_sec=stage_timings_sec,
        wall_start=wall_start,
    )


def _proof_html_body(
    *,
    run_id: str,
    ri: dict[str, object],
    eyebrow_line: str | None,
    val: object | None,
    title: str,
    summary: str,
    wp_html: str,
    rk_html: str,
    mood: str,
    basis: str,
    p_studio: str,
    p_out: str,
    prefix_display: str,
    proof_html: Path,
    json_snapshot_rel: str,
    tpo_verdict: str,
    tpo_reasons: list[str],
    roulette_verdict: str,
    roulette_reasons: list[str],
    extra_errors: list[str] | None = None,
    image_run: Optional[dict[str, Any]] = None,
    hashtag_block: str = "",
    failure_mode: bool = False,
    handoff_data: dict[str, object] | None = None,
    validation_result: object | None = None,
) -> str:
    extra_errors = extra_errors or []
    hd = dict(handoff_data or {})
    eyebrow_disp = html.escape((eyebrow_line or _briefing_eyebrow_line(ri, run_id)).strip())
    tpo_reader = _sanitize_reader_reason_list(tpo_reasons)
    rou_reader = _sanitize_reader_reason_list(roulette_reasons)
    tpo_ul = "".join(f"<li>{html.escape(x)}</li>" for x in tpo_reader)
    rou_ul = "".join(f"<li>{html.escape(x)}</li>" for x in rou_reader)
    tpo_ko = _pass_fail_ko(tpo_verdict)
    rou_ko = _pass_fail_ko(roulette_verdict)
    news_q = html.escape(
        "뉴스·장전 브리핑처럼 읽히는가? — 제목·요약·워치포인트에 피드의 구체 헤드라인·수치·일정이 녹아 있는지 확인."
    )
    if image_run is None:
        raise ValueError("image_run is required for proof HTML")
    top_hero_reader = _proof_top_hero_html(image_run)
    top_hero_debug = _proof_top_hero_html(image_run, include_status_caption=True)
    img_bottom_section = _proof_bottom_image_slot_html(image_run)
    bottom_reader = _proof_bottom_reader_html(image_run)
    image_dir_html = _proof_image_direction_html(mood, basis, p_studio, p_out)

    vr_admin = validation_result
    if vr_admin is None and val is not None:
        vr_admin = getattr(val, "result", None)

    operator_debug_html = ""
    if _proof_operator_body_debug_enabled():
        vr_dbg = getattr(val, "result", "n/a") if val else "n/a"
        vr_ko = _validation_gate_ko(vr_dbg)
        feed_ko = _feed_status_ko(ri.get("input_feed_status"))
        feed_dump = html.escape(json.dumps(ri, ensure_ascii=False, indent=2)[:12000])
        err_box = html.escape("; ".join(extra_errors) if extra_errors else "없음")
        operator_debug_html = f"""

<h1>운영·디버그: 이미지 방향·무드</h1>
{image_dir_html}

<h1>운영·디버그: 이번 실행 이미지 결과</h1>
{img_bottom_section}

<h1>운영·디버그: 상단 히어로</h1>
{top_hero_debug or '<p class="muted">상단 히어로 없음</p>'}

<h1>운영·디버그: 품질·일치 판정</h1>
<p class="muted">{news_q}</p>
<p><strong>텍스트가 실제 뉴스/브리핑인가?</strong> 위 제목·요약·워치포인트·리스크를 피드와 대조.</p>
<p><strong>이미지가 이 브리핑과 맞는가?</strong> 제목 직후 상단 미리보기(생성 시), 이미지 방향·무드 요약, 이번 실행 이미지 결과를 함께 본다.</p>
<p><strong>배경·무드·의상이 콘텐츠 반응형인가?</strong> 연출 요약과 상·하단 이미지를 대조한다.</p>
<p><strong>슬롯 룰렛처럼 보이는가?</strong> 아래 룰렛 판정을 참고.</p>
<p class="{'tpo-pass' if tpo_verdict == 'PASS' else 'tpo-fail'}"><strong>품질·일치 판정:</strong> {html.escape(tpo_ko)}</p>
<ul>{tpo_ul}</ul>

<h1>운영·디버그: 룰렛·반복 위험 판정</h1>
<p class="{'tpo-pass' if roulette_verdict == 'PASS' else 'tpo-fail'}"><strong>룰렛 판정:</strong> {html.escape(rou_ko)}</p>
<ul>{rou_ul}</ul>

<h1>운영·디버그: 실행 정보</h1>
<p class="meta"><strong>실행 시각:</strong> {html.escape(run_id)}<br/>
<strong>모드:</strong> 오늘의 지니<br/>
<strong>입력 피드:</strong> {html.escape(feed_ko)}<br/>
<strong>검증 결과:</strong> {html.escape(vr_ko)}<br/>
<strong>미리보기 기록:</strong> <code>{html.escape(json_snapshot_rel)}</code><br/>
<strong>증빙 HTML:</strong> <code>{html.escape(_repo_rel(proof_html))}</code><br/>
<strong>TODAY_GENIE_PROOF_OPERATOR_DEBUG:</strong> 활성화됨<br/>
<strong>오류 요약:</strong></p>
<div class="box">{err_box}</div>
<p class="muted">실행 입력(원문 앞부분만)</p>
<div class="box">{feed_dump}</div>"""
    operator_wrap = (
        f'<div class="operator-debug-append">{operator_debug_html}</div>'
        if operator_debug_html
        else ""
    )

    doc_title = html.escape(title if len(title) <= 72 else title[:69] + "…")
    if not doc_title.strip():
        doc_title = "오늘의 지니 · 장전 브리핑"

    indices_section = _proof_customer_major_indices_section(ri, hd)

    top_hero_section = ""
    if top_hero_reader:
        top_hero_section = (
            '<section class="handoff-section handoff-visual">\n'
            f"{top_hero_reader}\n"
            "</section>"
        )

    tag_section = ""
    hb = (hashtag_block or "").strip()
    if hb:
        tag_section = (
            '<section class="handoff-section handoff-hashtag-tail">\n'
            f"{hb}\n"
            "</section>"
        )

    if failure_mode:
        admin_footer = _operator_hold_footer(
            run_id=run_id,
            json_snapshot_rel=json_snapshot_rel,
            validation_result=vr_admin,
        )
    else:
        admin_footer = _customer_reader_admin_panel(run_id)

    disc_footer = _customer_investment_disclaimer_html()

    if failure_mode:
        reason_items = _sanitize_reader_reason_list(tpo_reasons)[:12]
        reason_html = "".join(f'<li class="reason-li">{html.escape(x)}</li>' for x in reason_items)
        draft_notice = (
            '<div class="draft-banner" role="status">'
            "<strong>참고용 초안입니다.</strong> "
            "이번 실행은 게시 확정 조건을 충족하지 않았습니다. 아래 초안과 사유를 바탕으로 편집해 주세요."
            "</div>\n"
        )
        reasons_block = (
            '<section class="handoff-section">\n'
            '<h2 class="section-heading">보완이 필요한 점</h2>\n'
            '<p class="muted section-lede">자동 점검에서 확인된 항목입니다.</p>\n'
            '<div class="box"><ul class="handoff-list">'
            f"{reason_html or '<li>구체적 사유는 로컬 기록을 확인해 주세요.</li>'}"
            "</ul></div>\n"
            "</section>"
        )
        page_title = "오늘의 지니 · 참고 초안"
        return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>{page_title}</title>
<style>{_HANDOFF_CSS}</style>
</head>
<body class="handoff-page">
{draft_notice}
<header class="handoff-header">
<p class="eyebrow">{eyebrow_disp}</p>
<h1 class="handoff-title">{html.escape(title)}</h1>
</header>
{top_hero_section}
<section class="handoff-section">
<h2 class="section-heading">오프닝 요약</h2>
<div class="box summary-box">{html.escape(summary)}</div>
</section>
{indices_section}
<section class="handoff-section">
<h2 class="section-heading">TOP 3 뉴스 브리핑</h2>
<div class="box summary-box">{wp_html}</div>
</section>
<section class="handoff-section">
<h2 class="section-heading">리스크와 체크포인트</h2>
<div class="box summary-box">{rk_html}</div>
</section>
{reasons_block}
{bottom_reader}
{tag_section}
{disc_footer}
{admin_footer}
{operator_wrap}
</body>
</html>"""

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>{doc_title}</title>
<style>{_HANDOFF_CSS}</style>
</head>
<body class="handoff-page">
<header class="handoff-header">
<p class="eyebrow">{eyebrow_disp}</p>
<h1 class="handoff-title">{html.escape(title)}</h1>
</header>
{top_hero_section}
<section class="handoff-section">
<h2 class="section-heading">오프닝 요약</h2>
<div class="box summary-box">{html.escape(summary)}</div>
</section>
{indices_section}
<section class="handoff-section">
<h2 class="section-heading">TOP 3 뉴스 브리핑</h2>
<div class="box summary-box">{wp_html}</div>
</section>
<section class="handoff-section">
<h2 class="section-heading">리스크와 체크포인트</h2>
<div class="box summary-box">{rk_html}</div>
</section>
{bottom_reader}
{tag_section}
{disc_footer}
{admin_footer}
{operator_wrap}
</body>
</html>"""


if __name__ == "__main__":
    sys.exit(main())
