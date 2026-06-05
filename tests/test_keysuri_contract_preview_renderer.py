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


def _sample_top_item(rank: int, *, scope: str) -> dict[str, Any]:
    return {
        "rank": rank,
        "headline": f"Staged sample headline {rank} ({scope})",
        "what_happened": f"Staged sample signal capture for item {rank}.",
        "why_it_matters": f"Staged structural relevance note {rank}.",
        "business_implication": f"Staged business implication {rank}.",
        "risk_note": f"Staged optional risk note {rank}.",
        "source_name": f"Sample Source {rank}",
        "source_url": f"https://example.com/source/{scope}-item-{rank}",
        "checked_at": "2026-06-05T12:00:00+09:00",
        "verification_status": "sample_only / not_verified",
    }


def _sample_deep_dive_layers(*, scope: str) -> list[dict[str, str]]:
    if scope == "korea":
        return [
            {
                "layer_number": "1",
                "layer_title": "물리·인프라 병목",
                "layer_body": "Staged Korea layer one — infrastructure bottleneck sample.",
            },
            {
                "layer_number": "2",
                "layer_title": "규제·주권·조달 압력",
                "layer_body": "Staged Korea layer two — regulation and procurement pressure sample.",
            },
            {
                "layer_number": "3",
                "layer_title": "워크플로·락인",
                "layer_body": "Staged Korea layer three — workflow lock-in sample.",
            },
        ]
    return [
        {
            "layer_number": "1",
            "layer_title": "Infrastructure signal",
            "layer_body": "Staged global layer one — infrastructure movement sample.",
        },
        {
            "layer_number": "2",
            "layer_title": "Platform control shift",
            "layer_body": "Staged global layer two — platform control sample.",
        },
        {
            "layer_number": "3",
            "layer_title": "Workflow leverage",
            "layer_body": "Staged global layer three — workflow leverage sample.",
        },
    ]


def build_korea_contract_fixture(*, review_state: str = "preview_pending") -> dict[str, Any]:
    """Local fixture for future Korea 18:30 contract preview renderer."""
    return {
        "program_id": "keysuri_korea_tech",
        "slot": "18:30",
        "review_state": review_state,
        "title_candidates": [
            "[키수리 브리핑] Staged domestic infra signal sample",
            "[키수리] Staged regulation pressure sample",
        ],
        "selected_title": "[키수리 브리핑] Staged domestic infra signal sample",
        "opening_lead": "Staged opening lead — domestic tech signal first, not greeting-first.",
        "top_5_heading": "국내 테크 TOP 5",
        "top_5_items": [_sample_top_item(i, scope="korea") for i in range(1, 6)],
        "deep_dive_heading": "키수리의 딥-다이브",
        "deep_dive_layers": _sample_deep_dive_layers(scope="korea"),
        "one_line_checkpoint": "Staged one-line decision cue for domestic preview.",
        "warm_close_text": "오늘도 수고하셨습니다. 내일 다시 뵙겠습니다.",
        "closing_message": "Staged closing message for domestic contract preview.",
        "source_list": [
            {
                "source_id": "korea-t0-sample",
                "source_name": "Sample Domestic Official",
                "source_url": "https://example.com/source/korea-official",
                "verification_status": "sample_only / not_verified",
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
            "[키수리 브리핑] Staged global infra signal sample",
            "[키수리] Staged platform control sample",
        ],
        "selected_title": "[키수리 브리핑] Staged global infra signal sample",
        "opening_lead": "Staged opening lead — global tech signal first, not greeting-first.",
        "top_5_heading": "글로벌 테크 TOP 5",
        "top_5_items": [_sample_top_item(i, scope="global") for i in range(1, 6)],
        "deep_dive_heading": "키수리의 딥-다이브",
        "deep_dive_layers": _sample_deep_dive_layers(scope="global"),
        "one_line_checkpoint": "Staged one-line decision cue for global preview.",
        "closing_message": "Staged closing message for global contract preview.",
        "source_list": [
            {
                "source_id": "global-t0-sample",
                "source_name": "Sample Global Official",
                "source_url": "https://example.com/source/global-official",
                "verification_status": "sample_only / not_verified",
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
            self.assertIn("sample_only", item["verification_status"])


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
            "Preview metadata",
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
            "Operation metadata",
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


if __name__ == "__main__":
    unittest.main()
