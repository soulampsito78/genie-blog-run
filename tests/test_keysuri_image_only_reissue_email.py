"""Tests for the image_only reissue email rebuild and mobile-Gmail-safe layout.

Reproduces the keysuri_korea_tech issue where an "이미지만 재발행" owner-review
email looked like only the image was delivered: the reissue body was byte
identical to the parent owner-review already in the Gmail thread, so mobile
Gmail folded the briefing behind a "…". The rebuild reuses the body verbatim
but injects a run-unique marker right after the hero image so the body is shown,
while keeping the operator-only marker out of the customer-final email.
"""
from __future__ import annotations

import unittest

from keysuri_contract_preview_renderer import (
    IMAGE_ONLY_REISSUE_MARKER_ID,
    assemble_image_only_reissue_email_html,
    image_only_reissue_email_has_body,
    _owner_review_admin_email_block,
)
from keysuri_customer_delivery import strip_keysuri_owner_review_controls

CHILD_RUN_ID = "20260626_120005_keysuri_korea_tech_deadbeef"
REISSUED_AT = "2026-06-26T12:00:05.123+09:00"


def _owner_email_html(*, with_hero: bool = True) -> str:
    """A production-shaped Korea owner-review email (hero, body, sources, admin)."""
    hero = (
        '<tr><td style="padding:0 0 16px 0;">'
        '<img src="cid:keysuri_topshot_korea_20260625" alt="hero" width="568" '
        'style="display:block;width:100%;border-radius:14px;" /></td></tr>'
        if with_hero
        else ""
    )
    admin = _owner_review_admin_email_block(
        admin_url="https://genie-blog-run.example.com/admin/runs/20260625_195226_keysuri_korea_tech_6453b12b",
        run_id="20260625_195226_keysuri_korea_tech_6453b12b",
    )
    return f"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="UTF-8"/><title>t</title></head>
