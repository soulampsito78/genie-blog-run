#!/usr/bin/env python3
from __future__ import annotations

"""
scripts/capture_review_surfaces_headless.py

Small read-only authenticated headless-browser evidence collector for genie-blog-run review surfaces.
Captures owner and canonical customer preview surfaces (desktop 1200x900 and mobile 375x667)
and generates a private, create-exclusive evidence manifest and full-page PNG screenshots.
"""

import argparse
import datetime
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Optional, List, Dict, Tuple
from urllib.parse import parse_qs, urlparse

try:
    from playwright.sync_api import sync_playwright, Browser, BrowserContext, Page, Response
except ImportError:
    sync_playwright = None
    Browser = None
    BrowserContext = None
    Page = None
    Response = None

CANONICAL_ORIGIN = "https://genie-blog-run-1055014091206.asia-northeast3.run.app"
RUN_ID_REGEX = re.compile(
    r"^[0-9]{8}_[0-9]{6}_(today_genie|keysuri_global_tech|keysuri_korea_tech)_[a-f0-9]{8}$"
)
TARGET_SHA256_REGEX = re.compile(r"^[0-9a-f]{64}$")
SHA256_HEX_REGEX = re.compile(r"^[0-9a-f]{64}$")
REQUIRED_AI_FOOTER = "본 브리핑은 운영책임자가 정한 정책에 따른 독립적인 AI 검토를 통과했습니다."

FORBIDDEN_URL_KEYWORDS = (
    "generate",
    "reissue",
    "approve",
    "approval",
    "register",
    "registration",
    "signature",
    "send",
)

DIRECT_HUMAN_WAITING_TERMS = (
    "승인 대기",
    "대기 중",
    "대기중",
    "waiting for approval",
    "human waiting",
    "pending human",
    "direct-human-waiting",
)

DESKTOP_VIEWPORT = {"width": 1200, "height": 900}
MOBILE_VIEWPORT = {"width": 375, "height": 667}


class CollectorSecurityError(Exception):
    """Raised when a security guard or network policy is violated."""
    pass


class CollectorValidationError(Exception):
    """Raised when surface or payload validation fails."""
    pass


def launch_browser(playwright) -> "Browser":
    """Launch headless Chrome with standard sandbox using official installed Chrome."""
    try:
        return playwright.chromium.launch(
            headless=True,
            channel="chrome",
            chromium_sandbox=True,
        )
    except Exception:
        chrome_path = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
        if os.path.exists(chrome_path):
            return playwright.chromium.launch(
                headless=True,
                executable_path=chrome_path,
                chromium_sandbox=True,
            )
        raise


def validate_run_id(run_id: str) -> str:
    """Validate run ID against strict canonical run syntax."""
    if not isinstance(run_id, str) or not RUN_ID_REGEX.fullmatch(run_id):
        raise CollectorValidationError("Invalid run_id format")
    return run_id


def get_run_type(run_id: str) -> str:
    """Extract run type from validated run ID."""
    match = RUN_ID_REGEX.fullmatch(run_id)
    if not match:
        raise CollectorValidationError("Cannot extract run type from invalid run_id")
    return match.group(1)


def get_expected_image_roles(run_id: str) -> List[str]:
    """
    Return expected image roles by run type:
    - today_genie: 2 images (top, bottom)
    - keysuri_korea_tech: 2 images (top, bottom)
    - keysuri_global_tech: 1 image (top)
    """
    run_type = get_run_type(run_id)
    if run_type in ("today_genie", "keysuri_korea_tech"):
        return ["top", "bottom"]
    elif run_type == "keysuri_global_tech":
        return ["top"]
    raise CollectorValidationError("Unknown run type for image counts")


def validate_target_sha256(target_sha256: str) -> str:
    """Validate target SHA256 hex string strictly."""
    if not isinstance(target_sha256, str):
        raise CollectorValidationError("target_sha256 must be a string")
    lowered = target_sha256.lower().strip()
    if not TARGET_SHA256_REGEX.fullmatch(lowered):
        raise CollectorValidationError("Invalid target_sha256: must be 64-character lowercase hex string")
    return lowered


