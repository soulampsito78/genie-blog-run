"""Tests for the future Kee-Suri contract preview renderer (TDD — pre-implementation).

Defines expected behavior for `keysuri_contract_preview_renderer.py` before implementation.
Implementation-dependent tests skip with:
  keysuri_contract_preview_renderer not implemented yet

Reference:
- docs/REVIEW_OPERATION_BOX_POLICY.md
- docs/keysuri/KEYSURI_CONTRACT_PREVIEW_RENDERER_DESIGN.md
- docs/keysuri/KEYSURI_TITLE_AND_BODY_SECTION_CONTRACT.md
- keysuri_html_preview_validation.py
"""
from __future__ import annotations

import re
import unittest
from datetime import datetime
from functools import wraps
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Callable, Optional, TypeVar

from keysuri_html_preview_validation import validate_keysuri_html_preview

_REPO = Path(__file__).resolve().parent.parent

_SKIP_REASON = "keysuri_contract_preview_renderer not implemented yet"

_REVIEW_CONFIRMATION_TEXT = {
    "preview_pending": "본 브리핑은 운영책임자의 직접 검수 대기 상태입니다.",
    "review_passed": "본 브리핑은 운영책임자의 직접 검수를 통과했습니다.",
    "sent_archived": "본 브리핑은 운영책임자의 직접 검수를 통과하여 발송되었습니다.",
}

_FORBIDDEN_BLEED_MARKERS = (
    "Today_Geenee",
    "Tomorrow_Geenee",
    "테크 앵커",
    "뉴스 앵커",
    "해시태그",
    "#키수리",
    "production_ready: true",
    "scheduler_ready: true",
    "email_ready: true",
    "static/email/",
)

_WARM_CLOSE_WEEKDAY = "오늘도 수고하셨습니다. 내일 다시 뵙겠습니다."
_WARM_CLOSE_FRIDAY = (
    "이번 주도 수고하셨습니다. 주말 잘 보내시고 월요일에 다시 뵙겠습니다."
)

_FORBIDDEN_ADMIN_CONTROLS_IN_REVIEW_CONFIRMATION = (
    "재발행",
    "다시 생성",
    "수정요청",
    "보류",
    "scheduler",
    "preview_path",
    "manifest_path",
    "validation_status",
)

_FORBIDDEN_INTERNAL_METADATA_IN_REVIEW_CONFIRMATION = (
    "program_id",
    "mode",
    "slot",
    "preview_path",
    "manifest_path",
    "scheduler",
    "debug",
)

_REVIEW_CONFIRMATION_BLOCK_RE = re.compile(
    r'<section[^>]*\bid=["\']review-confirmation-box["\'][^>]*>.*?</section>',
    re.IGNORECASE | re.DOTALL,
)

F = TypeVar("F", bound=Callable[..., Any])


def _try_import_contract_preview_renderer() -> Optional[Any]:
    try:
        import keysuri_contract_preview_renderer as mod  # type: ignore[import-not-found]

        return mod
    except ImportError:
        return None


_CONTRACT_RENDERER = _try_import_contract_preview_renderer()


def _require_contract_renderer(test_func: F) -> F:
    @wraps(test_func)
    def wrapper(self: unittest.TestCase, *args: Any, **kwargs: Any) -> Any:
        if _CONTRACT_RENDERER is None:
            raise unittest.SkipTest(_SKIP_REASON)
        return test_func(self, *args, **kwargs)

    return wrapper  # type: ignore[return-value]


_GLOBAL_ITEM_TITLES: tuple[str, ...] = (
    "구글, 제미나이 엔터프라이즈 보안·거버넌스 기능 확대 발표",
    "오픈AI, 개발자용 에이전트 빌더 베타 공개",
    "마이크로소프트, 코파일럿 워크플로 확장과 API 정책 조정",
    "메타, 오픈 모델 라인업 갱신과 추론 비용 공개",
    "애플, 온디바이스 AI 프라이버시 프레임워크 업데이트",
)

_KOREA_ITEM_TITLES: tuple[str, ...] = (
    "국내 클라우드, GPU 공급 확대와 조달 일정 공개",
    "반도체 장비사, 국내 파운드리 투자 계획 발표",
    "정부, AI 데이터센터 전력·인허가 가이드라인 개정",
    "국내 스타트업, 엔터프라이즈 에이전트 플랫폼 시리즈 A 유치",
    "통신사, 온프레미스 AI 추론 패키지 상용화 일정 공개",
)

_GLOBAL_SOURCE_URLS: tuple[str, ...] = (
    "https://blog.google/technology/ai/gemini-enterprise-update/",
    "https://openai.com/index/agent-builder-beta/",
    "https://blogs.microsoft.com/blog/2026/06/copilot-workflow-update/",
    "https://ai.meta.com/blog/open-models-inference-cost/",
    "https://www.apple.com/newsroom/2026/06/on-device-ai-privacy/",
)

