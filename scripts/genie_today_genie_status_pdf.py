#!/usr/bin/env python3
"""Generate operator-facing today_genie status PDF (Korean, ReportLab)."""
from __future__ import annotations

import json
import sys
from datetime import datetime
from html import escape
from pathlib import Path
from zoneinfo import ZoneInfo

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

FONT_PATH = "/System/Library/Fonts/Supplemental/AppleGothic.ttf"


def _p(text: str, style: ParagraphStyle) -> Paragraph:
    return Paragraph(escape(text).replace("\n", "<br/>"), style)


def main() -> int:
    live_path = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/report_live.json")
    out_dir = Path(sys.argv[2] if len(sys.argv) > 2 else ".").resolve()

    kst = datetime.now(ZoneInfo("Asia/Seoul"))
    fname = f"genie_{kst.hour:02d}_{kst.minute:02d}_{kst.second:02d}.pdf"
    out_path = out_dir / fname

    if not Path(FONT_PATH).is_file():
        print("Korean font not found:", FONT_PATH, file=sys.stderr)
        return 2

    pdfmetrics.registerFont(TTFont("AppleGothic", FONT_PATH))
    base = getSampleStyleSheet()
    h0 = ParagraphStyle(
        "h0",
        parent=base["Heading1"],
        fontName="AppleGothic",
        fontSize=16,
        leading=22,
        textColor=colors.HexColor("#111111"),
    )
    h1 = ParagraphStyle(
        "h1",
        parent=base["Heading2"],
        fontName="AppleGothic",
        fontSize=12,
        leading=16,
        textColor=colors.HexColor("#222222"),
        spaceBefore=10,
        spaceAfter=6,
    )
    body = ParagraphStyle(
        "body",
        parent=base["Normal"],
        fontName="AppleGothic",
        fontSize=9,
        leading=13,
        textColor=colors.HexColor("#333333"),
    )
    small = ParagraphStyle(
        "small",
        parent=body,
        fontSize=8,
        leading=11,
        textColor=colors.HexColor("#555555"),
    )

    raw = json.loads(live_path.read_text(encoding="utf-8"))
    if "detail" in raw:
        print("Live response was error payload; use a 200 OK JSON.", file=sys.stderr)
        return 3

    d = raw
    data = d.get("data") or {}
    ch = data.get("channel_drafts") or {}
    subject = ch.get("email_subject", "")
    title = data.get("title", "")
    summary = data.get("summary", "")
    market_setup = data.get("market_setup", "")
    issues = d.get("issues") or []
    wp = data.get("key_watchpoints") or []
    rc = data.get("rendered_channels") or {}
    em = rc.get("email_body_html", "") or ""

    story: list = []
    story.append(_p("GENIE today_genie 현재 상태 보고서", h0))
    story.append(_p(f"작성 시각 (KST): {kst.strftime('%Y-%m-%d %H:%M:%S')}", small))
    story.append(Spacer(1, 0.3 * cm))

    story.append(_p("1. Report title", h1))
    story.append(_p("GENIE today_genie 현재 상태 보고서 (상단 제목과 동일)", body))

    story.append(_p("2. Executive conclusion", h1))
    story.append(
        _p(
            "스테이징/E2E 입력 오염은 제거되었고 실제 피드(JSON) 연결·운영 박스 구조는 동작한다. "
            "다만 최신 라이브 호출은 검증이 draft_only로 남아 있으며(템플릿형 제목·결정 마감 문구 부족·체크포인트 TOP3 미달), "
            "고객 인도용 '거의 최종' 상태는 아직 아니다. "
            "단일 다음 과제는 검증 경고 3종을 한 번에 해소하도록 모델 산출물을 조정하는 것이다.",
            body,
        )
    )

    story.append(_p("3. Current objective", h1))
    story.append(
        _p(
            "거의 최종 수준의 이메일 본문 인도 + 최소한의 운영 메타(하단 박스) 완료. "
            "무한 미세 조정이 아니라 송고 가능한 상품 형태에 근접하는 것이 목표.",
            body,
        )
    )

    story.append(_p("4. Current production truth", h1))
    story.append(
        _p(
            "배포 리비전(조회 시점): genie-blog-run-00066-rpt (gcloud describe). "
            "라이브 API: POST / today_genie 1회(본 PDF 근거 JSON). "
            f"validation_result={d.get('validation_result')!s}, workflow_status={d.get('workflow_status')!s}. "
            f"issues 개수={len(issues)}. "
            "실제 SMTP 수신: 본 자동 리포트 생성 환경에서 미확인(이메일 본문 HTML은 API 단계 산출물).",
            body,
        )
    )

    story.append(_p("5. Received email quality review (PASS/HOLD)", h1))
    story.append(
        _p(
            "제목/타이틀: HOLD (template_title 경고). "
            "요약: PASS. "
            "장 셋업: PASS. "
            "체크포인트 밀도: HOLD (2건, TOP3 미달). "
            "결정 유용성: HOLD (missing_decision_line). "
            "이미지 연결: PASS(URL 2건 상·하단). 이미지 품질: HOLD(고정 템플릿 자산; 캡처 없어 시각 최종 판단 제한). "
            "하단 운영 박스: PASS(모드·검증·시각·요약·발송 안내·재발행 안내 구조). "
            "모바일 첫 화면: HOLD(스크린샷 없음, 미측정).",
            body,
        )
    )

    story.append(_p("6. Exact evidence", h1))
    story.append(_p("subject (channel_drafts.email_subject)", h1))
    story.append(_p(subject, body))
    story.append(_p("summary", h1))
    story.append(_p(summary, body))
    story.append(_p("market_setup", h1))
    story.append(_p(market_setup, body))
    story.append(_p("validator issues (JSON)", h1))
    story.append(_p(json.dumps(issues, ensure_ascii=False, indent=2), small))

    story.append(_p("7. Image / asset status", h1))
    story.append(
        _p(
            "연결 자산: static/email/GENIE_EMAIL_today_genie_top_v1.jpg, "
            "GENIE_EMAIL_today_genie_bottom_v1.jpg (이메일 HTML src 기준). "
            "고객 인도 관점: 브리핑 레터형 상·하단 프레이밍에는 적합하나, "
            "캡처가 없어 픽셀 품질·모바일 크롭은 본 PDF에서 확정 불가. "
            "제품 인상: 본문과 충돌하지 않는 범위에서 중립적 보조.",
            body,
        )
    )

    story.append(_p("8. Bottom admin box status", h1))
    story.append(
        _p(
            "표시: [운영 · Genie] 라벨, 모드, 검증·워크플로, 생성 시각 KST, 결과 요약(검증·입력피드), "
            "이메일 발송 안내(API vs 오케스트레이터), 재발행 요청 회색 박스. "
            "승인된 최소 운영 메타 구조와 정합. "
            "톤: 과도하게 크지 않음(13px 내외). 수용 가능.",
            body,
        )
    )

    story.append(_p("9. Root cause (단일)", h1))
    story.append(
        _p(
            "현재 지배적 차단 요인: 검증 경고 묶음(템플릿형 제목 + 결정 마감 문구 부족 + 체크포인트 TOP3 미달)로 "
            "validation_result가 pass에 도달하지 못함.",
            body,
        )
    )

    story.append(_p("10. Single next task", h1))
    story.append(
        _p(
            "다음 단일 실행: prompts.py의 today_genie 지시만 최소 수정하여 "
            "key_watchpoints 3건·closing_message 결정 기준 문장·title 비템플릿을 동시에 충족시킨 뒤 "
            "프로덕션 API를 1회 재호출해 validation_result=pass 여부를 확인한다.",
            body,
        )
    )

    story.append(_p("11. Appendix", h1))
    story.append(_p("스크린샷: 없음(자동 PDF 생성, 브라우저 캡처 미수행).", body))
    story.append(_p(f"title 필드: {title}", small))
    story.append(_p(f"key_watchpoints 건수: {len(wp)}", small))
    for i, w in enumerate(wp, 1):
        if isinstance(w, dict):
            story.append(_p(f"  {i}. {w.get('headline','')}", small))
    story.append(_p(f"email_body_html 길이: {len(em)} 문자", small))

    doc = SimpleDocTemplate(
        str(out_path),
        pagesize=A4,
        rightMargin=2 * cm,
        leftMargin=2 * cm,
        topMargin=1.5 * cm,
        bottomMargin=1.5 * cm,
    )
    doc.build(story)
    print(out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