def check_request_allowed(
    url: str,
    method: str,
    resource_type: Optional[str] = None,
    allow_synthetic_data_urls: bool = False,
    run_id: Optional[str] = None,
    target_sha256: Optional[str] = None,
) -> Tuple[bool, str]:
    """
    Enforce strict read-only outbound network policy:
    - Deny every method other than GET/HEAD and exact POST to /admin/login on canonical origin.
    - Exact POST /admin/login must have empty query.
    - Block off-origin resources entirely.
    - Block service workers / websockets / mutation endpoints.
    - Read-only allowed URLs must be exact /admin, /admin/login, /admin/operations,
      exact this run/email and this run/preview-assets/top|bottom.
    - Disallow GET root and all other candidate/unsafe URLs.
    """
    method_upper = method.upper()

    if allow_synthetic_data_urls and url.startswith("data:image/"):
        if method_upper in ("GET", "HEAD"):
            return True, "Allowed synthetic data URI"
        return False, "Data URIs only permit GET/HEAD"

    if resource_type in ("websocket", "eventsource") or url.startswith("ws://") or url.startswith("wss://"):
        return False, "Websocket or stream protocol forbidden"

    parsed = urlparse(url)
    origin = f"{parsed.scheme}://{parsed.netloc}"

    if origin != CANONICAL_ORIGIN:
        return False, f"Off-origin request forbidden: '{origin}' != '{CANONICAL_ORIGIN}'"

    path_lower = parsed.path.lower()
    query_lower = parsed.query.lower()

    for kw in FORBIDDEN_URL_KEYWORDS:
        if kw in path_lower or kw in query_lower:
            return False, f"Forbidden endpoint keyword detected: '{kw}'"

    if method_upper == "POST":
        if parsed.path == "/admin/login":
            if parsed.query:
                return False, "Login POST must not contain query parameters"
            return True, "Allowed login POST"
        return False, f"POST forbidden for path '{parsed.path}'"

    if method_upper not in ("GET", "HEAD"):
        return False, f"HTTP method forbidden: '{method_upper}'"

    if parsed.path in ("", "/"):
        return False, "Root path request forbidden"

    if parsed.path in ("/admin", "/admin/login", "/admin/operations"):
        if parsed.query:
            return False, "Query parameters forbidden on admin utility paths"
        return True, "Allowed admin utility path"

    email_match = re.match(r"^/admin/runs/([^/]+)/email$", parsed.path)
    if email_match:
        matched_run_id = email_match.group(1)
        if not RUN_ID_REGEX.fullmatch(matched_run_id):
            return False, "Invalid run_id in email path"
        if run_id is not None and matched_run_id != run_id:
            return False, "Mismatched run_id in email path"

        if not parsed.query:
            return True, "Allowed owner email path"
        else:
            q = parse_qs(parsed.query, keep_blank_values=True)
            if set(q.keys()) != {"preview_source", "target_sha256"}:
                return False, "Invalid query parameters on customer email path"
            if q.get("preview_source") != ["DELEGATED_WORK_REVIEW"]:
                return False, "Invalid preview_source parameter"
            targets = q.get("target_sha256", [])
            if len(targets) != 1 or not TARGET_SHA256_REGEX.fullmatch(targets[0].lower()):
                return False, "Invalid target_sha256 parameter"
            if target_sha256 is not None and targets[0].lower() != target_sha256.lower():
                return False, "target_sha256 query parameter mismatch"
            return True, "Allowed customer email path"

    asset_match = re.match(r"^/admin/runs/([^/]+)/preview-assets/(top|bottom)$", parsed.path)
    if asset_match:
        matched_run_id = asset_match.group(1)
        matched_role = asset_match.group(2)
        if not RUN_ID_REGEX.fullmatch(matched_run_id):
            return False, "Invalid run_id in asset path"
        if run_id is not None and matched_run_id != run_id:
            return False, "Mismatched run_id in asset path"
        if run_id is not None:
            expected_roles = get_expected_image_roles(run_id)
            if matched_role not in expected_roles:
                return False, "Unexpected image role for run"

        if not parsed.query:
            return True, "Allowed owner preview asset path"
        else:
            q = parse_qs(parsed.query, keep_blank_values=True)
            if list(q.keys()) != ["expected_sha256"]:
                return False, "Customer preview asset query must only contain expected_sha256"
            shas = q.get("expected_sha256", [])
            if len(shas) != 1 or not SHA256_HEX_REGEX.fullmatch(shas[0].lower()):
                return False, "Invalid expected_sha256 parameter"
            return True, "Allowed customer preview asset path"

    return False, f"Path not in read-only allowlist: '{parsed.path}'"