<body style="margin:0;padding:0;background:#14110d;">
<span style="display:none!important;opacity:0;color:transparent;">국내 AI·테크 신호 검수 대기 · 주요 신호: 환경보전원</span>
<table role="presentation" width="100%" border="0"><tr><td>
<table role="presentation" width="600" border="0">
<tr><td>
<table role="presentation" width="100%" border="0">
{hero}
<tr><td>
<p style="color:#cda85f;">국내 해석 · 18:30</p>
<h1 style="color:#f3ece0;">키수리 국내 테크 브리핑</h1>
<p style="color:#c8bca8;">주인님께 먼저 올리는 오늘의 국내 AI·테크 신호</p>
</td></tr>
</table>
</td></tr>
<tr><td>
<p style="color:#f3ece0;">주인님, 오늘 국내 테크 동향은 정부 주도의 환경 교육 강화와 핵심 인프라 투자 확대라는 두 축으로 요약됩니다.</p>
<h2 style="color:#f3ece0;">국내 테크 TOP 5</h2>
<h3>1. 환경보전원, 기후에너지환경교육 정책 공유</h3>
<a href="https://www.electimes.com/news/articleView.html?idxno=1">출처</a>
<h3>2. 국민성장펀드, AI 전력망에 3700억 투입</h3>
<a href="https://www.etnews.com/20260625000425">출처</a>
<h2 style="color:#f3ece0;">키수리의 딥-다이브</h2>
<p>국내 반도체 소부장 흐름이 핵심입니다.</p>
<h2 style="color:#f3ece0;">마무리 및 출처 리스트</h2>
<a href="https://zdnet.co.kr/view/?no=20260625191003">출처</a>
{admin}
</td></tr>
</table>
</td></tr></table>
</body></html>"""


class AssembleImageOnlyReissueEmailTests(unittest.TestCase):
    def _assemble(self, html: str, program_id: str = "keysuri_korea_tech") -> str:
        return assemble_image_only_reissue_email_html(
            html,
            child_run_id=CHILD_RUN_ID,
            reissued_at_kst=REISSUED_AT,
            program_id=program_id,
        )

    def test_marker_injected_after_hero_before_title(self) -> None:
        out = self._assemble(_owner_email_html())
        self.assertIn(IMAGE_ONLY_REISSUE_MARKER_ID, out)
        hero = out.index("cid:keysuri_topshot")
        marker = out.index(IMAGE_ONLY_REISSUE_MARKER_ID)
        h1 = out.index("<h1")
        self.assertLess(hero, marker, "marker must come after the hero image")
        self.assertLess(marker, h1, "marker must come before the title")

    def test_body_preserved_verbatim(self) -> None:
        src = _owner_email_html()
        out = self._assemble(src)
        # Every body landmark survives the rebuild unchanged.
        for landmark in (
            "주인님, 오늘 국내 테크 동향",
            "국내 테크 TOP 5",
            "환경보전원, 기후에너지환경교육 정책 공유",
            "키수리의 딥-다이브",
            "https://www.etnews.com/20260625000425",
        ):
            self.assertIn(landmark, out)

    def test_marker_carries_run_unique_text(self) -> None:
        out = self._assemble(_owner_email_html())
        # run suffix + reissue time make the leading content unique per reissue.
        self.assertIn("deadbeef", out)
        self.assertIn("12:00 KST", out)

    def test_idempotent_no_double_marker(self) -> None:
        once = self._assemble(_owner_email_html())
        twice = assemble_image_only_reissue_email_html(
            once, child_run_id="x_y_z", reissued_at_kst="2026", program_id="keysuri_korea_tech"
        )
        self.assertEqual(once, twice)
        self.assertEqual(once.count(f'id="{IMAGE_ONLY_REISSUE_MARKER_ID}"'), 1)

    def test_global_program_marker(self) -> None:
        out = self._assemble(_owner_email_html(), program_id="keysuri_global_tech")
        self.assertIn(IMAGE_ONLY_REISSUE_MARKER_ID, out)

    def test_fallback_injects_before_h1_without_hero(self) -> None:
        out = self._assemble(_owner_email_html(with_hero=False))
        self.assertIn(IMAGE_ONLY_REISSUE_MARKER_ID, out)
        self.assertLess(out.index(IMAGE_ONLY_REISSUE_MARKER_ID), out.index("<h1"))

    def test_empty_html_returns_unchanged(self) -> None:
        self.assertEqual(self._assemble("   "), "   ")


class BodyPresenceCheckerTests(unittest.TestCase):
    def test_full_email_has_body_true(self) -> None:
        self.assertTrue(image_only_reissue_email_has_body(_owner_email_html()))

    def test_after_rebuild_has_body_true(self) -> None:
        out = assemble_image_only_reissue_email_html(
            _owner_email_html(),
            child_run_id=CHILD_RUN_ID,
            reissued_at_kst=REISSUED_AT,
            program_id="keysuri_korea_tech",
        )
        self.assertTrue(image_only_reissue_email_has_body(out))

    def test_image_only_fragment_has_body_false(self) -> None:
        fragment = (
            '<html><body><img src="cid:keysuri_topshot_korea_20260625"/>'
            '<a href="https://example.com/admin/runs/x">review</a></body></html>'
        )
        self.assertFalse(image_only_reissue_email_has_body(fragment))


class OwnerCustomerSeparationTests(unittest.TestCase):
    def _owner(self) -> str:
        return assemble_image_only_reissue_email_html(
            _owner_email_html(),
            child_run_id=CHILD_RUN_ID,
            reissued_at_kst=REISSUED_AT,
            program_id="keysuri_korea_tech",
        )

    def test_marker_present_in_owner_email(self) -> None:
        self.assertIn("이미지 재발행", self._owner())

    def test_marker_stripped_from_customer_email(self) -> None:
        customer = strip_keysuri_owner_review_controls(self._owner())
        self.assertNotIn(IMAGE_ONLY_REISSUE_MARKER_ID, customer)
        self.assertNotIn("이미지 재발행", customer)

    def test_admin_link_absent_from_customer_email(self) -> None:
        customer = strip_keysuri_owner_review_controls(self._owner())
        self.assertNotIn("운영자 검수 화면 열기", customer)
        self.assertNotIn("/admin/runs/", customer)

    def test_customer_email_retains_body(self) -> None:
        customer = strip_keysuri_owner_review_controls(self._owner())
        self.assertIn("환경보전원", customer)
        self.assertIn("키수리의 딥-다이브", customer)


class HtmlOrderTests(unittest.TestCase):
    def test_admin_block_after_body(self) -> None:
        out = assemble_image_only_reissue_email_html(
            _owner_email_html(),
            child_run_id=CHILD_RUN_ID,
            reissued_at_kst=REISSUED_AT,
            program_id="keysuri_korea_tech",
        )
        admin_idx = out.index("운영자 검수 화면 열기")
        body_idx = out.index("키수리의 딥-다이브")
        first_news_idx = out.index("국내 테크 TOP 5")
        self.assertLess(first_news_idx, admin_idx, "body must precede the admin card")
        self.assertLess(body_idx, admin_idx, "deep-dive must precede the admin card")

    def test_body_intro_visible_soon_after_hero(self) -> None:
        out = assemble_image_only_reissue_email_html(
            _owner_email_html(),
            child_run_id=CHILD_RUN_ID,
            reissued_at_kst=REISSUED_AT,
            program_id="keysuri_korea_tech",
        )
        # The opening lead / first body summary appears right after the title,
        # before the first TOP5 section — not pushed far down by the admin card.
        intro_idx = out.index("주인님, 오늘 국내 테크 동향")
        admin_idx = out.index("운영자 검수 화면 열기")
        self.assertLess(intro_idx, admin_idx)


if __name__ == "__main__":
    unittest.main()