_KOREA_SOURCE_URLS: tuple[str, ...] = (
    "https://www.kakaoenterprise.com/news/gpu-supply-2026/",
    "https://www.skhynix.com/kr/news/foundry-investment/",
    "https://www.msit.go.kr/notice/ai-datacenter-guideline/",
    "https://www.platum.kr/articles/enterprise-agent-series-a",
    "https://www.lguplus.com/enterprise/onprem-ai-inference/",
)


def _contract_top_item(rank: int, *, scope: str) -> dict[str, Any]:
    titles = _KOREA_ITEM_TITLES if scope == "korea" else _GLOBAL_ITEM_TITLES
    urls = _KOREA_SOURCE_URLS if scope == "korea" else _GLOBAL_SOURCE_URLS
    title = titles[rank - 1]
    source_url = urls[rank - 1]
    return {
        "rank": rank,
        "korean_title": title,
        "headline": title,
        "what_happened": (
            f"항목 {rank}에서 RSS·원문 요약에 따르면 주요 변화가 보고되었습니다. "
            f"세부 일정·수치는 원문 확인이 필요할 수 있습니다. "
            f"키수리는 확인 가능한 범위 안에서만 정리했습니다."
        ),
        "why_now": (
            f"항목 {rank}는 엔터프라이즈 배포·API 정책 변경이 겹치는 시점이라 "
            f"주인님의 파트너·비용 구조에 단기 영향이 나올 수 있습니다."
        ),
        "why_it_matters": (
            f"항목 {rank}는 엔터프라이즈 배포·API 정책 변경이 겹치는 시점이라 "
            f"주인님의 파트너·비용 구조에 단기 영향이 나올 수 있습니다."
        ),
        "owner_angle": (
            f"주인님께서는 항목 {rank}를 제품 로드맵·파트너 선정 기준에 반영할지 점검하시면 됩니다. "
            f"단기 과장과 장기 구조 변화를 구분해 보시는 것이 좋습니다."
        ),
        "business_implication": (
            f"주인님께서는 항목 {rank}를 제품 로드맵·파트너 선정 기준에 반영할지 점검하시면 됩니다. "
            f"단기 과장과 장기 구조 변화를 구분해 보시는 것이 좋습니다."
        ),
        "keysuri_judgment_label": "관찰",
        "keysuri_judgment": f"항목 {rank} — 후속 공식 발표 확인 후 활용 여부를 결정하세요.",
        "next_watch": f"항목 {rank} 관련 공식 발표·가격·일정 공개 여부를 확인하세요.",
        "source_name": "Google The Keyword" if scope == "global" else "국내 공식 보도",
        "source_url": source_url,
        "checked_at": "2026-06-05T12:00:00+09:00",
        "verification_status": "rss_summary / not_verified",
    }


def _contract_deep_dive_layers(*, scope: str) -> list[dict[str, str]]:
    if scope == "korea":
        return [
            {
                "layer_number": "1",
                "layer_title": "물리·인프라 병목",
                "layer_body": (
                    "국내 데이터센터·전력·GPU 조달 병목이 의사결정 주기를 늘리고 있습니다. "
                    "주인님께서는 인프라 예산·파트너 조건을 재점검하시면 됩니다."
                ),
            },
            {
                "layer_number": "2",
                "layer_title": "규제·주권·조달 압력",
                "layer_body": (
                    "데이터 주권·인허가·조달 규정 변화가 클라우드·AI 도입 일정에 직접 영향을 줍니다. "
                    "규제 공문·가이드라인 후속 조치를 확인하세요."
                ),
            },
            {
                "layer_number": "3",
                "layer_title": "워크플로·락인",
                "layer_body": (
                    "엔터프라이즈 에이전트·온프레미스 추론 패키지가 워크플로 락인을 강화하고 있습니다. "
                    "전환 비용과 API 의존도를 함께 보시는 것이 좋습니다."
                ),
            },
        ]
    return [
        {
            "layer_number": "1",
            "layer_title": "인프라·배포 압력",
            "layer_body": (
                "글로벌 하이퍼스케일 업체들이 추론·배포 레이어 투자를 확대하고 있습니다. "
                "주인님께서는 공급망·지역 가용성 리스크를 점검하시면 됩니다."
            ),
        },
        {
            "layer_number": "2",
            "layer_title": "플랫폼 통제권 이동",
            "layer_body": (
                "모델 성능 경쟁에서 워크플로·검색·개발 루틴 장악 경쟁으로 초점이 이동하고 있습니다. "
                "플랫폼 정책 변화가 파트너 조건에 바로 반영될 수 있습니다."
            ),
        },
        {
            "layer_number": "3",
            "layer_title": "워크플로 락인",
            "layer_body": (
                "에이전트·코파일럿류 제품이 업무 루틴에 깊게 들어오면서 전환 비용이 커지고 있습니다. "
                "단기 생산성 이득과 장기 락인을 구분해 보시는 것이 좋습니다."
            ),
        },
    ]