def extract_surface_geometry(page: "Page") -> Dict:
    """Extract actual DOM viewport, document, and scroll geometry non-destructively."""
    js_script = """
    () => {
        const doc = document.documentElement;
        const body = document.body;
        const viewportWidth = window.innerWidth || 0;
        const viewportHeight = window.innerHeight || 0;
        const docScrollWidth = doc ? doc.scrollWidth : 0;
        const docScrollHeight = doc ? doc.scrollHeight : 0;
        const docClientWidth = doc ? doc.clientWidth : 0;
        const docClientHeight = doc ? doc.clientHeight : 0;

        return {
            viewport: {
                width: viewportWidth,
                height: viewportHeight
            },
            document: {
                scrollWidth: docScrollWidth,
                scrollHeight: docScrollHeight,
                clientWidth: docClientWidth,
                clientHeight: docClientHeight
            },
            body: {
                scrollWidth: body ? body.scrollWidth : 0,
                scrollHeight: body ? body.scrollHeight : 0,
                clientWidth: body ? body.clientWidth : 0,
                clientHeight: body ? body.clientHeight : 0
            },
            scroll: {
                scrollX: window.scrollX || window.pageXOffset || 0,
                scrollY: window.scrollY || window.pageYOffset || 0
            },
            overflow_observed: docScrollWidth > viewportWidth
        };
    }
    """
    return page.evaluate(js_script)


def validate_customer_dom(page: "Page") -> None:
    """
    Verify canonical customer page constraints:
    - Must include existing AI-review footer exact text.
    - Must have NO owner admin links (/admin/...).
    - Must have NO direct-human-waiting copy.
    """
    text_content = page.evaluate("() => document.body ? document.body.innerText : ''")
    if REQUIRED_AI_FOOTER not in text_content:
        raise CollectorValidationError(
            "Customer surface missing required AI review footer: "
            f"'{REQUIRED_AI_FOOTER}'"
        )

    for term in DIRECT_HUMAN_WAITING_TERMS:
        if term in text_content:
            raise CollectorValidationError(
                f"Customer surface contains prohibited direct-human-waiting copy: '{term}'"
            )

    links: List[str] = page.evaluate(
        """() => Array.from(document.querySelectorAll('a[href]')).map(a => a.getAttribute('href') || '')"""
    )
    for href in links:
        href_lower = href.lower().strip()
        if href_lower.startswith("/admin") or href_lower.startswith(f"{CANONICAL_ORIGIN.lower()}/admin"):
            raise CollectorValidationError(
                f"Customer surface contains prohibited owner admin link: '{href}'"
            )


def wait_for_surface_images(page: "Page", expected_count: int, timeout_ms: int = 10000) -> None:
    """Wait for all required images to complete loading with natural dimensions > 0."""
    try:
        page.wait_for_function(
            """(expected) => {
                const imgs = Array.from(document.querySelectorAll('img'));
                if (imgs.length !== expected) return false;
                return imgs.every(img => img.complete && img.naturalWidth > 0 && img.naturalHeight > 0);
            }""",
            arg=expected_count,
            timeout=timeout_ms,
        )
    except Exception:
        raise CollectorValidationError("Required image elements failed to load within timeout")


