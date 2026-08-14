"""Authenticated, run-bound image assets for the Admin HTML preview only.

Customer HTML remains the canonical MIME/CID document.  Browsers have no MIME
attachment context, so the Admin renderer may substitute only stored, validated
run image identities with a same-origin authenticated URL.
"""
from __future__ import annotations

import html
import mimetypes
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Mapping, Optional

from admin_store import (
    _get_gcs_bucket,
    admin_artifact_bucket_name,
    admin_artifact_gcs_prefix,
    admin_runs_dir,
    repo_root,
)

_CID = re.compile(r"^[A-Za-z0-9._@+\-]+$")
_IMG_TAG = re.compile(r"<img\b(?P<attrs>[^>]*?)\s*/?>", re.IGNORECASE)
_SRC_ATTR = re.compile(r"\bsrc\s*=\s*(['\"])(?P<src>[^'\"]+)\1", re.IGNORECASE)
_SAFE_IMAGE_TYPES = frozenset({"image/jpeg", "image/png", "image/webp", "image/gif"})
PREVIEW_ASSET_MAX_BYTES = 12 * 1024 * 1024
PREVIEW_HTML_STREAM_CHUNK_CHARS = 64 * 1024
_PREVIEW_FALLBACK_STYLE = (
    "<style>.admin-preview-image-unavailable{padding:18px;border:1px dashed #9a5700;"
    "border-radius:8px;background:#fff2d9;color:#65400b;font:14px system-ui,sans-serif;}</style>"
)


@dataclass(frozen=True)
class PreviewAsset:
    slot: str
    cid: str
    backend: str
    object_name: str = ""
    local_path: Optional[Path] = None


def _normal_cid(value: Any) -> str:
    raw = str(value or "").strip()
    if raw.lower().startswith("cid:"):
        raw = raw[4:]
    return raw if _CID.fullmatch(raw) else ""


def _safe_gcs_object(run_id: str, value: Any) -> str:
    object_name = str(value or "").strip().lstrip("/")
    expected = f"{admin_artifact_gcs_prefix().strip('/')}/{run_id}.images/"
    return object_name if object_name.startswith(expected) and ".." not in object_name else ""


def _safe_local_path(value: Any) -> Optional[Path]:
    raw = str(value or "").strip()
    if not raw:
        return None
    path = Path(raw)
    candidate = path.resolve() if path.is_absolute() else (repo_root() / path).resolve()
    allowed_roots = ((repo_root() / "output").resolve(), admin_runs_dir().resolve())
    if not any(candidate == root or root in candidate.parents for root in allowed_roots):
        return None
    return candidate if candidate.is_file() else None


def _slot_cids(meta: Mapping[str, Any]) -> dict[str, str]:
    return {
        "top": _normal_cid(meta.get("top_image_cid")),
        "bottom": _normal_cid(meta.get("bottom_image_cid") or meta.get("korea_bottom_shot_cid")),
    }


def _gcs_object_for_slot(meta: Mapping[str, Any], slot: str) -> tuple[str, str]:
    bucket = ""
    object_name = ""
    objects = meta.get("customer_image_gcs_objects")
    if isinstance(objects, Mapping):
        bucket = str(meta.get("customer_image_gcs_bucket") or "").strip()
        object_name = str(objects.get(slot) or "").strip()
    if not object_name and slot == "top":
        bucket = str(
            meta.get("korea_generated_image_gcs_bucket")
            or meta.get("generated_image_gcs_bucket")
            or ""
        ).strip()
        object_name = str(meta.get("korea_generated_top_gcs_object") or meta.get("top_image_gcs_object") or "").strip()
    if not object_name and slot == "bottom":
        bucket = str(meta.get("korea_generated_image_gcs_bucket") or "").strip()
        object_name = str(meta.get("korea_generated_bottom_gcs_object") or "").strip()
    return bucket, object_name


def _local_path_for_slot(meta: Mapping[str, Any], slot: str) -> Optional[Path]:
    generated = meta.get("generated_image_paths")
    if isinstance(generated, Mapping):
        candidate = _safe_local_path(generated.get(slot))
        if candidate:
            return candidate
    keys = (
        ("generated_image_path", "customer_top_image_path", "run_specific_images")
        if slot == "top"
        else ("korea_bottom_shot_path", "bottom_shot_image_path", "customer_bottom_image_path")
    )
    for key in keys:
        candidate = _safe_local_path(meta.get(key))
        if candidate:
            return candidate
    return None


def preview_assets_for_run(run_id: str, meta: Mapping[str, Any]) -> dict[str, PreviewAsset]:
    """Return only exact CID identities belonging to this run, never a browser path."""
    configured_bucket = str(admin_artifact_bucket_name() or "").strip()
    assets: dict[str, PreviewAsset] = {}
    for slot, cid in _slot_cids(meta).items():
        if not cid:
            continue
        bucket, object_name = _gcs_object_for_slot(meta, slot)
        safe_object = _safe_gcs_object(run_id, object_name)
        if configured_bucket and bucket == configured_bucket and safe_object:
            assets[slot] = PreviewAsset(slot=slot, cid=cid, backend="gcs", object_name=safe_object)
            continue
        local_path = _local_path_for_slot(meta, slot)
        if local_path:
            assets[slot] = PreviewAsset(slot=slot, cid=cid, backend="local", local_path=local_path)
    return assets