def build_korea_contract_fixture(*, review_state: str = "preview_pending") -> dict[str, Any]:
    """Local fixture for future Korea 18:30 contract preview renderer."""
    return {
        "program_id": "keysuri_korea_tech",
        "slot": "18:30",
        "review_state": review_state,
        "title_candidates": [
            "[키수리 브리핑] 국내 인프라·조달 압력 신호",
            "[키수리] 국내 규제·데이터 주권 변화",
        ],
        "selected_title": "[키수리 브리핑] 국내 인프라·조달 압력 신호",
        "opening_lead": (
            "주인님, 오늘 국내 테크 신호는 인프라 병목과 조달 일정 변동이 중심입니다. "
            "규제·전력·GPU 공급이 동시에 의사결정에 걸려 있습니다. "
            "키수리는 주인님께 바로 쓸 수 있는 관점으로 정리했습니다."
        ),
        "top_5_heading": "국내 테크 TOP 5",
        "top_5_items": [_contract_top_item(i, scope="korea") for i in range(1, 6)],
        "deep_dive_heading": "키수리의 딥-다이브",
        "deep_dive_layers": _contract_deep_dive_layers(scope="korea"),
        "one_line_checkpoint": "주인님, 오늘은 인프라·조달 일정 변동을 먼저 보시면 됩니다.",
        "warm_close_text": "오늘도 수고하셨습니다. 내일 다시 뵙겠습니다.",
        "closing_message": "주인님, 오늘 신호는 여기까지 정리해 두었습니다. 출처는 아래에 그대로 남깁니다.",
        "source_list": [
            {
                "source_id": "korea-msit-notice",
                "source_name": "과학기술정보통신부",
                "source_url": "https://www.msit.go.kr/notice/ai-datacenter-guideline/",
                "verification_status": "rss_summary / not_verified",
            }
        ],
        "operation_metadata": {
            "program_id": "keysuri_korea_tech",
            "mode": "contract_preview",
            "status": "review_required",
            "slot": "18:30",
        },
    }


def build_global_contract_fixture(*, review_state: str = "preview_pending") -> dict[str, Any]:
    """Local fixture for future global 12:30 contract preview renderer."""
    return {
        "program_id": "keysuri_global_tech",
        "slot": "12:30",
        "review_state": review_state,
        "title_candidates": [
            "[키수리 브리핑] 글로벌 AI·플랫폼 통제권 이동 신호",
            "[키수리] 오늘의 테크 신호 — 배포 레이어 압력",
        ],
        "selected_title": "[키수리 브리핑] 글로벌 AI·플랫폼 통제권 이동 신호",
        "opening_lead": (
            "주인님, 오늘 글로벌 테크 신호는 개별 헤드라인보다 AI·플랫폼·업무 루틴 쪽 구조적 움직임으로 읽힙니다. "
            "배포 레이어와 공급망 압력이 동시에 커지고 있습니다. "
            "키수리는 주인님께 의사결정에 바로 쓸 수 있는 관점으로 정리했습니다."
        ),
        "top_5_heading": "글로벌 테크 TOP 5",
        "top_5_items": [_contract_top_item(i, scope="global") for i in range(1, 6)],
        "deep_dive_heading": "키수리의 딥-다이브",
        "deep_dive_body": (
            "주인님, 오늘 선정된 다섯 신호는 AI 기능 발표보다 배포·검색·개발 루틴 장악 속도에 초점이 맞춰져 있습니다. "
            "확인된 사실은 공식 블로그·보도자료·RSS 요약 범위 안에 머무릅니다. "
            "키수리 해석상 플랫폼 통제권은 모델 성능 경쟁에서 워크플로 락인 경쟁으로 이동 중입니다. "
            "한국 운영자·창업자에게는 API 가격·지역 가용성·데이터 주권이 곧바로 비용 구조에 반영될 수 있습니다. "
            "아직 불확실한 점은 각사의 상용 일정과 엔터프라이즈 계약 조건입니다. "
            "원문 상세 확인이 필요한 항목은 카드에 표시했습니다."
        ),
        "deep_dive_layers": _contract_deep_dive_layers(scope="global"),
        "one_line_checkpoint": "주인님, 오늘 먼저 확인하실 포인트: 워크플로 락인 속도와 API 가격 변동입니다.",
        "closing_message": "주인님, 오늘 신호는 여기까지 정리해 두었습니다. 출처는 아래에 그대로 남깁니다.",
        "source_list": [
            {
                "source_id": "global-blog-google",
                "source_name": "Google The Keyword",
                "source_url": "https://blog.google/technology/ai/",
                "verification_status": "rss_summary / not_verified",
            }
        ],
        "operation_metadata": {
            "program_id": "keysuri_global_tech",
            "mode": "contract_preview",
            "status": "review_required",
            "slot": "12:30",
        },
    }