def validate_image_elements(
    page: "Page",
    run_id: str,
    is_customer: bool = False,
    allow_synthetic: bool = False,
) -> List[Dict]:
    """
    Validate loaded images on page:
    - Natural size must be loaded (naturalWidth > 0, naturalHeight > 0).
    - Image must be complete (complete === true).
    - Roles must match expected run type roles without duplicate or missing.
    - Customer image URLs must have strict canonical origin and single expected_sha256 param.
    """
    expected_roles = get_expected_image_roles(run_id)

    images_data: List[Dict] = page.evaluate(
        """() => {
            const imgs = Array.from(document.querySelectorAll('img'));
            return imgs.map(img => ({
                src: img.currentSrc || img.src || img.getAttribute('src') || '',
                naturalWidth: img.naturalWidth,
                naturalHeight: img.naturalHeight,
                complete: img.complete,
                alt: img.alt || ''
            }));
        }"""
    )

    if len(images_data) != len(expected_roles):
        raise CollectorValidationError(
            f"Expected {len(expected_roles)} image(s) for run, found {len(images_data)}"
        )

    validated_images: List[Dict] = []
    found_roles: set[str] = set()

    for idx, img in enumerate(images_data):
        src = img.get("src", "")
        nat_w = img.get("naturalWidth", 0)
        nat_h = img.get("naturalHeight", 0)
        complete = img.get("complete", False)

        if not complete or nat_w <= 0 or nat_h <= 0:
            raise CollectorValidationError("Image is not fully loaded")

        role = None
        if allow_synthetic and src.startswith("data:image/"):
            if idx < len(expected_roles):
                role = expected_roles[idx]
        else:
            parsed_src = urlparse(src)
            origin = f"{parsed_src.scheme}://{parsed_src.netloc}"
            if origin != CANONICAL_ORIGIN:
                raise CollectorValidationError("Image origin is not canonical origin")

            path_pattern = rf"^/admin/runs/{re.escape(run_id)}/preview-assets/(top|bottom)$"
            match = re.match(path_pattern, parsed_src.path)
            if not match:
                raise CollectorValidationError("Image src does not match preview-assets pattern")
            role = match.group(1)

            if is_customer:
                q = parse_qs(parsed_src.query, keep_blank_values=True)
                if list(q.keys()) != ["expected_sha256"]:
                    raise CollectorValidationError("Customer image must contain single expected_sha256 parameter")
                expected_sha = q.get("expected_sha256", [""])[0]
                if not SHA256_HEX_REGEX.fullmatch(expected_sha):
                    raise CollectorValidationError("Customer image missing valid expected_sha256 query param")
            else:
                if parsed_src.query:
                    raise CollectorValidationError("Owner image URL must not have query parameters")

        if role not in expected_roles:
            raise CollectorValidationError("Unexpected image role for run")

        if role in found_roles:
            raise CollectorValidationError("Duplicate image role observed")

        found_roles.add(role)
        validated_images.append({
            "role": role,
            "src": src,
            "natural_width": nat_w,
            "natural_height": nat_h,
            "complete": complete,
        })

    if set(expected_roles) != found_roles:
        raise CollectorValidationError("Missing required image roles")

    return validated_images


