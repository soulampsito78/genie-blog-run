#!/usr/bin/env python3
"""Visual review PDF: render today_genie email_body_html → screenshots → PDF."""
from __future__ import annotations

import io
import json
import tempfile
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from PIL import Image
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader

API_URL = "https://genie-blog-run-1055014091206.asia-northeast3.run.app/"
FONT_PATH = "/System/Library/Fonts/Supplemental/AppleGothic.ttf"
VIEWPORT_W = 600
FIRST_VIEWPORT_H = 900


def fetch_email_html() -> str:
    body = json.dumps({"type": "today_genie"}).encode("utf-8")
    req = urllib.request.Request(
        API_URL,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=180) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    if "detail" in data:
        raise RuntimeError(f"API error: {data.get('detail', {}).get('reason')}")
    html = (data.get("data") or {}).get("rendered_channels", {}).get("email_body_html") or ""
    if not html.strip():
        raise RuntimeError("empty email_body_html")
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"/>
<style>html,body{{margin:0;padding:0;background:#fff;}}</style>
</head><body>{html}</body></html>"""


def main() -> Path:
    kst = datetime.now(ZoneInfo("Asia/Seoul"))
    out = Path(__file__).resolve().parent.parent / f"genie_{kst.hour:02d}_{kst.minute:02d}_{kst.second:02d}.pdf"

    html = fetch_email_html()

    from playwright.sync_api import sync_playwright

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        first_png = td / "first.png"
        full_png = td / "full.png"
        admin_png = td / "admin.png"

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(
                viewport={"width": VIEWPORT_W, "height": FIRST_VIEWPORT_H},
                device_scale_factor=2,
            )
            page.set_content(html, wait_until="networkidle", timeout=120_000)
            page.screenshot(path=str(first_png), type="png")
            page.set_viewport_size({"width": VIEWPORT_W, "height": 720})
            page.screenshot(path=str(full_png), type="png", full_page=True)
            loc = page.locator("#genie-operational-handoff")
            loc.wait_for(state="visible", timeout=20_000)
            loc.scroll_into_view_if_needed()
            page.wait_for_timeout(300)
            loc.screenshot(path=str(admin_png), type="png")
            browser.close()

        pdfmetrics.registerFont(TTFont("KG", FONT_PATH))
        pw, ph = A4
        margin = 14 * mm
        img_w = pw - 2 * margin
        img_h_max = ph - 2 * margin

        c = canvas.Canvas(str(out), pagesize=A4)

        def draw_scaled(img: Image.Image, max_h: float) -> None:
            iw, ih = img.size
            scale = img_w / iw
            dh = ih * scale
            if dh > max_h:
                scale = max_h / ih
                dw = iw * scale
                dh = ih * scale
                x0 = margin + (img_w - dw) / 2
                resized = img.resize((max(1, int(dw)), max(1, int(dh))), Image.Resampling.LANCZOS)
            else:
                dw = iw * scale
                dh = ih * scale
                x0 = margin
                resized = img.resize((max(1, int(dw)), max(1, int(dh))), Image.Resampling.LANCZOS)
            buf = io.BytesIO()
            resized.save(buf, format="PNG")
            buf.seek(0)
            c.drawImage(ImageReader(buf), x0, ph - margin - dh, width=dw, height=dh, mask="auto")

        # 1) First screen
        im_first = Image.open(first_png)
        draw_scaled(im_first, img_h_max)
        c.showPage()

        # 2+) Full body: resize to img_w px width, slice vertically
        im_full = Image.open(full_png)
        fw, fh = im_full.size
        target_px_w = int(img_w * 2)
        scale = target_px_w / fw
        new_w = target_px_w
        new_h = int(fh * scale)
        im_r = im_full.resize((new_w, new_h), Image.Resampling.LANCZOS)
        slice_px = int((img_h_max / img_w) * new_w)

        y = 0
        while y < new_h:
            h = min(slice_px, new_h - y)
            band = im_r.crop((0, y, new_w, y + h))
            draw_scaled(band, img_h_max)
            c.showPage()
            y += h

        im_ad = Image.open(admin_png)
        draw_scaled(im_ad, img_h_max)
        c.showPage()

        # Final: 운영 안내 박스 시각 점검 메모
        c.setFont("KG", 12)
        ty = ph - margin
        c.drawString(margin, ty - 16, "어드민에서 거슬리는 점 3개")
        c.setFont("KG", 10)
        ty -= 36
        points = [
            "1) 재발행 URL(GENIE_REREQUEST_URL) 미설정 시 버튼이 #로만 연결될 수 있음.",
            "2) 일부 메일 클라이언트에서 링크 버튼 스타일이 평문처럼 보일 수 있음.",
            "3) ‘이메일 발송 여부’ 문구는 API 시점 기준이라 실제 수신과 100% 일치하지 않을 수 있음.",
        ]
        for line in points:
            c.drawString(margin, ty, line)
            ty -= 16
        c.save()

    return out


if __name__ == "__main__":
    print(main())