def _write_html_test_preview(tmp: Path, program_token: str, html: str) -> Path:
    target_dir = tmp / "output" / "keysuri_preview" / "html_test"
    target_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = target_dir / f"keysuri_{program_token}_contract_preview_{stamp}.html"
    path.write_text(html, encoding="utf-8")
    return path


def _render_contract_html(mod: Any, fixture: dict[str, Any]) -> str:
    if hasattr(mod, "render_keysuri_contract_preview_html"):
        return mod.render_keysuri_contract_preview_html(fixture)
    raise AttributeError("render_keysuri_contract_preview_html not found on contract preview renderer")


def _write_contract_html(mod: Any, fixture: dict[str, Any], tmp: Path, program_token: str) -> Path:
    if hasattr(mod, "write_keysuri_contract_preview_html"):
        target_dir = tmp / "output" / "keysuri_preview" / "html_test"
        target_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"keysuri_{program_token}_contract_preview_{stamp}.html"
        return Path(
            mod.write_keysuri_contract_preview_html(
                fixture,
                output_dir=str(target_dir),
                filename=filename,
            )
        )
    html = _render_contract_html(mod, fixture)
    return _write_html_test_preview(tmp, program_token, html)


def _anchor_pos(html: str, *needles: str) -> list[int]:
    positions: list[int] = []
    for needle in needles:
        pos = html.find(needle)
        if pos < 0:
            raise AssertionError(f"Missing anchor: {needle!r}")
        positions.append(pos)
    return positions


def _extract_review_confirmation_block(html: str) -> str:
    match = _REVIEW_CONFIRMATION_BLOCK_RE.search(html)
    if not match:
        raise AssertionError('Missing <section id="review-confirmation-box"> block')
    return match.group(0)


def _extract_block_by_id(html: str, element_id: str) -> str:
    pattern = re.compile(
        rf'<(?:section|div)[^>]*\bid=["\']{re.escape(element_id)}["\'][^>]*>.*?</(?:section|div)>',
        re.IGNORECASE | re.DOTALL,
    )
    match = pattern.search(html)
    if not match:
        raise AssertionError(f'Missing block with id="{element_id}"')
    return match.group(0)


class KeysuriContractPreviewFixtureTests(unittest.TestCase):
    """Fixture builders — run before renderer exists."""

    def test_korea_fixture_has_required_fields(self) -> None:
        fixture = build_korea_contract_fixture()
        self.assertEqual(fixture["program_id"], "keysuri_korea_tech")
        self.assertEqual(len(fixture["title_candidates"]), 2)
        self.assertIn(fixture["selected_title"], fixture["title_candidates"])
        self.assertEqual(len(fixture["top_5_items"]), 5)
        self.assertEqual(len(fixture["deep_dive_layers"]), 3)
        self.assertIn("operation_metadata", fixture)
        self.assertEqual(fixture["review_state"], "preview_pending")

    def test_global_fixture_has_required_fields(self) -> None:
        fixture = build_global_contract_fixture()
        self.assertEqual(fixture["program_id"], "keysuri_global_tech")
        self.assertEqual(fixture["top_5_heading"], "글로벌 테크 TOP 5")
        self.assertEqual(len(fixture["top_5_items"]), 5)
        self.assertEqual(len(fixture["deep_dive_layers"]), 3)
        self.assertNotIn("warm_close_text", fixture)

    def test_top_items_include_item_level_sources(self) -> None:
        for item in build_korea_contract_fixture()["top_5_items"]:
            self.assertIn("source_name", item)
            self.assertIn("source_url", item)
            self.assertIn("verification_status", item)
            self.assertTrue(item["source_url"].startswith("https://"))
            self.assertIn("not_verified", item["verification_status"])


class KeysuriContractPreviewImportTests(unittest.TestCase):
    def test_contract_preview_renderer_import_status(self) -> None:
        if _CONTRACT_RENDERER is None:
            self.skipTest(_SKIP_REASON)
        self.assertTrue(hasattr(_CONTRACT_RENDERER, "render_keysuri_contract_preview_html"))