def capture_surface(
    page: "Page",
    output_dir: Path,
    surface_name: str,
    viewport: Dict,
    images: Optional[List[Dict]] = None,
    wait_for_images: bool = True,
) -> Dict:
    """
    Configure viewport, extract geometry, capture fullpage PNG screenshot with exclusive mode 0600.
    """
    page.set_viewport_size(viewport)

    if wait_for_images:
        page.wait_for_function(
            """() => {
                const imgs = Array.from(document.querySelectorAll('img'));
                return imgs.every(img => img.complete && img.naturalWidth > 0 && img.naturalHeight > 0);
            }""",
            timeout=10000,
        )

    geometry = extract_surface_geometry(page)
    png_bytes = page.screenshot(full_page=True, type="png")
    screenshot_hash = hashlib.sha256(png_bytes).hexdigest()

    png_path = output_dir / f"{surface_name}.png"
    fd = os.open(png_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with open(fd, "wb") as f:
        f.write(png_bytes)

    return {
        "surface_name": surface_name,
        "page_url": page.url,
        "screenshot_file": f"{surface_name}.png",
        "screenshot_sha256": screenshot_hash,
        "geometry": geometry,
        "images": images or [],
        "captured_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }


def perform_login(page: "Page", admin_password: str) -> None:
    """
    Authenticate against canonical admin login route.
    GET /admin -> password input name=password -> POST /admin/login -> redirect to /admin/operations.
    """
    login_url = f"{CANONICAL_ORIGIN}/admin"
    response = page.goto(login_url, wait_until="domcontentloaded")
    if not response or response.status >= 400:
        raise CollectorSecurityError("Failed to load login page")

    password_input = page.locator('input[name="password"]')
    if password_input.count() == 0:
        raise CollectorSecurityError("Password input not found on login page")

    password_input.fill(admin_password)

    with page.expect_response(
        lambda r: r.url == f"{CANONICAL_ORIGIN}/admin/login" and r.request.method == "POST",
        timeout=10000,
    ) as login_resp_info:
        page.keyboard.press("Enter")

    login_resp = login_resp_info.value
    if login_resp.status not in (200, 302, 303, 307):
        raise CollectorSecurityError("Authentication failed: invalid login response status")

    page.wait_for_load_state("domcontentloaded")
    if "/admin/login" in page.url:
        raise CollectorSecurityError("Authentication rejected: redirected back to login")


def capture_review_surfaces(
    run_id: str,
    target_sha256: str,
    output_dir: Path,
    admin_password: str,
) -> Path:
    """
    Main orchestration routine for authenticated review surface capture.
    """
    validated_run_id = validate_run_id(run_id)
    validated_target = validate_target_sha256(target_sha256)

    if not admin_password:
        raise CollectorSecurityError("Admin password must not be empty")

    output_dir = Path(output_dir).resolve()
    try:
        os.makedirs(output_dir, mode=0o700, exist_ok=False)
        os.chmod(output_dir, 0o700)
    except FileExistsError:
        raise CollectorValidationError("Output directory already exists")

    if sync_playwright is None:
        raise CollectorSecurityError("playwright is not installed or importable")

    manifest_path = output_dir / "manifest.json"
    expected_image_roles = get_expected_image_roles(validated_run_id)
    expected_image_count = len(expected_image_roles)

    response_bytes_by_url: Dict[str, bytes] = {}
    response_errors: List[str] = []
    blocked_requests: List[Dict] = []

    customer_headers_recorded: Dict[str, str] = {}
    manifest_data: Dict = {
        "scope": "EVIDENCE_CAPTURED",
        "run_id": validated_run_id,
        "target_sha256": validated_target,
        "canonical_origin": CANONICAL_ORIGIN,
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "surfaces": {},
        "customer_headers": {},
        "customer_body": {},
        "images": [],
        "security": {
            "authenticated_state_persisted": False,
            "isolated_overflow_observed": False,
        },
    }

    with sync_playwright() as playwright:
        browser: Optional["Browser"] = None
        context: Optional["BrowserContext"] = None
        try:
            browser = launch_browser(playwright)
            context = browser.new_context(service_workers="block")

            def route_interceptor(route):
                req = route.request
                allowed, reason = check_request_allowed(
                    url=req.url,
                    method=req.method,
                    resource_type=req.resource_type,
                    allow_synthetic_data_urls=False,
                    run_id=validated_run_id,
                    target_sha256=validated_target,
                )
                if not allowed:
                    blocked_requests.append({
                        "url": req.url,
                        "method": req.method,
                        "reason": reason,
                    })
                    route.abort("blockedbyclient")
                    return
                route.continue_()

            context.route("**/*", route_interceptor)
            page = context.new_page()

            def on_response(response: Response):
                url = response.url
                if "/preview-assets/" in url:
                    if response.status != 200:
                        response_errors.append("Non-200 status for image asset")
                        return
                    try:
                        body = response.body()
                        if url in response_bytes_by_url and response_bytes_by_url[url] != body:
                            response_errors.append("Conflicting response bytes received for image URL")
                            return
                        response_bytes_by_url[url] = body
                    except Exception:
                        response_errors.append("Failed to read image asset response body")

            page.on("response", on_response)

            perform_login(page, admin_password)
            if blocked_requests:
                raise CollectorSecurityError("Forbidden request attempt observed during authentication")

            owner_url = f"{CANONICAL_ORIGIN}/admin/runs/{validated_run_id}/email"
            customer_url = (
                f"{CANONICAL_ORIGIN}/admin/runs/{validated_run_id}/email"
                f"?preview_source=DELEGATED_WORK_REVIEW&target_sha256={validated_target}"
            )

            # Owner surfaces
            resp = page.goto(owner_url, wait_until="domcontentloaded")
            if blocked_requests:
                raise CollectorSecurityError("Forbidden request attempt observed during owner navigation")
            if not resp or resp.status != 200:
                raise CollectorValidationError("Failed to load owner review surface")
            if resp.url != owner_url or page.url != owner_url:
                raise CollectorValidationError("Owner surface redirect detected: exact URL match required")

            # Owner desktop
            page.set_viewport_size(DESKTOP_VIEWPORT)
            wait_for_surface_images(page, expected_image_count)
            owner_desktop_images = validate_image_elements(page, validated_run_id, is_customer=False)
            manifest_data["surfaces"]["owner_desktop"] = capture_surface(
                page, output_dir, "owner_desktop", DESKTOP_VIEWPORT, images=owner_desktop_images, wait_for_images=False
            )

            # Owner mobile
            page.set_viewport_size(MOBILE_VIEWPORT)
            wait_for_surface_images(page, expected_image_count)
            owner_mobile_images = validate_image_elements(page, validated_run_id, is_customer=False)
            manifest_data["surfaces"]["owner_mobile"] = capture_surface(
                page, output_dir, "owner_mobile", MOBILE_VIEWPORT, images=owner_mobile_images, wait_for_images=False
            )

            # Record owner image bytes by URL
            owner_image_bytes: Dict[str, bytes] = {}
            for role in expected_image_roles:
                img_url = f"{CANONICAL_ORIGIN}/admin/runs/{validated_run_id}/preview-assets/{role}"
                b = response_bytes_by_url.get(img_url)
                if not b:
                    raise CollectorValidationError("Failed to capture owner image response bytes")
                owner_image_bytes[role] = b

            # Customer surfaces
            resp_cust = page.goto(customer_url, wait_until="domcontentloaded")
            if blocked_requests:
                raise CollectorSecurityError("Forbidden request attempt observed during customer navigation")
            if not resp_cust or resp_cust.status != 200:
                raise CollectorValidationError("Failed to load customer review surface")
            if resp_cust.url != customer_url or page.url != customer_url:
                raise CollectorValidationError("Customer surface redirect detected: exact URL match required")

            headers_lower = {k.lower(): v for k, v in resp_cust.headers.items()}
            target_hdr = headers_lower.get("x-genie-preview-target-sha256", "").strip()
            body_hdr = headers_lower.get("x-genie-preview-body-sha256", "").strip()

            if target_hdr.lower() != validated_target:
                raise CollectorValidationError("Customer response X-Genie-Preview-Target-SHA256 header mismatch")
            if not SHA256_HEX_REGEX.fullmatch(body_hdr.lower()):
                raise CollectorValidationError("Customer response X-Genie-Preview-Body-SHA256 header invalid")

            customer_headers_recorded["x_genie_preview_target_sha256"] = target_hdr.lower()
            customer_headers_recorded["x_genie_preview_body_sha256"] = body_hdr.lower()
            manifest_data["customer_headers"] = customer_headers_recorded

            rendered_hash = hashlib.sha256(resp_cust.body()).hexdigest()
            manifest_data["customer_body"] = {
                "server_body_sha256": body_hdr.lower(),
                "rendered_response_sha256": rendered_hash,
            }

            validate_customer_dom(page)

            # Customer desktop
            page.set_viewport_size(DESKTOP_VIEWPORT)
            wait_for_surface_images(page, expected_image_count)
            customer_desktop_images = validate_image_elements(page, validated_run_id, is_customer=True)
            manifest_data["surfaces"]["customer_desktop"] = capture_surface(
                page, output_dir, "customer_desktop", DESKTOP_VIEWPORT, images=customer_desktop_images, wait_for_images=False
            )

            # Customer mobile
            page.set_viewport_size(MOBILE_VIEWPORT)
            wait_for_surface_images(page, expected_image_count)
            customer_mobile_images = validate_image_elements(page, validated_run_id, is_customer=True)
            manifest_data["surfaces"]["customer_mobile"] = capture_surface(
                page, output_dir, "customer_mobile", MOBILE_VIEWPORT, images=customer_mobile_images, wait_for_images=False
            )

            if response_errors:
                raise CollectorValidationError("Image response verification failed")

            # Validate each image against queryhash (customer) and owner role bytes (all)
            for image_list, is_customer in (
                (owner_desktop_images, False),
                (owner_mobile_images, False),
                (customer_desktop_images, True),
                (customer_mobile_images, True),
            ):
                for img_info in image_list:
                    role = img_info["role"]
                    src = img_info["src"]

                    actual_bytes = response_bytes_by_url.get(src)
                    if not actual_bytes:
                        raise CollectorValidationError("Failed to capture image response bytes")

                    actual_sha = hashlib.sha256(actual_bytes).hexdigest()
                    if is_customer:
                        q = parse_qs(urlparse(src).query, keep_blank_values=True)
                        expected_sha = q["expected_sha256"][0].lower()
                        if actual_sha != expected_sha:
                            raise CollectorValidationError("Customer image hash mismatch against query parameter")

                    owner_bytes = owner_image_bytes.get(role)
                    if not owner_bytes or owner_bytes != actual_bytes:
                        raise CollectorValidationError("Owner image bytes do not match customer image bytes")

                    img_info["sha256"] = actual_sha
                    if image_list is customer_desktop_images:
                        manifest_data["images"].append(img_info)

            overflow_seen = any(
                surf["geometry"].get("overflow_observed", False)
                for surf in manifest_data["surfaces"].values()
            )
            manifest_data["security"]["isolated_overflow_observed"] = overflow_seen

        finally:
            if context:
                try:
                    context.close()
                except Exception:
                    pass
            if browser:
                try:
                    browser.close()
                except Exception:
                    pass

    if blocked_requests:
        raise CollectorSecurityError("Forbidden request attempt observed during review capture")
    if response_errors:
        raise CollectorValidationError("Image response verification failed")

    fd = os.open(manifest_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with open(fd, "w", encoding="utf-8") as f:
        json.dump(manifest_data, f, indent=2, ensure_ascii=False)

    return manifest_path


def main() -> None:
    """CLI Entrypoint for headless review surface collector."""
    parser = argparse.ArgumentParser(
        description="Authenticated headless review evidence collector for genie-blog-run."
    )
    parser.add_argument("--run-id", required=True, help="Strict canonical run ID")
    parser.add_argument("--target-sha256", required=True, help="Strict 64-character lowercase hex target hash")
    parser.add_argument("--output-dir", required=True, help="Path for private create-exclusive artifacts")

    args = parser.parse_args()

    admin_password = os.environ.get("GENIE_ADMIN_PASSWORD")
    if not admin_password:
        sys.stderr.write("Error: GENIE_ADMIN_PASSWORD environment variable is required and must not be empty.\n")
        sys.exit(1)

    try:
        manifest_path = capture_review_surfaces(
            run_id=args.run_id,
            target_sha256=args.target_sha256,
            output_dir=Path(args.output_dir),
            admin_password=admin_password,
        )
        sys.stdout.write(f"Capture completed successfully. Manifest written to: {manifest_path}\n")
    except CollectorValidationError as exc:
        sys.stderr.write(f"Capture failed: VALIDATION_ERROR: {exc}\n")
        sys.exit(1)
    except CollectorSecurityError as exc:
        sys.stderr.write(f"Capture failed: SECURITY_ERROR: {exc}\n")
        sys.exit(1)
    except Exception:
        sys.stderr.write("Capture failed: BROWSER_OR_SYSTEM_ERROR\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
