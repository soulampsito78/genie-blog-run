"""Kee-Suri approved image asset registry — runtime reuse policy."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Sequence, Tuple

REGISTRY_REL_PATH = Path("assets/keysuri/keysuri_approved_image_assets.json")

ImageSourceMode = Literal["approved_registry", "explicit_test_override", "unresolved"]

GLOBAL_TOP_ROLE = "global_top"
KOREA_TOP_ROLE = "korea_top"
KOREA_BOTTOM_ROLE = "korea_bottom"
HERO_TOPSHOT_ROLE = "hero_topshot"

APPROVED_STATUS = "approved"
APPROVED_LOCKED_STATUS = "approved_locked"
APPROVED_DIRECTION_LOCKED_STATUS = "approved_direction_locked"
CURRENT_FALLBACK_STATUS = "current_fallback_approved"
PENDING_OWNER_STATUS = "approved_candidate_pending_owner_visual_check"
REJECTED_STATUS = "rejected"
SUPERSEDED_STATUS = "superseded"

_ROUTINE_STATUSES = (
    APPROVED_STATUS,
    CURRENT_FALLBACK_STATUS,
    APPROVED_LOCKED_STATUS,
    APPROVED_DIRECTION_LOCKED_STATUS,
)
_PREVIEW_TEST_STATUSES = _ROUTINE_STATUSES

# Known korea_bottom hashes — must never resolve as global_top.
_KOREA_BOTTOM_SHA256 = frozenset(
    {
        "2792aca4c5d1011e822d563ddd7108e6c96c45fa56766d4368ac65af26f7370c",
        "c6209f406717aa68ef8be70fbfd9dbc30b882e9fae800633d570111bb1b3faf9",
    }
)

PROGRAM_GLOBAL = "keysuri_global_tech"
PROGRAM_KOREA = "keysuri_korea_tech"


@dataclass(frozen=True)
class ApprovedImageAsset:
    asset_id: str
    persona: str
    program: str
    slot: str
    role: str
    status: str
    file_path: str
    manifest_path: Optional[str]
    sha256: str
    width: int
    height: int
    watermark_status: str
    approved_for: tuple[str, ...]
    source_type: str
    approved_at: str
    approval_note: str
    replacement_policy: str
    image_role: str = ""
    watermarked_path: Optional[str] = None
    watermarked_sha256: str = ""
    gcs_object: str = ""

    def resolved_file_path(self, repo_root: Path) -> Path:
        return (repo_root / self.file_path).resolve()

    def resolved_watermarked_path(self, repo_root: Path) -> Optional[Path]:
        if not self.watermarked_path:
            return None
        path = (repo_root / self.watermarked_path).resolve()
        return path if path.is_file() else None

    def resolved_manifest_path(self, repo_root: Path) -> Optional[Path]:
        if not self.manifest_path:
            return None
        path = (repo_root / self.manifest_path).resolve()
        return path if path.is_file() else None

    def preview_file_path(self, repo_root: Path, *, prefer_watermarked: bool = False) -> Path:
        """Return on-disk path for preview embedding (no image generation)."""
        if prefer_watermarked:
            wm = self.resolved_watermarked_path(repo_root)
            if wm is not None:
                return wm
        path = self.resolved_file_path(repo_root)
        if path.is_file():
            return path
        wm = self.resolved_watermarked_path(repo_root)
        if wm is not None:
            return wm
        return path

    def to_dict(self) -> dict:
        out = {
            "asset_id": self.asset_id,
            "persona": self.persona,
            "program": self.program,
            "slot": self.slot,
            "role": self.role,
            "status": self.status,
            "file_path": self.file_path,
            "manifest_path": self.manifest_path,
            "sha256": self.sha256,
            "width": self.width,
            "height": self.height,
            "watermark_status": self.watermark_status,
            "approved_for": list(self.approved_for),
            "source_type": self.source_type,
            "approved_at": self.approved_at,
            "approval_note": self.approval_note,
            "replacement_policy": self.replacement_policy,
        }
        if self.image_role:
            out["image_role"] = self.image_role
        if self.watermarked_path:
            out["watermarked_path"] = self.watermarked_path
        if self.watermarked_sha256:
            out["watermarked_sha256"] = self.watermarked_sha256
        if self.gcs_object:
            out["gcs_object"] = self.gcs_object
        return out


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _parse_asset(raw: dict) -> ApprovedImageAsset:
    approved_for = raw.get("approved_for") or []
    if not isinstance(approved_for, list):
        approved_for = []
    return ApprovedImageAsset(
        asset_id=str(raw.get("asset_id") or ""),
        persona=str(raw.get("persona") or "keysuri"),
        program=str(raw.get("program") or ""),
        slot=str(raw.get("slot") or ""),
        role=str(raw.get("role") or HERO_TOPSHOT_ROLE),
        status=str(raw.get("status") or ""),
        file_path=str(raw.get("file_path") or ""),
        manifest_path=str(raw.get("manifest_path") or "") or None,
        sha256=str(raw.get("sha256") or "").lower(),
        width=int(raw.get("width") or 0),
        height=int(raw.get("height") or 0),
        watermark_status=str(raw.get("watermark_status") or ""),
        approved_for=tuple(str(x) for x in approved_for),
        source_type=str(raw.get("source_type") or ""),
        approved_at=str(raw.get("approved_at") or ""),
        approval_note=str(raw.get("approval_note") or ""),
        replacement_policy=str(raw.get("replacement_policy") or ""),
        image_role=str(raw.get("image_role") or ""),
        watermarked_path=str(raw.get("watermarked_path") or "") or None,
        watermarked_sha256=str(raw.get("watermarked_sha256") or "").lower(),
        gcs_object=str(raw.get("gcs_object") or ""),
    )


def registry_path(repo_root: Path) -> Path:
    return (repo_root / REGISTRY_REL_PATH).resolve()


def load_approved_image_registry(repo_root: Path) -> dict:
    path = registry_path(repo_root)
    if not path.is_file():
        raise FileNotFoundError(f"Approved image asset registry not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Approved image asset registry must be a JSON object")
    return data


def list_approved_assets(repo_root: Path) -> List[ApprovedImageAsset]:
    data = load_approved_image_registry(repo_root)
    assets = data.get("assets") or []
    if not isinstance(assets, list):
        return []
    return [_parse_asset(item) for item in assets if isinstance(item, dict)]


def normalize_asset_role(role: str) -> str:
    token = str(role or "").strip().lower()
    if token in (HERO_TOPSHOT_ROLE, "hero", "top", "top_shot", GLOBAL_TOP_ROLE):
        return GLOBAL_TOP_ROLE
    if token in (KOREA_TOP_ROLE, "korea_topshot"):
        return KOREA_TOP_ROLE
    if token in (KOREA_BOTTOM_ROLE, "bottom_shot", "bottom", "offduty_02c"):
        return KOREA_BOTTOM_ROLE
    return token


def default_top_role_for_program(program_id: str) -> str:
    if program_id == PROGRAM_KOREA:
        return KOREA_TOP_ROLE
    return GLOBAL_TOP_ROLE


def _asset_matches_use_case(asset: ApprovedImageAsset, use_case: str) -> bool:
    if use_case in asset.approved_for:
        return True
    if use_case == "contract_preview" and "contract_preview_test" in asset.approved_for:
        return True
    return False


def _role_matches(asset: ApprovedImageAsset, requested_role: str) -> bool:
    req = normalize_asset_role(requested_role)
    asset_role = normalize_asset_role(asset.role)
    if asset_role == req:
        return True
    # Legacy hero_topshot entries only match global_top when explicitly global program.
    if req == GLOBAL_TOP_ROLE and asset.role == HERO_TOPSHOT_ROLE:
        return asset.program == PROGRAM_GLOBAL
    return False


def is_korea_bottom_sha256(sha256: str) -> bool:
    return str(sha256 or "").lower() in _KOREA_BOTTOM_SHA256


def assert_role_safe_for_request(
    asset: ApprovedImageAsset,
    *,
    requested_role: str,
    program_id: str,
    image_sha256: Optional[str] = None,
) -> None:
    """Raise ValueError when resolver would return a role-mismatched asset."""
    req = normalize_asset_role(requested_role)
    asset_role = normalize_asset_role(asset.role)

    if req == GLOBAL_TOP_ROLE and asset_role == KOREA_BOTTOM_ROLE:
        raise ValueError(
            f"asset_role_mismatch: korea_bottom asset {asset.asset_id!r} cannot serve global_top"
        )
    if req == KOREA_TOP_ROLE and asset_role == KOREA_BOTTOM_ROLE:
        raise ValueError(
            f"asset_role_mismatch: korea_bottom asset {asset.asset_id!r} cannot serve korea_top"
        )
    if req in (GLOBAL_TOP_ROLE, KOREA_TOP_ROLE) and asset_role == KOREA_BOTTOM_ROLE:
        raise ValueError(
            f"asset_role_mismatch: bottom_shot asset {asset.asset_id!r} cannot serve {req!r}"
        )
    if program_id == PROGRAM_GLOBAL and asset_role == KOREA_BOTTOM_ROLE:
        raise ValueError(
            f"wrong_locked_asset_for_program: korea_bottom asset for {program_id!r}"
        )
    if req == GLOBAL_TOP_ROLE and image_sha256 and is_korea_bottom_sha256(image_sha256):
        raise ValueError(
            "fallback_role_mismatch: 105936 korea_bottom hash cannot be used as global_top"
        )


def resolve_approved_asset(
    repo_root: Path,
    program_id: str,
    *,
    role: Optional[str] = None,
    slot: Optional[str] = None,
    use_case: str = "contract_preview",
    prefer_watermarked: bool = False,
) -> ApprovedImageAsset:
    """Return the best approved asset for program + role."""
    requested_role = normalize_asset_role(role or default_top_role_for_program(program_id))
    matches: List[ApprovedImageAsset] = []
    for asset in list_approved_assets(repo_root):
        if asset.program != program_id:
            continue
        if not _role_matches(asset, requested_role):
            continue
        if asset.status in (SUPERSEDED_STATUS, REJECTED_STATUS):
            continue
        if asset.status not in _PREVIEW_TEST_STATUSES:
            continue
        if slot and asset.slot != slot:
            continue
        if use_case and not _asset_matches_use_case(asset, use_case):
            continue
        preview_path = asset.preview_file_path(repo_root, prefer_watermarked=prefer_watermarked)
        if not preview_path.is_file():
            continue
        try:
            actual_sha = _sha256_file(preview_path)
        except OSError:
            continue
        assert_role_safe_for_request(
            asset,
            requested_role=requested_role,
            program_id=program_id,
            image_sha256=actual_sha,
        )
        matches.append(asset)

    if not matches:
        raise FileNotFoundError(
            f"No approved asset for program={program_id!r} role={requested_role!r} use_case={use_case!r}"
        )
    matches.sort(key=lambda a: a.approved_at, reverse=True)
    return matches[0]


def resolve_approved_hero_asset(
    repo_root: Path,
    program_id: str,
    *,
    slot: Optional[str] = None,
    use_case: str = "contract_preview",
    role: Optional[str] = None,
) -> ApprovedImageAsset:
    """Return hero/top asset for a program (global_top or korea_top)."""
    requested = role or default_top_role_for_program(program_id)
    prefer_watermarked = use_case in ("contract_preview", "owner_review_preview")
    return resolve_approved_asset(
        repo_root,
        program_id,
        role=requested,
        slot=slot,
        use_case=use_case,
        prefer_watermarked=prefer_watermarked,
    )


def resolve_korea_bottom_asset(
    repo_root: Path,
    *,
    use_case: str = "korea_bottom_preview",
    prefer_watermarked: bool = False,
) -> ApprovedImageAsset:
    return resolve_approved_asset(
        repo_root,
        PROGRAM_KOREA,
        role=KOREA_BOTTOM_ROLE,
        slot="18:30",
        use_case=use_case,
        prefer_watermarked=prefer_watermarked,
    )


def resolve_approved_hero_image_path(
    repo_root: Path,
    program_id: str,
    *,
    slot: Optional[str] = None,
    use_case: str = "contract_preview",
    role: Optional[str] = None,
) -> Path:
    asset = resolve_approved_hero_asset(
        repo_root,
        program_id,
        slot=slot,
        use_case=use_case,
        role=role,
    )
    prefer_watermarked = use_case in ("contract_preview", "owner_review_preview")
    path = asset.preview_file_path(repo_root, prefer_watermarked=prefer_watermarked)
    if not path.is_file():
        raise FileNotFoundError(f"Approved asset file missing: {path}")
    actual_sha = _sha256_file(path)
    assert_role_safe_for_request(
        asset,
        requested_role=role or default_top_role_for_program(program_id),
        program_id=program_id,
        image_sha256=actual_sha,
    )
    return path


def match_registry_asset(
    repo_root: Path,
    image_path: Path,
    program_id: str,
    *,
    role: Optional[str] = None,
    use_case: Optional[str] = None,
    verify_sha256: bool = True,
) -> Optional[ApprovedImageAsset]:
    """Match an on-disk image to an approved registry entry by sha256 + role."""
    candidate = Path(image_path).expanduser().resolve()
    if not candidate.is_file():
        return None
    try:
        actual_sha = _sha256_file(candidate)
    except OSError:
        return None

    requested_role = normalize_asset_role(role or default_top_role_for_program(program_id))

    for asset in list_approved_assets(repo_root):
        if asset.program != program_id:
            continue
        if not _role_matches(asset, requested_role):
            continue
        if asset.status in (SUPERSEDED_STATUS, REJECTED_STATUS):
            continue
        if asset.status not in _PREVIEW_TEST_STATUSES:
            continue
        if use_case and not _asset_matches_use_case(asset, use_case or "contract_preview"):
            continue

        known_hashes = {asset.sha256.lower()}
        if asset.watermarked_sha256:
            known_hashes.add(asset.watermarked_sha256.lower())

        registry_file = asset.resolved_file_path(repo_root)
        wm_file = asset.resolved_watermarked_path(repo_root)

        path_match = (
            registry_file.resolve() == candidate
            or (wm_file is not None and wm_file.resolve() == candidate)
        )
        sha_match = not verify_sha256 or actual_sha in known_hashes

        if not path_match and not sha_match:
            continue

        try:
            assert_role_safe_for_request(
                asset,
                requested_role=requested_role,
                program_id=program_id,
                image_sha256=actual_sha,
            )
        except ValueError:
            continue

        if verify_sha256 and asset.sha256 and actual_sha not in known_hashes and not path_match:
            continue
        return asset
    return None


def classify_image_selection(
    repo_root: Path,
    image_path: Path,
    program_id: str,
    *,
    explicit_override: bool,
    use_case: str = "contract_preview",
    role: Optional[str] = None,
) -> ImageSourceMode:
    if match_registry_asset(
        repo_root,
        image_path,
        program_id,
        use_case=use_case,
        role=role,
    ):
        return "approved_registry"
    if explicit_override:
        return "explicit_test_override"
    return "unresolved"