class KeysuriContractPreviewReviewConfirmationTests(unittest.TestCase):
    def test_review_confirmation_text_constants(self) -> None:
        self.assertEqual(
            _REVIEW_CONFIRMATION_TEXT["preview_pending"],
            "본 브리핑은 운영책임자의 직접 검수 대기 상태입니다.",
        )
        self.assertEqual(
            _REVIEW_CONFIRMATION_TEXT["review_passed"],
            "본 브리핑은 운영책임자의 직접 검수를 통과했습니다.",
        )
        self.assertEqual(
            _REVIEW_CONFIRMATION_TEXT["sent_archived"],
            "본 브리핑은 운영책임자의 직접 검수를 통과하여 발송되었습니다.",
        )

    def test_preview_pending_is_default_fixture_state(self) -> None:
        self.assertEqual(build_korea_contract_fixture()["review_state"], "preview_pending")
        self.assertEqual(build_global_contract_fixture()["review_state"], "preview_pending")

    def test_review_passed_text_must_not_claim_send_complete(self) -> None:
        text = _REVIEW_CONFIRMATION_TEXT["review_passed"]
        self.assertNotIn("발송되었습니다", text)

    def test_sent_archived_only_when_state_is_sent_archived(self) -> None:
        self.assertNotEqual(
            build_korea_contract_fixture(review_state="preview_pending")["review_state"],
            "sent_archived",
        )
        self.assertNotEqual(
            build_korea_contract_fixture(review_state="review_passed")["review_state"],
            "sent_archived",
        )
        self.assertEqual(
            build_korea_contract_fixture(review_state="sent_archived")["review_state"],
            "sent_archived",
        )

    @_require_contract_renderer
    def test_review_confirmation_box_states_in_rendered_html(self) -> None:
        mod = _CONTRACT_RENDERER
        assert mod is not None
        for state, expected_text in _REVIEW_CONFIRMATION_TEXT.items():
            html = _render_contract_html(mod, build_korea_contract_fixture(review_state=state))
            self.assertIn(expected_text, html)
            self.assertIn("review-confirmation", html.lower().replace("_", "-"))
            if state != "sent_archived":
                self.assertNotIn(_REVIEW_CONFIRMATION_TEXT["sent_archived"], html)
            if state == "review_passed":
                self.assertNotIn("발송되었습니다", html.replace(expected_text, ""))


class KeysuriContractPreviewReviewBoxSeparationTests(unittest.TestCase):
    """Review/operation box separation — locks shared policy on html_test surface."""

    @_require_contract_renderer
    def test_review_confirmation_box_dom_hooks(self) -> None:
        mod = _CONTRACT_RENDERER
        assert mod is not None
        html = _render_contract_html(mod, build_korea_contract_fixture())
        self.assertIn('id="review-confirmation-box"', html)
        self.assertRegex(html, r'data-review-state=["\']preview_pending["\']')

    @_require_contract_renderer
    def test_review_confirmation_exact_korean_copy_per_state(self) -> None:
        mod = _CONTRACT_RENDERER
        assert mod is not None
        for state, expected_text in _REVIEW_CONFIRMATION_TEXT.items():
            with self.subTest(state=state):
                html = _render_contract_html(
                    mod, build_korea_contract_fixture(review_state=state)
                )
                block = _extract_review_confirmation_block(html)
                self.assertIn(expected_text, block)
                self.assertRegex(
                    html,
                    rf'data-review-state=["\']{re.escape(state)}["\']',
                )

    @_require_contract_renderer
    def test_review_confirmation_separate_from_validation_box(self) -> None:
        mod = _CONTRACT_RENDERER
        assert mod is not None
        html = _render_contract_html(mod, build_korea_contract_fixture())
        self.assertIn('id="review-confirmation-box"', html)
        self.assertIn('id="validation-result-box"', html)

        review_block = _extract_review_confirmation_block(html)
        validation_block = _extract_block_by_id(html, "validation-result-box")
        self.assertNotEqual(review_block.strip(), validation_block.strip())
        self.assertNotIn("validation-result-box", review_block)
        self.assertNotIn("review-confirmation-box", validation_block)

        review_pos = html.find('id="review-confirmation-box"')
        validation_pos = html.find('id="validation-result-box"')
        self.assertGreater(validation_pos, review_pos)

    @_require_contract_renderer
    def test_review_confirmation_separate_from_operation_metadata(self) -> None:
        mod = _CONTRACT_RENDERER
        assert mod is not None
        html = _render_contract_html(mod, build_korea_contract_fixture())
        self.assertIn('id="review-confirmation-box"', html)
        self.assertIn('id="operation-metadata"', html)

        review_block = _extract_review_confirmation_block(html)
        operation_block = _extract_block_by_id(html, "operation-metadata")
        self.assertNotEqual(review_block.strip(), operation_block.strip())
        self.assertNotIn("operation-metadata", review_block)
        self.assertNotIn("review-confirmation-box", operation_block)

        for term in _FORBIDDEN_INTERNAL_METADATA_IN_REVIEW_CONFIRMATION:
            with self.subTest(term=term):
                self.assertNotIn(term, review_block)

    @_require_contract_renderer
    def test_review_confirmation_customer_safe_no_admin_controls(self) -> None:
        mod = _CONTRACT_RENDERER
        assert mod is not None
        for fixture in (
            build_korea_contract_fixture(),
            build_global_contract_fixture(),
        ):
            html = _render_contract_html(mod, fixture)
            review_block = _extract_review_confirmation_block(html)
            for term in _FORBIDDEN_ADMIN_CONTROLS_IN_REVIEW_CONFIRMATION:
                with self.subTest(program=fixture["program_id"], term=term):
                    self.assertNotIn(term, review_block)

    @_require_contract_renderer
    def test_korea_bottom_shot_review_confirmation_warm_close_order(self) -> None:
        mod = _CONTRACT_RENDERER
        assert mod is not None
        html = _render_contract_html(mod, build_korea_contract_fixture())
        positions = _anchor_pos(
            html,
            "bottom-shot-placeholder",
            'id="review-confirmation-box"',
            _WARM_CLOSE_WEEKDAY,
        )
        self.assertEqual(positions, sorted(positions))

    @_require_contract_renderer
    def test_korea_friday_warm_close_after_review_confirmation(self) -> None:
        mod = _CONTRACT_RENDERER
        assert mod is not None
        fixture = build_korea_contract_fixture()
        fixture["warm_close_text"] = _WARM_CLOSE_FRIDAY
        html = _render_contract_html(mod, fixture)
        positions = _anchor_pos(
            html,
            'id="review-confirmation-box"',
            _WARM_CLOSE_FRIDAY,
        )
        self.assertEqual(positions, sorted(positions))

    @_require_contract_renderer
    def test_sent_archived_renderable_for_fixture_only_not_production_gate(self) -> None:
        """sent_archived is renderable for explicit fixture/testing only.

        Production paths must gate sent_archived on a real send/archive completion
        record — see docs/REVIEW_OPERATION_BOX_POLICY.md §5.
        """
        mod = _CONTRACT_RENDERER
        assert mod is not None
        html = _render_contract_html(
            mod, build_korea_contract_fixture(review_state="sent_archived")
        )
        block = _extract_review_confirmation_block(html)
        self.assertIn(_REVIEW_CONFIRMATION_TEXT["sent_archived"], block)
        self.assertRegex(html, r'data-review-state=["\']sent_archived["\']')

    @_require_contract_renderer
    def test_default_review_state_preview_pending_when_omitted(self) -> None:
        mod = _CONTRACT_RENDERER
        assert mod is not None
        fixture = build_korea_contract_fixture()
        fixture.pop("review_state", None)
        html = _render_contract_html(mod, fixture)
        block = _extract_review_confirmation_block(html)
        self.assertIn(_REVIEW_CONFIRMATION_TEXT["preview_pending"], block)
        self.assertRegex(html, r'data-review-state=["\']preview_pending["\']')

    @_require_contract_renderer
    def test_english_review_confirmation_heading_allowed(self) -> None:
        """Heading localization is optional — do not require Korean heading yet."""
        mod = _CONTRACT_RENDERER
        assert mod is not None
        html = _render_contract_html(mod, build_korea_contract_fixture())
        block = _extract_review_confirmation_block(html)
        self.assertIn("Review confirmation", block)