def preview_known_cids(meta: Mapping[str, Any]) -> dict[str, str]:
    return {cid: slot for slot, cid in _slot_cids(meta).items() if cid}


def preview_asset_url(run_id: str, slot: str) -> str:
    return f"/admin/runs/{run_id}/preview-assets/{slot}"


def _preview_img_rewriter(run_id: str, meta: Mapping[str, Any]):
    assets = preview_assets_for_run(run_id, meta)
    known = preview_known_cids(meta)
    resolved_by_cid = {asset.cid: asset for asset in assets.values()}

    def replace(match: re.Match[str]) -> str:
        tag = match.group(0)
        src_match = _SRC_ATTR.search(tag)
        if not src_match:
            return tag
        src = src_match.group("src")
        if not src.lower().startswith("cid:"):
            return tag
        cid = _normal_cid(src)
        asset = resolved_by_cid.get(cid)
        if asset:
            url = preview_asset_url(run_id, asset.slot)
            return tag[: src_match.start("src")] + url + tag[src_match.end("src") :]
        # A CID image has no browser/MIME context.  Keep a visible controlled
        # state rather than leaving a broken-image icon; the known slot is shown
        # where metadata permits, otherwise it is explicitly unverified.
        slot = known.get(cid, "unknown")
        return (
            f'<div class="admin-preview-image-unavailable" data-preview-slot="{html.escape(slot, quote=True)}" '
            f'role="status">이미지 미리보기 없음 · 저장된 {html.escape(slot, quote=True)} 이미지 근거를 확인하세요.</div>'
        )

    return replace


def stream_customer_html_for_admin_preview(
    run_id: str,
    meta: Mapping[str, Any],
    customer_html: str,
) -> Iterator[str]:
    """Yield a CID-resolved preview without building a second full HTML string."""
    replace = _preview_img_rewriter(run_id, meta)
    source = str(customer_html or "")

    def chunks(start: int, end: int) -> Iterator[str]:
        while start < end:
            next_offset = min(end, start + PREVIEW_HTML_STREAM_CHUNK_CHARS)
            yield source[start:next_offset]
            start = next_offset

    yield _PREVIEW_FALLBACK_STYLE
    offset = 0
    for match in _IMG_TAG.finditer(source):
        yield from chunks(offset, match.start())
        yield replace(match)
        offset = match.end()
    yield from chunks(offset, len(source))


def rewrite_customer_html_for_admin_preview(run_id: str, meta: Mapping[str, Any], customer_html: str) -> str:
    """Compatibility helper; route code should prefer the streaming variant."""
    return "".join(stream_customer_html_for_admin_preview(run_id, meta, customer_html))


def read_preview_asset(run_id: str, meta: Mapping[str, Any], slot: str) -> tuple[Optional[bytes], Optional[str]]:
    """Read one validated asset.  There is no list, wildcard, or caller path input."""
    if slot not in {"top", "bottom"}:
        return None, None
    asset = preview_assets_for_run(run_id, meta).get(slot)
    if asset is None:
        return None, None
    if asset.backend == "local" and asset.local_path is not None:
        try:
            if asset.local_path.stat().st_size > PREVIEW_ASSET_MAX_BYTES:
                return None, None
            payload = asset.local_path.read_bytes()
        except OSError:
            return None, None
        if not payload or len(payload) > PREVIEW_ASSET_MAX_BYTES:
            return None, None
        media_type = mimetypes.guess_type(asset.local_path.name)[0] or "image/jpeg"
        return (payload, media_type) if media_type in _SAFE_IMAGE_TYPES else (None, None)
    if asset.backend == "gcs":
        try:
            blob = _get_gcs_bucket().blob(asset.object_name)
            # ``Blob.exists()`` is only a boolean probe and does not hydrate
            # object metadata in google-cloud-storage.  Production therefore
            # saw ``content_type is None`` for valid JPEGs and rejected them.
            # Reload the exact, already run-bound object before MIME validation;
            # missing objects still fail closed via the caught NotFound error.
            blob.reload()
            media_type = str(blob.content_type or "").split(";", 1)[0].lower()
            size = int(blob.size or 0)
            if (
                media_type not in _SAFE_IMAGE_TYPES
                or size <= 0
                or size > PREVIEW_ASSET_MAX_BYTES
            ):
                return None, None
            payload = blob.download_as_bytes(start=0, end=size - 1)
            if len(payload) != size or len(payload) > PREVIEW_ASSET_MAX_BYTES:
                return None, None
            return payload, media_type
        except Exception:
            return None, None
    return None, None
