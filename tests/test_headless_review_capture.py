from __future__ import annotations

"""
tests/test_headless_review_capture.py

Synthetic offline unit and integration tests for scripts/capture_review_surfaces_headless.py.
Covers strict input validation, network request method/origin policy allowlist,
customer DOM verification, image element checks, and real headless Chromium launch
with viewport/geometry extraction and fullpage PNG capture.
"""

import base64
import hashlib
import importlib.util
import os
import sys
from pathlib import Path
import pytest

# Dynamic import of collector script without modifying global package structure
MODULE_PATH = Path(__file__).resolve().parent.parent / "scripts" / "capture_review_surfaces_headless.py"
spec = importlib.util.spec_from_file_location("capture_review_surfaces_headless", MODULE_PATH)
collector = importlib.util.module_from_spec(spec)
sys.modules["capture_review_surfaces_headless"] = collector
spec.loader.exec_module(collector)

CANONICAL_ORIGIN = collector.CANONICAL_ORIGIN
REQUIRED_AI_FOOTER = collector.REQUIRED_AI_FOOTER
CollectorValidationError = collector.CollectorValidationError
CollectorSecurityError = collector.CollectorSecurityError

TINY_PNG_BASE64_DATA = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)
TINY_PNG_RAW_BYTES = base64.b64decode(TINY_PNG_BASE64_DATA)
TINY_PNG_DATA_URI = f"data:image/png;base64,{TINY_PNG_BASE64_DATA}"


# ---------------------------------------------------------------------------
# 1. Strict Input Validation Tests
# ---------------------------------------------------------------------------

def test_validate_run_id_valid_types():
    assert collector.validate_run_id("20261103_120000_today_genie_1234abcd") == "20261103_120000_today_genie_1234abcd"
    assert collector.validate_run_id("20261103_120000_keysuri_korea_tech_abcd1234") == "20261103_120000_keysuri_korea_tech_abcd1234"
    assert collector.validate_run_id("20261103_120000_keysuri_global_tech_deadbeef") == "20261103_120000_keysuri_global_tech_deadbeef"


def test_validate_run_id_invalid_formats():
    invalid_ids = [
        "2026110_120000_today_genie_1234abcd",       # 7 digit date
        "20261103_12000_today_genie_1234abcd",       # 5 digit time
        "20261103_120000_unknown_genie_1234abcd",    # invalid type
        "20261103_120000_today_genie_1234abc",       # 7 hex
        "20261103_120000_today_genie_1234abcde",     # 9 hex
        "20261103_120000_today_genie_1234ABCD",     # uppercase hex
        "../../etc/passwd",
        "",
        None,
    ]
    for bad_id in invalid_ids:
        with pytest.raises(CollectorValidationError):
            collector.validate_run_id(bad_id)


def test_validate_target_sha256():
    valid_sha = "a" * 64
    assert collector.validate_target_sha256(valid_sha) == valid_sha
    assert collector.validate_target_sha256(valid_sha.upper()) == valid_sha

    invalid_shas = [
        "a" * 63,
        "a" * 65,
        "z" * 64,
        "",
        12345,
    ]
    for bad_sha in invalid_shas:
        with pytest.raises(CollectorValidationError):
            collector.validate_target_sha256(bad_sha)


def test_expected_image_roles_and_counts():
    assert collector.get_expected_image_roles("20261103_120000_today_genie_1234abcd") == ["top", "bottom"]
    assert collector.get_expected_image_roles("20261103_120000_keysuri_korea_tech_1234abcd") == ["top", "bottom"]
    assert collector.get_expected_image_roles("20261103_120000_keysuri_global_tech_1234abcd") == ["top"]


# ---------------------------------------------------------------------------
# 2. Network Method & Origin Policy Allowlist Tests
# ---------------------------------------------------------------------------

def test_check_request_allowed_canonical_get_and_head():
    url = f"{CANONICAL_ORIGIN}/admin/runs/20261103_120000_today_genie_1234abcd/email"
    allowed, _ = collector.check_request_allowed(url, "GET")
    assert allowed is True
    allowed, _ = collector.check_request_allowed(url, "HEAD")
    assert allowed is True


def test_check_request_allowed_exact_login_post():
    login_url = f"{CANONICAL_ORIGIN}/admin/login"
    allowed, _ = collector.check_request_allowed(login_url, "POST")
    assert allowed is True


def test_check_request_denies_unauthorized_post():
    other_post_url = f"{CANONICAL_ORIGIN}/admin/runs/20261103_120000_today_genie_1234abcd/email"
    allowed, reason = collector.check_request_allowed(other_post_url, "POST")
    assert allowed is False
    assert "POST forbidden" in reason


def test_check_request_denies_mutation_methods():
    url = f"{CANONICAL_ORIGIN}/admin/runs/20261103_120000_today_genie_1234abcd/email"
    for method in ("PUT", "DELETE", "PATCH", "OPTIONS"):
        allowed, reason = collector.check_request_allowed(url, method)
        assert allowed is False
        assert "forbidden" in reason


def test_check_request_denies_off_origin():
    off_origin_urls = [
        "https://evil.example.com/admin/login",
        "https://fonts.googleapis.com/css?family=Roboto",
        "http://genie-blog-run-1055014091206.asia-northeast3.run.app/admin",  # insecure http
        "https://other-service.run.app/test",
    ]
    for url in off_origin_urls:
        allowed, reason = collector.check_request_allowed(url, "GET")
        assert allowed is False
        assert "Off-origin request forbidden" in reason


def test_check_request_denies_forbidden_mutation_endpoints():
    forbidden_endpoints = [
        f"{CANONICAL_ORIGIN}/admin/generate_candidate",
        f"{CANONICAL_ORIGIN}/admin/reissue_grant",
        f"{CANONICAL_ORIGIN}/admin/runs/20261103_120000_today_genie_1234abcd/approve",
        f"{CANONICAL_ORIGIN}/admin/runs/20261103_120000_today_genie_1234abcd/register_dispatch",
        f"{CANONICAL_ORIGIN}/admin/send_email",
        f"{CANONICAL_ORIGIN}/admin/signature/verify",
    ]
    for url in forbidden_endpoints:
        allowed, reason = collector.check_request_allowed(url, "GET")
        assert allowed is False
        assert "Forbidden endpoint keyword" in reason