class KeysuriContractPreviewRendererTests(unittest.TestCase):
    """Implementation-dependent tests — skip until keysuri_contract_preview_renderer exists."""

    @_require_contract_renderer
    def test_korea_1830_expected_output_sections(self) -> None:
        mod = _CONTRACT_RENDERER
        assert mod is not None
        html = _render_contract_html(mod, build_korea_contract_fixture())
        required_markers = (
            "미리보기 정보",
            "테크 비서 키수리",
            "국내 테크 TOP 5",
            "키수리의 딥-다이브",
            "원-라인 체크포인트",
            "bottom-shot",
            "review-confirmation",
            "국내 18:30 따뜻한 마무리",
            "마무리 및 출처 리스트",
            "Copyright Ⓒ MirAI:ON. All rights reserved.",
            "무단 전재, 재배포 및 AI학습 이용 절대 금지",
            "운영 정보",
            "Contract compliance checklist",
            "Validation result",
        )
        for marker in required_markers:
            with self.subTest(marker=marker):
                self.assertIn(marker, html)

    @_require_contract_renderer
    def test_korea_1830_section_order(self) -> None:
        mod = _CONTRACT_RENDERER
        assert mod is not None
        html = _render_contract_html(mod, build_korea_contract_fixture())
        anchors = (
            "원-라인 체크포인트",
            "bottom-shot",
            "review-confirmation",
            "국내 18:30 따뜻한 마무리",
            "마무리 및 출처 리스트",
            "Copyright Ⓒ MirAI:ON. All rights reserved.",
            "operation-metadata",
            "validation-result-box",
        )
        positions = _anchor_pos(html, *anchors)
        self.assertEqual(positions, sorted(positions))

    @_require_contract_renderer
    def test_global_1230_expected_output_sections(self) -> None:
        mod = _CONTRACT_RENDERER
        assert mod is not None
        html = _render_contract_html(mod, build_global_contract_fixture())
        self.assertIn("글로벌 테크 TOP 5", html)
        self.assertIn("review-confirmation", html.lower().replace("_", "-"))
        self.assertIn("Copyright Ⓒ MirAI:ON. All rights reserved.", html)
        self.assertIn("Validation result", html)
        self.assertNotIn("국내 18:30 따뜻한 마무리", html)

        closing_pos = html.find("마무리 및 출처 리스트")
        review_pos = html.lower().find("review-confirmation")
        self.assertGreater(closing_pos, review_pos)

    @_require_contract_renderer
    def test_global_review_confirmation_before_closing(self) -> None:
        mod = _CONTRACT_RENDERER
        assert mod is not None
        html = _render_contract_html(mod, build_global_contract_fixture())
        review_pos = html.lower().find("review-confirmation")
        closing_pos = html.find("마무리 및 출처 리스트")
        self.assertGreater(closing_pos, review_pos)

    @_require_contract_renderer
    def test_validator_integration_korea_passes(self) -> None:
        mod = _CONTRACT_RENDERER
        assert mod is not None
        with TemporaryDirectory() as tmpdir:
            path = _write_contract_html(
                mod,
                build_korea_contract_fixture(),
                Path(tmpdir),
                "korea_1830",
            )
            result = validate_keysuri_html_preview(
                str(path),
                program_id="keysuri_korea_tech",
            )
        self.assertTrue(result.is_pass(), msg=str(result.issues))

    @_require_contract_renderer
    def test_validator_integration_global_passes(self) -> None:
        mod = _CONTRACT_RENDERER
        assert mod is not None
        with TemporaryDirectory() as tmpdir:
            path = _write_contract_html(
                mod,
                build_global_contract_fixture(),
                Path(tmpdir),
                "global_1230",
            )
            result = validate_keysuri_html_preview(str(path))
        self.assertTrue(result.is_pass(), msg=str(result.issues))

    @_require_contract_renderer
    def test_no_genie_or_production_bleed(self) -> None:
        mod = _CONTRACT_RENDERER
        assert mod is not None
        for fixture in (build_korea_contract_fixture(), build_global_contract_fixture()):
            html = _render_contract_html(mod, fixture)
            for marker in _FORBIDDEN_BLEED_MARKERS:
                with self.subTest(program=fixture["program_id"], marker=marker):
                    self.assertNotIn(marker, html)

    @_require_contract_renderer
    def test_top5_item_level_source_boxes(self) -> None:
        mod = _CONTRACT_RENDERER
        assert mod is not None
        html = _render_contract_html(mod, build_korea_contract_fixture())
        blocks = re.findall(
            r'data-top-item="(\d)"|class="top-item"[^>]*data-top-item="(\d)"',
            html,
        )
        ranks = {int(a or b) for a, b in blocks}
        self.assertEqual(ranks, {1, 2, 3, 4, 5})
        for rank in range(1, 6):
            with self.subTest(rank=rank):
                self.assertRegex(html, r"(출처명|source_name)", re.IGNORECASE)
                self.assertRegex(html, r"https://")
                self.assertRegex(html, r"(검증 상태|verification_status|sample_only|not_verified)", re.IGNORECASE)

    @_require_contract_renderer
    def test_deep_dive_layer_structure_not_single_dense_block(self) -> None:
        mod = _CONTRACT_RENDERER
        assert mod is not None
        html = _render_contract_html(mod, build_korea_contract_fixture())
        layer_count = len(re.findall(r'class="[^"]*\bdeep-layer\b', html, flags=re.IGNORECASE))
        self.assertGreaterEqual(layer_count, 3)
        for title in ("물리·인프라 병목", "규제·주권·조달 압력", "워크플로·락인"):
            self.assertIn(title, html)


