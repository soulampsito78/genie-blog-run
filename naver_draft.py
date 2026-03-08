"""
Thin Naver Blog draft creation via Playwright. Saves a post as draft only;
no auto-publish. Invoked by the orchestrator when policy allows.
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


def _read_secret(env_key: str, file_env_key: str) -> str:
    """Read from env or, if file_env_key is set, from that path (Secret Manager mount)."""
    val = os.getenv(env_key, "").strip()
    if val:
        return val
    path = os.getenv(file_env_key, "").strip()
    if path and os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as f:
                return f.read().strip()
        except OSError:
            pass
    return ""


NAVER_ID = os.getenv("NAVER_ID", "")
NAVER_PASSWORD = _read_secret("NAVER_PASSWORD", "NAVER_PASSWORD_FILE") or _read_secret("NAVER_APP_PASSWORD", "NAVER_APP_PASSWORD_FILE")
NAVER_BLOG_ID = os.getenv("NAVER_BLOG_ID", "")
NAVER_HEADLESS = os.getenv("NAVER_HEADLESS", "true").lower() in ("1", "true", "yes")
NAVER_DRAFT_TIMEOUT_MS = int(os.getenv("NAVER_DRAFT_TIMEOUT_MS", "60000"))


def create_naver_draft(html_body: str, title: str) -> bool:
    """
    Create a Naver Blog post draft via Playwright (login → compose → set title/body → save draft).

    Args:
        html_body: HTML body (e.g. from rendered_channels.naver_blog_body_html)
        title: Post title (e.g. from channel_drafts.naver_blog_title)

    Returns:
        True if draft was saved, False on misconfiguration or failure.
    """
    if not NAVER_ID or not NAVER_PASSWORD:
        logger.warning("create_naver_draft: skipped (NAVER_ID, NAVER_PASSWORD required)")
        return False
    if not NAVER_BLOG_ID:
        logger.warning("create_naver_draft: skipped (NAVER_BLOG_ID required)")
        return False
    if not title.strip():
        logger.warning("create_naver_draft: skipped (empty title)")
        return False

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.warning("create_naver_draft: skipped (playwright not installed)")
        return False

    timeout = NAVER_DRAFT_TIMEOUT_MS
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=NAVER_HEADLESS)
            try:
                context = browser.new_context(
                    viewport={"width": 1280, "height": 720},
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                    ),
                )
                page = context.new_page()
                page.set_default_timeout(timeout)

                # Login
                page.goto("https://nid.naver.com/nidlogin.login")
                page.fill("input#id", NAVER_ID)
                page.fill("input#pw", NAVER_PASSWORD)
                page.click("button#log.login")
                page.wait_for_load_state("networkidle", timeout=timeout)

                if "nid.naver.com" in page.url and "nidlogin" in page.url:
                    logger.warning("create_naver_draft: likely login failed (CAPTCHA or verification)")
                    return False

                page.goto(f"https://blog.naver.com/{NAVER_BLOG_ID}/postwrite")
                page.wait_for_load_state("domcontentloaded", timeout=timeout)
                page.wait_for_selector("[contenteditable='true'], .se-title-text, input", timeout=15000)

                title_el = page.query_selector(".se-title-text, .se-module-title [contenteditable], input[placeholder*='제목']")
                if title_el:
                    try:
                        title_el.fill(title)
                    except Exception:
                        title_el.evaluate("(el, t) => { el.textContent = t; el.dispatchEvent(new Event('input', { bubbles: true })); }", title)

                body_el = page.query_selector(".se-component-content [contenteditable='true'], .se-main-container [contenteditable='true'], [contenteditable='true'].se-text-paragraph")
                if body_el:
                    body_el.evaluate(
                        "(el, html) => { el.innerHTML = html; el.dispatchEvent(new Event('input', { bubbles: true })); }",
                        html_body,
                    )

                draft_btn = page.get_by_role("button", name="임시저장")
                if draft_btn.count() == 0:
                    draft_btn = page.locator("button:has-text('임시저장'), a:has-text('임시저장')").first
                draft_btn.click(timeout=10000)
                page.wait_for_load_state("networkidle", timeout=15000)

                logger.info("create_naver_draft: draft saved (title=%s)", title[:50])
                return True
            finally:
                browser.close()

    except Exception as e:
        logger.exception("create_naver_draft: failed: %s", e)
        return False