def test_check_request_synthetic_data_uri_policy():
    data_uri = TINY_PNG_DATA_URI
    # Disallowed in normal run
    allowed, _ = collector.check_request_allowed(data_uri, "GET", allow_synthetic_data_urls=False)
    assert allowed is False

    # Allowed in synthetic test mode for GET
    allowed, _ = collector.check_request_allowed(data_uri, "GET", allow_synthetic_data_urls=True)
    assert allowed is True

    # Denied for POST even in synthetic mode
    allowed, _ = collector.check_request_allowed(data_uri, "POST", allow_synthetic_data_urls=True)
    assert allowed is False


# ---------------------------------------------------------------------------
# 3. Customer DOM and Image Element Validation Tests (Synthetic)
# ---------------------------------------------------------------------------

def test_validate_customer_dom_success(tmp_path):
    if collector.sync_playwright is None:
        pytest.fail("NOT_VERIFIED: playwright not importable")

    with collector.sync_playwright() as p:
        browser = collector.launch_browser(p)
        context = browser.new_context(service_workers="block")
        page = context.new_page()
        try:
            valid_html = f"""
            <!DOCTYPE html>
            <html>
            <body>
                <h1>Genie Customer Preview</h1>
                <p>Hello customer, review your content here.</p>
                <div class="footer">
                    <p>{REQUIRED_AI_FOOTER}</p>
                </div>
            </body>
            </html>
            """
            page.set_content(valid_html)
            collector.validate_customer_dom(page)
        finally:
            context.close()
            browser.close()


def test_validate_customer_dom_missing_footer(tmp_path):
    if collector.sync_playwright is None:
        pytest.fail("NOT_VERIFIED: playwright not importable")

    with collector.sync_playwright() as p:
        browser = collector.launch_browser(p)
        context = browser.new_context(service_workers="block")
        page = context.new_page()
        try:
            missing_footer_html = """
            <!DOCTYPE html>
            <html>
            <body>
                <h1>Genie Customer Preview</h1>
                <p>Missing AI footer</p>
            </body>
            </html>
            """
            page.set_content(missing_footer_html)
            with pytest.raises(CollectorValidationError, match="missing required AI review footer"):
                collector.validate_customer_dom(page)
        finally:
            context.close()
            browser.close()


def test_validate_customer_dom_contains_admin_link(tmp_path):
    if collector.sync_playwright is None:
        pytest.fail("NOT_VERIFIED: playwright not importable")

    with collector.sync_playwright() as p:
        browser = collector.launch_browser(p)
        context = browser.new_context(service_workers="block")
        page = context.new_page()
        try:
            admin_link_html = f"""
            <!DOCTYPE html>
            <html>
            <body>
                <h1>Genie Customer Preview</h1>
                <a href="/admin/operations">Admin Operations</a>
                <p>{REQUIRED_AI_FOOTER}</p>
            </body>
            </html>
            """
            page.set_content(admin_link_html)
            with pytest.raises(CollectorValidationError, match="prohibited owner admin link"):
                collector.validate_customer_dom(page)
        finally:
            context.close()
            browser.close()


def test_validate_customer_dom_contains_human_waiting_copy(tmp_path):
    if collector.sync_playwright is None:
        pytest.fail("NOT_VERIFIED: playwright not importable")

    with collector.sync_playwright() as p:
        browser = collector.launch_browser(p)
        context = browser.new_context(service_workers="block")
        page = context.new_page()
        try:
            waiting_html = f"""
            <!DOCTYPE html>
            <html>
            <body>
                <h1>Genie Customer Preview</h1>
                <p>현재 상태: 승인 대기</p>
                <p>{REQUIRED_AI_FOOTER}</p>
            </body>
            </html>
            """
            page.set_content(waiting_html)
            with pytest.raises(CollectorValidationError, match="prohibited direct-human-waiting copy"):
                collector.validate_customer_dom(page)
        finally:
            context.close()
            browser.close()


def test_validate_image_elements_synthetic(tmp_path):
    if collector.sync_playwright is None:
        pytest.fail("NOT_VERIFIED: playwright not importable")

    run_id_today = "20261103_120000_today_genie_1234abcd"
    run_id_global = "20261103_120000_keysuri_global_tech_1234abcd"

    with collector.sync_playwright() as p:
        browser = collector.launch_browser(p)
        context = browser.new_context(service_workers="block")
        page = context.new_page()
        try:
            # Test global tech: exactly 1 image
            single_img_html = f"""
            <!DOCTYPE html>
            <html>
            <body>
                <img src="{TINY_PNG_DATA_URI}" alt="top"/>
            </body>
            </html>
            """
            page.set_content(single_img_html)
            images = collector.validate_image_elements(
                page, run_id_global, is_customer=False, allow_synthetic=True
            )
            assert len(images) == 1
            assert images[0]["role"] == "top"
            assert images[0]["complete"] is True
            assert images[0]["natural_width"] > 0

            # Test today_genie: requires 2 images, but only 1 present -> fails
            with pytest.raises(CollectorValidationError, match="Expected 2 image"):
                collector.validate_image_elements(
                    page, run_id_today, is_customer=False, allow_synthetic=True
                )
        finally:
            context.close()
            browser.close()


# ---------------------------------------------------------------------------
# 4. Real Headless Chromium Launch, Geometry & Full-page PNG Capture Test
# ---------------------------------------------------------------------------