class KeysuriThemeSeparationRendererTests(unittest.TestCase):
    @_require_contract_renderer
    def test_global_body_has_theme_global(self) -> None:
        mod = _CONTRACT_RENDERER
        assert mod is not None
        html = _render_contract_html(mod, build_global_contract_fixture())
        self.assertRegex(html, r'<body class="premium-briefing theme-global">')
        self.assertNotRegex(
            html,
            r'<body class="premium-briefing theme-korea">',
        )

    @_require_contract_renderer
    def test_korea_body_has_theme_korea(self) -> None:
        mod = _CONTRACT_RENDERER
        assert mod is not None
        html = _render_contract_html(mod, build_korea_contract_fixture())
        self.assertIn('class="premium-briefing theme-korea"', html)

    @_require_contract_renderer
    def test_global_no_bottom_shot_block(self) -> None:
        mod = _CONTRACT_RENDERER
        assert mod is not None
        fixture = build_global_contract_fixture()
        fixture["bottom_shot_image_src"] = "data:image/jpeg;base64,abc"
        html = _render_contract_html(mod, fixture)
        self.assertNotIn("bottom-shot-placeholder", html)
        self.assertNotIn('id="bottom-shot-image"', html)

    @_require_contract_renderer
    def test_global_framing_markers_present(self) -> None:
        mod = _CONTRACT_RENDERER
        assert mod is not None
        html = _render_contract_html(mod, build_global_contract_fixture())
        self.assertIn("글로벌 신호 · 12:30", html)
        self.assertIn("글로벌 원인", html)
        self.assertIn("한국 도착 전 압력", html)
        self.assertIn("다음 48시간 관찰 포인트", html)
        self.assertIn("산업 레이어가 어디로 이동하나", html)

    @_require_contract_renderer
    def test_korea_framing_markers_present(self) -> None:
        mod = _CONTRACT_RENDERER
        assert mod is not None
        html = _render_contract_html(mod, build_korea_contract_fixture())
        self.assertIn("국내 해석 · 18:30", html)
        self.assertIn("국내 적용", html)
        self.assertIn("내일 영향", html)
        self.assertIn("한국 기업·정책으로 읽으면", html)
        self.assertIn("오늘의 정리와 퇴근 전 메모", html)
        self.assertIn("bottom-shot-placeholder", html)

    @_require_contract_renderer
    def test_global_light_tokens_not_dark_navy(self) -> None:
        mod = _CONTRACT_RENDERER
        assert mod is not None
        html = _render_contract_html(mod, build_global_contract_fixture())
        style = html[html.find("<style>") : html.find("</style>")]
        self.assertIn("--g-bg:#f3f6fa", style.replace(" ", ""))
        self.assertNotIn("#0a0f1a", style)
        self.assertNotIn("#070d18", style)

    @_require_contract_renderer
    def test_korea_warm_dark_tokens(self) -> None:
        mod = _CONTRACT_RENDERER
        assert mod is not None
        html = _render_contract_html(mod, build_korea_contract_fixture())
        style = html[html.find("<style>") : html.find("</style>")]
        self.assertIn("--k-bg:#14110d", style.replace(" ", ""))
        self.assertIn("--k-gold:#cda85f", style.replace(" ", ""))


class KeysuriPremiumHandoffRendererTests(unittest.TestCase):
    @_require_contract_renderer
    def test_hero_uses_data_uri_not_relative_path(self) -> None:
        mod = _CONTRACT_RENDERER
        assert mod is not None
        html = _render_contract_html(mod, build_global_contract_fixture())
        self.assertIn('id="top-shot-image"', html)
        self.assertIn('class="top-shot-hero"', html)
        self.assertNotIn("../image_canary", html)
        match = re.search(
            r'<img[^>]*class="top-shot-hero"[^>]*src="([^"]+)"'
            r'|<img[^>]*src="([^"]+)"[^>]*class="top-shot-hero"',
            html,
        )
        self.assertIsNotNone(match)
        assert match is not None
        src = match.group(1) or match.group(2)
        self.assertTrue(src.startswith("data:image/"))

    @_require_contract_renderer
    def test_preheader_and_color_scheme_present(self) -> None:
        mod = _CONTRACT_RENDERER
        assert mod is not None
        html = _render_contract_html(mod, build_global_contract_fixture())
        self.assertIn('name="color-scheme"', html)
        self.assertIn('class="preheader-hidden"', html)
        body_start = html.find("<body")
        preheader_pos = html.find("preheader-hidden")
        shell_pos = html.find('<div class="briefing-shell">')
        self.assertGreater(preheader_pos, body_start)
        self.assertLess(preheader_pos, shell_pos)

    @_require_contract_renderer
    def test_signal_summary_and_judgment_micro_label(self) -> None:
        mod = _CONTRACT_RENDERER
        assert mod is not None
        html = _render_contract_html(mod, build_global_contract_fixture())
        self.assertIn('id="signal-summary"', html)
        self.assertGreaterEqual(html.count('class="judgment-label"'), 5)

    @_require_contract_renderer
    def test_audit_fold_collapses_operational_metadata(self) -> None:
        mod = _CONTRACT_RENDERER
        assert mod is not None
        html = _render_contract_html(mod, build_global_contract_fixture())
        self.assertIn('class="audit-fold"', html)
        self.assertIn('id="operation-metadata"', html)
        audit_pos = html.find("audit-fold")
        op_pos = html.find('id="operation-metadata"')
        self.assertLess(audit_pos, op_pos)

    @_require_contract_renderer
    def test_hero_portrait_uses_contain_not_cover(self) -> None:
        mod = _CONTRACT_RENDERER
        assert mod is not None
        html = _render_contract_html(mod, build_global_contract_fixture())
        style_block = html[html.find("<style>") : html.find("</style>")]
        self.assertIn("object-fit:contain", style_block.replace(" ", ""))
        self.assertNotRegex(style_block, r"\.top-shot-hero\{[^}]*object-fit:\s*cover")
        self.assertNotIn("object-fit:cover", style_block.replace(" ", ""))
        self.assertIn('class="hero-layout"', html)


if __name__ == "__main__":
    unittest.main()