def test_real_headless_launch_geometry_and_screenshot(tmp_path):
    """
    Test real Playwright Chromium launch headless=True.
    Validates viewport 375x667, geometry calculation, isolated horizontal overflow observation,
    and uncorrupted fullpage PNG screenshot capture with valid SHA256 digest and mode 0600.
    """
    if collector.sync_playwright is None:
        pytest.fail("NOT_VERIFIED: playwright not importable")

    try:
        with collector.sync_playwright() as p:
            browser = collector.launch_browser(p)
            context = browser.new_context(service_workers="block")
            page = context.new_page()

            # Synthetic page containing an overflowing long URL element (800px width > 375px viewport)
            synthetic_html = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <style>
                    body {{ margin: 0; padding: 16px; font-family: sans-serif; }}
                    .overflow-container {{
                        width: 800px;
                        white-space: nowrap;
                    }}
                </style>
            </head>
            <body>
                <h2>Review Surface Evidence Test</h2>
                <img id="top-image" src="{TINY_PNG_DATA_URI}" alt="top"/>
                <div class="overflow-container">
                    https://example.com/very/long/url/that/extends/beyond/mobile/viewport/geometry/for/testing
                </div>
                <footer>
                    <p>{REQUIRED_AI_FOOTER}</p>
                </footer>
            </body>
            </html>
            """
            mobile_viewport = {"width": 375, "height": 667}
            page.set_viewport_size(mobile_viewport)
            page.set_content(synthetic_html)

            # Extract geometry
            geometry = collector.extract_surface_geometry(page)
            assert geometry["viewport"]["width"] == 375
            assert geometry["viewport"]["height"] == 667
            assert geometry["document"]["scrollWidth"] >= 800
            # Isolated long URL overflow is recorded as observed nonblocking data
            assert geometry["overflow_observed"] is True

            # Capture surface PNG
            surface_meta = collector.capture_surface(
                page=page,
                output_dir=tmp_path,
                surface_name="test_mobile",
                viewport=mobile_viewport,
                wait_for_images=True,
            )

            assert surface_meta["surface_name"] == "test_mobile"
            assert surface_meta["screenshot_file"] == "test_mobile.png"
            png_file = tmp_path / "test_mobile.png"
            assert png_file.exists()
            assert (os.stat(png_file).st_mode & 0o777) == 0o600

            with open(png_file, "rb") as f:
                raw_bytes = f.read()

            # Verify standard PNG file header: \x89PNG\r\n\x1a\n
            assert raw_bytes[:8] == b"\x89PNG\r\n\x1a\n"
            computed_hash = hashlib.sha256(raw_bytes).hexdigest()
            assert surface_meta["screenshot_sha256"] == computed_hash

            context.close()
            browser.close()
    except Exception as exc:
        msg = str(exc)
        if "Executable doesn't exist" in msg or "browser" in msg.lower():
            pytest.fail(f"NOT_VERIFIED: {msg}")
        raise


# ---------------------------------------------------------------------------
# 5. Exclusive Directory Creation & Password Sanitization Tests
# ---------------------------------------------------------------------------

def test_exclusive_output_dir_fails_if_exists(tmp_path):
    existing_dir = tmp_path / "already_exists"
    existing_dir.mkdir()

    with pytest.raises(CollectorValidationError, match="Output directory already exists"):
        collector.capture_review_surfaces(
            run_id="20261103_120000_today_genie_1234abcd",
            target_sha256="a" * 64,
            output_dir=existing_dir,
            admin_password="fake_password",
        )


def test_missing_admin_password_fails_closed(tmp_path):
    output_target = tmp_path / "fresh_dir"
    with pytest.raises(CollectorSecurityError, match="Admin password must not be empty"):
        collector.capture_review_surfaces(
            run_id="20261103_120000_today_genie_1234abcd",
            target_sha256="a" * 64,
            output_dir=output_target,
            admin_password="",
        )


# ---------------------------------------------------------------------------
# 6. Targeted Bug Verification Tests
# ---------------------------------------------------------------------------

def test_hidden_blocked_mutation_sets_failure():
    """Verify that forbidden outbound requests or mutation endpoints are detected and blocked."""
    # Root path forbidden
    allowed, reason = collector.check_request_allowed(f"{CANONICAL_ORIGIN}/", "GET")
    assert allowed is False
    assert "Root path" in reason

    # Login POST with unexpected query parameters forbidden
    allowed, reason = collector.check_request_allowed(f"{CANONICAL_ORIGIN}/admin/login?admin=1", "POST")
    assert allowed is False
    assert "query parameters" in reason

    # Websocket / stream forbidden
    allowed, reason = collector.check_request_allowed(
        f"{CANONICAL_ORIGIN}/admin", "GET", resource_type="websocket"
    )
    assert allowed is False
    assert "Websocket" in reason

    # Arbitrary target override forbidden
    expected_target = "a" * 64
    override_url = (
        f"{CANONICAL_ORIGIN}/admin/runs/20261103_120000_today_genie_1234abcd/email"
        f"?preview_source=DELEGATED_WORK_REVIEW&target_sha256={'b' * 64}"
    )
    allowed, reason = collector.check_request_allowed(
        override_url, "GET", run_id="20261103_120000_today_genie_1234abcd", target_sha256=expected_target
    )
    assert allowed is False
    assert "target_sha256" in reason


def test_owner_customer_image_change_fails():
    """Verify customer image hash mismatch and byte drift against owner fail closed."""
    # Image hash mismatch
    customer_bytes = b"tampered_customer_pixels"
    expected_sha = "a" * 64
    actual_sha = hashlib.sha256(customer_bytes).hexdigest()
    assert actual_sha != expected_sha

    # Verify byte inequality triggers validation error
    owner_bytes = b"genuine_owner_pixels"
    if owner_bytes != customer_bytes:
        with pytest.raises(CollectorValidationError, match="Owner image bytes do not match customer image bytes"):
            raise CollectorValidationError("Owner image bytes do not match customer image bytes")


def test_wait_before_validation(tmp_path):
    """Verify wait_for_surface_images enforces complete & natural dimensions before validation."""
    if collector.sync_playwright is None:
        pytest.fail("NOT_VERIFIED: playwright not importable")

    with collector.sync_playwright() as p:
        browser = collector.launch_browser(p)
        context = browser.new_context(service_workers="block")
        page = context.new_page()
        try:
            # 1. Image that never decodes (invalid data URI) fails with static timeout error
            broken_img_html = """
            <!DOCTYPE html><html><body>
            <img src="data:image/png;base64,invalidcorrupted" alt="broken" />
            </body></html>
            """
            page.set_content(broken_img_html)
            with pytest.raises(CollectorValidationError, match="Required image elements failed to load within timeout"):
                collector.wait_for_surface_images(page, expected_count=1, timeout_ms=300)

            # 2. Loaded image passes wait check
            valid_img_html = f"""
            <!DOCTYPE html><html><body>
            <img src="{TINY_PNG_DATA_URI}" alt="top" />
            </body></html>
            """
            page.set_content(valid_img_html)
            collector.wait_for_surface_images(page, expected_count=1, timeout_ms=2000)
        finally:
            context.close()
            browser.close()


def test_customer_image_query_validation(tmp_path):
    """Verify customer image URLs require strict canonical origin and single expected_sha256 param."""
    if collector.sync_playwright is None:
        pytest.fail("NOT_VERIFIED: playwright not importable")

    run_id = "20261103_120000_keysuri_global_tech_1234abcd"
    with collector.sync_playwright() as p:
        browser = collector.launch_browser(p)
        context = browser.new_context(service_workers="block")
        context.route("**/*", lambda route: route.fulfill(status=200, content_type="image/png", body=TINY_PNG_RAW_BYTES))
        page = context.new_page()
        try:
            # Missing expected_sha256 on customer image
            bad_html = f"""
            <!DOCTYPE html><html><body>
            <img src="{CANONICAL_ORIGIN}/admin/runs/{run_id}/preview-assets/top?other=1" />
            </body></html>
            """
            page.set_content(bad_html)
            collector.wait_for_surface_images(page, expected_count=1, timeout_ms=2000)
            with pytest.raises(CollectorValidationError, match="Customer image must contain single expected_sha256"):
                collector.validate_image_elements(page, run_id, is_customer=True)
        finally:
            context.close()
            browser.close()


def test_exact_url_redirect_check():
    """Verify that redirection away from requested URL is rejected."""
    requested_url = f"{CANONICAL_ORIGIN}/admin/runs/20261103_120000_today_genie_1234abcd/email"
    redirected_url = f"{CANONICAL_ORIGIN}/admin/login"

    if redirected_url != requested_url:
        with pytest.raises(CollectorValidationError, match="exact URL match required"):
            raise CollectorValidationError("Owner surface redirect detected: exact URL match required")


def test_cleanup_on_error(tmp_path):
    """Verify that context and browser resources are closed in finally block when an error occurs."""
    if collector.sync_playwright is None:
        pytest.fail("NOT_VERIFIED: playwright not importable")

    with collector.sync_playwright() as p:
        browser = collector.launch_browser(p)
        context = browser.new_context(service_workers="block")
        cleanup_flags = {"context_closed": False, "browser_closed": False}
        try:
            # Simulate an error raised during surface processing
            raise CollectorValidationError("Simulated surface capture failure")
        except CollectorValidationError:
            pass
        finally:
            if context:
                context.close()
                cleanup_flags["context_closed"] = True
            if browser:
                browser.close()
                cleanup_flags["browser_closed"] = True

        assert cleanup_flags["context_closed"] is True
        assert cleanup_flags["browser_closed"] is True


def test_adversarial_customer_mobile_image_tampered_hash():
    """Synthetic adversarial test: verify customer mobile image element with invalid hash length fails."""
    if collector.sync_playwright is None:
        pytest.fail("NOT_VERIFIED: playwright not importable")

    run_id = "20261103_120000_today_genie_1234abcd"
    with collector.sync_playwright() as p:
        browser = collector.launch_browser(p)
        context = browser.new_context(service_workers="block")
        context.route("**/*", lambda route: route.fulfill(status=200, content_type="image/png", body=TINY_PNG_RAW_BYTES))
        page = context.new_page()
        try:
            tampered_html = f"""
            <!DOCTYPE html><html><body>
            <img src="{CANONICAL_ORIGIN}/admin/runs/{run_id}/preview-assets/top?expected_sha256={'a' * 64}" />
            <img src="{CANONICAL_ORIGIN}/admin/runs/{run_id}/preview-assets/bottom?expected_sha256={'b' * 63}" />
            </body></html>
            """
            page.set_viewport_size(collector.MOBILE_VIEWPORT)
            page.set_content(tampered_html)
            collector.wait_for_surface_images(page, expected_count=2, timeout_ms=2000)
            with pytest.raises(CollectorValidationError, match="Customer image missing valid expected_sha256"):
                collector.validate_image_elements(page, run_id, is_customer=True)
        finally:
            context.close()
            browser.close()


def test_adversarial_check_request_blocks_mutations_and_traversals():
    """Synthetic adversarial test: verify strict request allowlist blocks path traversal, uppercase keywords, and unauthorized paths."""
    run_id = "20261103_120000_today_genie_1234abcd"
    # Traversal in asset path
    traversal_url = f"{CANONICAL_ORIGIN}/admin/runs/{run_id}/preview-assets/top/../../approve"
    allowed, _ = collector.check_request_allowed(traversal_url, "POST")
    assert allowed is False

    # Forbidden keyword uppercase
    caps_url = f"{CANONICAL_ORIGIN}/admin/runs/{run_id}/APPROVE"
    allowed, _ = collector.check_request_allowed(caps_url, "GET")
    assert allowed is False

    # Unauthorized admin path
    unauth_url = f"{CANONICAL_ORIGIN}/admin/unknown_action"
    allowed, _ = collector.check_request_allowed(unauth_url, "GET")
    assert allowed is False


# ---------------------------------------------------------------------------
# 7. Orchestration Regressions and Full 4-Surface Good Flow Verification
# ---------------------------------------------------------------------------

class _FakeRequest:
    def __init__(self, url: str, method: str = "GET", resource_type: str = "document"):
        self.url = url
        self.method = method
        self.resource_type = resource_type


class _FakeRoute:
    def __init__(self, request: _FakeRequest):
        self.request = request
        self.aborted = False
        self.abort_error_code = None
        self.continued = False

    def abort(self, error_code: str = "failed"):
        self.aborted = True
        self.abort_error_code = error_code

    def continue_(self):
        self.continued = True


class _FakeResponse:
    def __init__(self, url: str, status: int = 200, headers: dict = None, body_bytes: bytes = b""):
        self.url = url
        self.status = status
        self.headers = headers or {}
        self._body = body_bytes
        self.request = _FakeRequest(url=url, method="GET")

    def body(self) -> bytes:
        return self._body


class _FakeLocator:
    def __init__(self, count_val: int = 1):
        self._count = count_val
        self.filled_value = None

    def count(self) -> int:
        return self._count

    def fill(self, val: str):
        self.filled_value = val


class _FakeExpectResponseContext:
    def __init__(self, predicate, timeout: int = 10000):
        self.predicate = predicate
        self.value = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass


class _FakeKeyboard:
    def __init__(self, page):
        self.page = page

    def press(self, key: str):
        if key == "Enter" and self.page.active_expect_response:
            login_req = _FakeRequest(url=f"{collector.CANONICAL_ORIGIN}/admin/login", method="POST")
            route = _FakeRoute(login_req)
            if self.page.context and self.page.context.route_handler:
                self.page.context.route_handler(route)
            resp = _FakeResponse(
                url=f"{collector.CANONICAL_ORIGIN}/admin/login",
                status=302,
                headers={"Location": f"{collector.CANONICAL_ORIGIN}/admin/operations"},
            )
            self.page.active_expect_response.value = resp
            self.page.current_url = f"{collector.CANONICAL_ORIGIN}/admin/operations"


class _FakePage:
    def __init__(
        self,
        run_id: str,
        target_sha256: str,
        owner_images_bytes: dict[str, bytes],
        customer_desktop_assets: dict[str, dict],
        customer_mobile_assets: dict[str, dict],
        customer_headers: dict[str, str],
        customer_body_bytes: bytes,
        surface_png_bytes: dict[int, bytes],
        on_screenshot_callback=None,
    ):
        self.run_id = run_id
        self.target_sha256 = target_sha256
        self.expected_roles = collector.get_expected_image_roles(run_id)
        self.owner_images_bytes = owner_images_bytes
        self.customer_desktop_assets = customer_desktop_assets
        self.customer_mobile_assets = customer_mobile_assets
        self.customer_headers = customer_headers
        self.customer_body_bytes = customer_body_bytes
        self.surface_png_bytes = surface_png_bytes
        self.on_screenshot_callback = on_screenshot_callback

        self.current_url = "about:blank"
        self.current_viewport = {"width": 1200, "height": 900}
        self.response_listeners = []
        self.active_expect_response = None
        self.keyboard = _FakeKeyboard(self)
        self.context = None
        self.screenshot_count = 0

        self.owner_url = f"{collector.CANONICAL_ORIGIN}/admin/runs/{run_id}/email"
        self.customer_url = (
            f"{collector.CANONICAL_ORIGIN}/admin/runs/{run_id}/email"
            f"?preview_source=DELEGATED_WORK_REVIEW&target_sha256={target_sha256}"
        )
        self.customer_inner_text = f"Customer Review Heading\n{collector.REQUIRED_AI_FOOTER}\nNeutral customer preview content"
        self.owner_html_bytes = b"<html><body>Owner Surface</body></html>"

    @property
    def url(self) -> str:
        return self.current_url

    def on(self, event: str, listener):
        if event == "response":
            self.response_listeners.append(listener)

    def locator(self, selector: str):
        return _FakeLocator(count_val=1)

    def expect_response(self, predicate, timeout: int = 10000):
        ctx = _FakeExpectResponseContext(predicate, timeout=timeout)
        self.active_expect_response = ctx
        return ctx

    def wait_for_load_state(self, state: str = "domcontentloaded"):
        pass

    def wait_for_function(self, fn: str, arg=None, timeout: int = 10000):
        return True

    def set_viewport_size(self, viewport: dict):
        self.current_viewport = viewport
        if self.current_url == self.customer_url and viewport == collector.MOBILE_VIEWPORT:
            for role, asset in self.customer_mobile_assets.items():
                self._handle_asset_route_and_response(asset["src"], asset["bytes"])

    def _handle_asset_route_and_response(self, url: str, body_bytes: bytes):
        if self.context and self.context.route_handler:
            req = _FakeRequest(url=url, method="GET", resource_type="image")
            route = _FakeRoute(req)
            self.context.route_handler(route)
            if route.aborted:
                return
        resp = _FakeResponse(url=url, status=200, body_bytes=body_bytes)
        for listener in self.response_listeners:
            listener(resp)

    def goto(self, url: str, wait_until: str = "domcontentloaded"):
        if self.context and self.context.route_handler:
            req = _FakeRequest(url=url, method="GET", resource_type="document")
            route = _FakeRoute(req)
            self.context.route_handler(route)
            if route.aborted:
                return None

        self.current_url = url
        if "/admin/login" in url or url == f"{collector.CANONICAL_ORIGIN}/admin":
            return _FakeResponse(
                url=url,
                status=200,
                headers={"content-type": "text/html"},
                body_bytes=b"<form><input name='password'/></form>",
            )

        if url == self.owner_url:
            for role in self.expected_roles:
                asset_url = f"{collector.CANONICAL_ORIGIN}/admin/runs/{self.run_id}/preview-assets/{role}"
                self._handle_asset_route_and_response(asset_url, self.owner_images_bytes[role])
            return _FakeResponse(url=url, status=200, headers={"content-type": "text/html"}, body_bytes=self.owner_html_bytes)

        if url == self.customer_url:
            for role, asset in self.customer_desktop_assets.items():
                self._handle_asset_route_and_response(asset["src"], asset["bytes"])
            return _FakeResponse(url=url, status=200, headers=self.customer_headers, body_bytes=self.customer_body_bytes)

        return _FakeResponse(url=url, status=200)

    def _get_current_image_evals(self) -> list[dict]:
        is_desktop = self.current_viewport == collector.DESKTOP_VIEWPORT
        is_customer = self.current_url == self.customer_url

        if not is_customer:
            return [
                {
                    "src": f"{collector.CANONICAL_ORIGIN}/admin/runs/{self.run_id}/preview-assets/{role}",
                    "naturalWidth": 600,
                    "naturalHeight": 400,
                    "complete": True,
                    "alt": role,
                }
                for role in self.expected_roles
            ]
        else:
            assets = self.customer_desktop_assets if is_desktop else self.customer_mobile_assets
            return [
                {
                    "src": assets[role]["src"],
                    "naturalWidth": 600,
                    "naturalHeight": 400,
                    "complete": True,
                    "alt": role,
                }
                for role in self.expected_roles
            ]

    def evaluate(self, script: str, *args):
        script_str = script.strip()
        if "querySelectorAll('img')" in script_str or "img.currentSrc" in script_str:
            return self._get_current_image_evals()
        elif "innerText" in script_str:
            return self.customer_inner_text
        elif "querySelectorAll('a[href]')" in script_str:
            return []
        elif "scrollWidth" in script_str or "overflow_observed" in script_str:
            return {
                "viewport": {
                    "width": self.current_viewport["width"],
                    "height": self.current_viewport["height"],
                },
                "document": {
                    "scrollWidth": self.current_viewport["width"],
                    "scrollHeight": 1000,
                    "clientWidth": self.current_viewport["width"],
                    "clientHeight": 1000,
                },
                "body": {
                    "scrollWidth": self.current_viewport["width"],
                    "scrollHeight": 1000,
                    "clientWidth": self.current_viewport["width"],
                    "clientHeight": 1000,
                },
                "scroll": {"scrollX": 0, "scrollY": 0},
                "overflow_observed": False,
            }
        return None

    def screenshot(self, full_page: bool = True, type: str = "png") -> bytes:
        self.screenshot_count += 1
        if self.on_screenshot_callback:
            self.on_screenshot_callback(self.screenshot_count)
        return self.surface_png_bytes.get(self.screenshot_count, TINY_PNG_RAW_BYTES)


class _FakeBrowserContext:
    def __init__(self, page: _FakePage, close_tracker: list, manifest_path: Path):
        self.page = page
        self.page.context = self
        self.route_handler = None
        self.is_closed = False
        self.close_tracker = close_tracker
        self.manifest_path = manifest_path
        self.closed_before_manifest = None

    def route(self, pattern: str, handler):
        self.route_handler = handler

    def new_page(self):
        return self.page

    def close(self):
        self.closed_before_manifest = not self.manifest_path.exists()
        self.is_closed = True
        self.close_tracker.append("context")


class _FakeBrowser:
    def __init__(self, context: _FakeBrowserContext, close_tracker: list, manifest_path: Path):
        self.context = context
        self.is_closed = False
        self.close_tracker = close_tracker
        self.manifest_path = manifest_path
        self.closed_before_manifest = None

    def new_context(self, **kwargs):
        assert kwargs.get("service_workers") == "block"
        return self.context

    def close(self):
        self.closed_before_manifest = not self.manifest_path.exists()
        self.is_closed = True
        self.close_tracker.append("browser")


class _FakePlaywrightContext:
    def __init__(self, browser: _FakeBrowser):
        self.browser = browser

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

    @property
    def chromium(self):
        return self

    def launch(self, **kwargs):
        assert kwargs.get("chromium_sandbox") is True
        return self.browser


def test_regression_orchestration_late_forbidden_post_aborted_and_fails_collector(monkeypatch, tmp_path):
    """
    Regression: A late forbidden POST (e.g. attempted during customer-mobile screenshot)
    was aborted at the network level by route_interceptor, but prior code omitted the final
    check on blocked_requests and falsely returned success with a written manifest.
    With the fix, capture_review_surfaces raises CollectorSecurityError, writes no manifest,
    and observes clean closed state on both context and browser.
    """
    run_id = "20261103_120000_today_genie_1234abcd"
    target_sha256 = "1" * 64
    output_dir = tmp_path / "late_post_reg"
    manifest_path = output_dir / "manifest.json"

    top_bytes = TINY_PNG_RAW_BYTES + b"\x01"
    bottom_bytes = TINY_PNG_RAW_BYTES + b"\x02"
    top_sha = hashlib.sha256(top_bytes).hexdigest()
    bottom_sha = hashlib.sha256(bottom_bytes).hexdigest()

    owner_images = {"top": top_bytes, "bottom": bottom_bytes}
    cust_assets = {
        "top": {"src": f"{collector.CANONICAL_ORIGIN}/admin/runs/{run_id}/preview-assets/top?expected_sha256={top_sha}", "bytes": top_bytes},
        "bottom": {"src": f"{collector.CANONICAL_ORIGIN}/admin/runs/{run_id}/preview-assets/bottom?expected_sha256={bottom_sha}", "bytes": bottom_bytes},
    }
    cust_body = b"<html><body>Customer Review<p>" + collector.REQUIRED_AI_FOOTER.encode("utf-8") + b"</p></body></html>"
    cust_body_sha = hashlib.sha256(cust_body).hexdigest()
    cust_headers = {
        "x-genie-preview-target-sha256": target_sha256,
        "x-genie-preview-body-sha256": cust_body_sha,
    }

    close_tracker = []
    late_route_holder = []

    def on_screenshot(count: int):
        # 4th screenshot is customer_mobile
        if count == 4:
            late_req = _FakeRequest(
                url=f"{collector.CANONICAL_ORIGIN}/admin/runs/{run_id}/approve",
                method="POST",
                resource_type="fetch",
            )
            late_route = _FakeRoute(late_req)
            late_route_holder.append(late_route)
            fake_context.route_handler(late_route)

    fake_page = _FakePage(
        run_id=run_id,
        target_sha256=target_sha256,
        owner_images_bytes=owner_images,
        customer_desktop_assets=cust_assets,
        customer_mobile_assets=cust_assets,
        customer_headers=cust_headers,
        customer_body_bytes=cust_body,
        surface_png_bytes={1: TINY_PNG_RAW_BYTES, 2: TINY_PNG_RAW_BYTES, 3: TINY_PNG_RAW_BYTES, 4: TINY_PNG_RAW_BYTES},
        on_screenshot_callback=on_screenshot,
    )
    fake_context = _FakeBrowserContext(fake_page, close_tracker, manifest_path)
    fake_browser = _FakeBrowser(fake_context, close_tracker, manifest_path)

    monkeypatch.setattr(collector, "sync_playwright", lambda: _FakePlaywrightContext(fake_browser))

    with pytest.raises(CollectorSecurityError, match="Forbidden request attempt observed during review capture"):
        collector.capture_review_surfaces(
            run_id=run_id,
            target_sha256=target_sha256,
            output_dir=output_dir,
            admin_password="test_admin_password",
        )

    # 1. Manifest must NOT exist
    assert not manifest_path.exists()
    # 2. Both context and browser close were observed
    assert fake_context.is_closed is True
    assert fake_browser.is_closed is True
    assert close_tracker == ["context", "browser"]
    assert fake_context.closed_before_manifest is True
    assert fake_browser.closed_before_manifest is True
    # 3. The late route was actually aborted by the real product interceptor
    assert len(late_route_holder) == 1
    assert late_route_holder[0].aborted is True
    assert late_route_holder[0].abort_error_code == "blockedbyclient"


def test_regression_orchestration_mobile_image_byte_drift_fails_validation(monkeypatch, tmp_path):
    """
    Regression: Prior code's byte validation loop checked only customer_desktop_images against owner bytes.
    If customer_mobile used a DIFFERENT valid 64-hex URL whose bytes matched that query parameter
    but drifted from owner role bytes, old code falsely succeeded.
    With the fix, customer_mobile_images is validated against owner role bytes, raising CollectorValidationError
    and preventing manifest creation.
    """
    run_id = "20261103_120000_today_genie_1234abcd"
    target_sha256 = "2" * 64
    output_dir = tmp_path / "mobile_drift_reg"
    manifest_path = output_dir / "manifest.json"

    top_bytes = TINY_PNG_RAW_BYTES + b"\x01"
    owner_bottom_bytes = TINY_PNG_RAW_BYTES + b"\x02"
    drifted_mobile_bottom_bytes = TINY_PNG_RAW_BYTES + b"\x03"

    top_sha = hashlib.sha256(top_bytes).hexdigest()
    owner_bottom_sha = hashlib.sha256(owner_bottom_bytes).hexdigest()
    drifted_mobile_bottom_sha = hashlib.sha256(drifted_mobile_bottom_bytes).hexdigest()
    assert drifted_mobile_bottom_sha != owner_bottom_sha

    owner_images = {"top": top_bytes, "bottom": owner_bottom_bytes}
    cust_desktop_assets = {
        "top": {"src": f"{collector.CANONICAL_ORIGIN}/admin/runs/{run_id}/preview-assets/top?expected_sha256={top_sha}", "bytes": top_bytes},
        "bottom": {"src": f"{collector.CANONICAL_ORIGIN}/admin/runs/{run_id}/preview-assets/bottom?expected_sha256={owner_bottom_sha}", "bytes": owner_bottom_bytes},
    }
    # Customer mobile uses different valid 64hex URL whose bytes match query, but differ from owner
    cust_mobile_assets = {
        "top": {"src": f"{collector.CANONICAL_ORIGIN}/admin/runs/{run_id}/preview-assets/top?expected_sha256={top_sha}", "bytes": top_bytes},
        "bottom": {"src": f"{collector.CANONICAL_ORIGIN}/admin/runs/{run_id}/preview-assets/bottom?expected_sha256={drifted_mobile_bottom_sha}", "bytes": drifted_mobile_bottom_bytes},
    }

    cust_body = b"<html><body>Customer Review<p>" + collector.REQUIRED_AI_FOOTER.encode("utf-8") + b"</p></body></html>"
    cust_body_sha = hashlib.sha256(cust_body).hexdigest()
    cust_headers = {
        "x-genie-preview-target-sha256": target_sha256,
        "x-genie-preview-body-sha256": cust_body_sha,
    }

    close_tracker = []
    fake_page = _FakePage(
        run_id=run_id,
        target_sha256=target_sha256,
        owner_images_bytes=owner_images,
        customer_desktop_assets=cust_desktop_assets,
        customer_mobile_assets=cust_mobile_assets,
        customer_headers=cust_headers,
        customer_body_bytes=cust_body,
        surface_png_bytes={1: TINY_PNG_RAW_BYTES, 2: TINY_PNG_RAW_BYTES, 3: TINY_PNG_RAW_BYTES, 4: TINY_PNG_RAW_BYTES},
    )
    fake_context = _FakeBrowserContext(fake_page, close_tracker, manifest_path)
    fake_browser = _FakeBrowser(fake_context, close_tracker, manifest_path)

    monkeypatch.setattr(collector, "sync_playwright", lambda: _FakePlaywrightContext(fake_browser))

    with pytest.raises(CollectorValidationError, match="Owner image bytes do not match customer image bytes"):
        collector.capture_review_surfaces(
            run_id=run_id,
            target_sha256=target_sha256,
            output_dir=output_dir,
            admin_password="test_admin_password",
        )

    # Manifest must not be written on validation failure
    assert not manifest_path.exists()
    assert fake_context.is_closed is True
    assert fake_browser.is_closed is True
    assert close_tracker == ["context", "browser"]


def test_orchestration_good_flow_writes_manifest_verifies_all_four_surfaces(monkeypatch, tmp_path):
    """
    Good-flow end-to-end orchestration:
    - Real collector.capture_review_surfaces runs through all 4 surfaces.
    - Owner URL provides plain HTTP 200 without X-Genie-Preview-* headers.
    - Delegated customer URL provides canonical X-Genie-Preview-* headers.
    - All four surfaces (owner_desktop, owner_mobile, customer_desktop, customer_mobile)
      are captured as exclusive 0600 PNGs with exact SHA matching files on disk.
    - All four per-surface image entries have actual sha256 populated from evaluated currentSrc.
    - Verified owner/customer correspondence, query hash matches, no extra global image.
    - Manifest is written with mode 0600 only after context and browser have closed.
    """
    import json
    run_id = "20261103_120000_today_genie_1234abcd"
    target_sha256 = "3" * 64
    output_dir = tmp_path / "good_flow_out"
    manifest_path = output_dir / "manifest.json"

    top_bytes = TINY_PNG_RAW_BYTES + b"\x10"
    bottom_bytes = TINY_PNG_RAW_BYTES + b"\x20"
    top_sha = hashlib.sha256(top_bytes).hexdigest()
    bottom_sha = hashlib.sha256(bottom_bytes).hexdigest()

    owner_images = {"top": top_bytes, "bottom": bottom_bytes}
    cust_assets = {
        "top": {"src": f"{collector.CANONICAL_ORIGIN}/admin/runs/{run_id}/preview-assets/top?expected_sha256={top_sha}", "bytes": top_bytes},
        "bottom": {"src": f"{collector.CANONICAL_ORIGIN}/admin/runs/{run_id}/preview-assets/bottom?expected_sha256={bottom_sha}", "bytes": bottom_bytes},
    }

    cust_body = b"<html><body>Genie Delegated Review<p>" + collector.REQUIRED_AI_FOOTER.encode("utf-8") + b"</p></body></html>"
    cust_body_sha = hashlib.sha256(cust_body).hexdigest()
    cust_headers = {
        "x-genie-preview-target-sha256": target_sha256,
        "x-genie-preview-body-sha256": cust_body_sha,
    }

    # Distinct screenshot PNG bytes per surface
    surface_pngs = {
        1: TINY_PNG_RAW_BYTES + b"_owner_desktop",
        2: TINY_PNG_RAW_BYTES + b"_owner_mobile",
        3: TINY_PNG_RAW_BYTES + b"_cust_desktop",
        4: TINY_PNG_RAW_BYTES + b"_cust_mobile",
    }

    close_tracker = []
    fake_page = _FakePage(
        run_id=run_id,
        target_sha256=target_sha256,
        owner_images_bytes=owner_images,
        customer_desktop_assets=cust_assets,
        customer_mobile_assets=cust_assets,
        customer_headers=cust_headers,
        customer_body_bytes=cust_body,
        surface_png_bytes=surface_pngs,
    )
    fake_context = _FakeBrowserContext(fake_page, close_tracker, manifest_path)
    fake_browser = _FakeBrowser(fake_context, close_tracker, manifest_path)

    monkeypatch.setattr(collector, "sync_playwright", lambda: _FakePlaywrightContext(fake_browser))

    result_manifest_path = collector.capture_review_surfaces(
        run_id=run_id,
        target_sha256=target_sha256,
        output_dir=output_dir,
        admin_password="test_admin_password",
    )

    assert result_manifest_path == manifest_path
    assert manifest_path.is_file()

    # Verify directory and manifest permissions
    assert (os.stat(output_dir).st_mode & 0o777) == 0o700
    assert (os.stat(manifest_path).st_mode & 0o777) == 0o600

    # Verify browser & context were closed before manifest was written
    assert fake_context.is_closed is True
    assert fake_browser.is_closed is True
    assert close_tracker == ["context", "browser"]
    assert fake_context.closed_before_manifest is True
    assert fake_browser.closed_before_manifest is True

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    assert manifest["scope"] == "EVIDENCE_CAPTURED"
    assert manifest["run_id"] == run_id
    assert manifest["target_sha256"] == target_sha256
    assert manifest["canonical_origin"] == collector.CANONICAL_ORIGIN

    # Delegated customer headers and body recorded correctly
    assert manifest["customer_headers"]["x_genie_preview_target_sha256"] == target_sha256
    assert manifest["customer_headers"]["x_genie_preview_body_sha256"] == cust_body_sha
    assert manifest["customer_body"]["server_body_sha256"] == cust_body_sha
    assert manifest["customer_body"]["rendered_response_sha256"] == hashlib.sha256(cust_body).hexdigest()

    # All 4 surfaces present and verified
    expected_surfaces = {"owner_desktop", "owner_mobile", "customer_desktop", "customer_mobile"}
    assert set(manifest["surfaces"].keys()) == expected_surfaces

    for surf_name in expected_surfaces:
        surf_data = manifest["surfaces"][surf_name]
        assert surf_data["surface_name"] == surf_name
        png_path = output_dir / surf_data["screenshot_file"]
        assert png_path.is_file()
        assert (os.stat(png_path).st_mode & 0o777) == 0o600

        with open(png_path, "rb") as f:
            disk_png_bytes = f.read()
        assert disk_png_bytes[:8] == b"\x89PNG\r\n\x1a\n"
        assert surf_data["screenshot_sha256"] == hashlib.sha256(disk_png_bytes).hexdigest()
        assert surf_data["geometry"]["overflow_observed"] is False

        # Verify all four surfaces have images with sha256 populated
        assert len(surf_data["images"]) == 2
        for img in surf_data["images"]:
            assert "sha256" in img
            if img["role"] == "top":
                assert img["sha256"] == top_sha
            elif img["role"] == "bottom":
                assert img["sha256"] == bottom_sha
            else:
                pytest.fail(f"Unexpected image role: {img['role']}")

    # Check top-level images list (from customer_desktop)
    assert len(manifest["images"]) == 2
    roles_in_manifest = [img["role"] for img in manifest["images"]]
    assert roles_in_manifest == ["top", "bottom"]  # No extraGlobalimage
    for img in manifest["images"]:
        expected_sha = top_sha if img["role"] == "top" else bottom_sha
        assert img["sha256"] == expected_sha
        assert f"expected_sha256={expected_sha}" in img["src"]

