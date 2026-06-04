"""Tests for Kee-Suri source pack schema and source gate foundation."""
from __future__ import annotations

import json
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from keysuri_source_gate import (
    audit_claims,
    run_keysuri_source_gate,
    validate_source_pack,
)
from programs.registry import get_program

_REPO = Path(__file__).resolve().parent.parent
_NOW = datetime(2026, 6, 4, 18, 0, 0, tzinfo=ZoneInfo("Asia/Seoul"))


def _source(
    source_id: str,
    *,
    tier: str = "T2_TIER1_WIRE",
    url: str = "https://example.com/source/test",
    fetched_at: str = "2026-06-04T10:00:00+09:00",
) -> dict:
    return {
        "source_id": source_id,
        "source_name": "Example Source",
        "source_url": url,
        "source_tier": tier,
        "fetched_at": fetched_at,
    }


def _pack(*sources: dict, claims: list[dict] | None = None) -> dict:
    return {
        "program_id": "keysuri_global_tech",
        "generated_at": "2026-06-04T10:00:00+09:00",
        "sources": list(sources),
        "claims": claims or [],
    }


def _claim(
    claim_id: str,
    *,
    claim_type: str = "general",
    source_ids: list[str] | None = None,
    confidence: str = "reported",
    statement: str = "Example claim statement for testing.",
) -> dict:
    return {
        "claim_id": claim_id,
        "statement": statement,
        "claim_type": claim_type,
        "source_ids": source_ids or [],
        "confidence_label": confidence,
    }


class KeysuriSourceGatePackTests(unittest.TestCase):
    def test_empty_source_pack_blocks(self) -> None:
        result = validate_source_pack({"program_id": "keysuri_global_tech", "sources": []})
        self.assertEqual(result.verdict, "block")
        self.assertTrue(any(i.code == "source_pack_empty" for i in result.issues))

    def test_missing_deep_link_blocks(self) -> None:
        pack = _pack(
            _source("s1", url="ftp://example.com/bad"),
        )
        result = validate_source_pack(pack, now=_NOW)
        self.assertEqual(result.verdict, "block")
        self.assertTrue(any(i.code == "source_url_invalid" for i in result.issues))

    def test_unknown_tier_blocks(self) -> None:
        pack = _pack(_source("s1", tier="T9_UNKNOWN"))
        result = validate_source_pack(pack, now=_NOW)
        self.assertEqual(result.verdict, "block")
        self.assertTrue(any(i.code == "source_tier_unknown" for i in result.issues))

    def test_stale_source_holds(self) -> None:
        pack = _pack(
            _source("s1", fetched_at="2026-05-01T10:00:00+09:00"),
            claims=[_claim("c1", source_ids=["s1"])],
        )
        result = run_keysuri_source_gate(pack, now=_NOW)
        self.assertEqual(result.verdict, "hold")
        self.assertTrue(any("stale" in i.code for i in result.issues))


class KeysuriSourceGateClaimTests(unittest.TestCase):
    def test_t4_only_numeric_claim_blocks(self) -> None:
        pack = _pack(
            _source("t4", tier="T4_AGGREGATOR_BLOG"),
            claims=[
                _claim(
                    "num1",
                    claim_type="numeric",
                    source_ids=["t4"],
                    confidence="reported",
                    statement="Revenue reached 10B.",
                )
            ],
        )
        result = audit_claims(pack, pack["claims"], now=_NOW)
        self.assertEqual(result.verdict, "block")

    def test_t3_only_numeric_claim_holds(self) -> None:
        pack = _pack(
            _source("t3", tier="T3_QUALITY_PRESS"),
            claims=[
                _claim(
                    "num1",
                    claim_type="numeric",
                    source_ids=["t3"],
                    confidence="reported",
                    statement="Shipments rose 12 percent.",
                )
            ],
        )
        result = audit_claims(pack, pack["claims"], now=_NOW)
        self.assertEqual(result.verdict, "hold")
        self.assertTrue(any(i.code == "numeric_claim_t3_only" for i in result.issues))

    def test_t0_numeric_claim_passes(self) -> None:
        pack = _pack(
            _source("t0", tier="T0_OFFICIAL_PRIMARY"),
            claims=[
                _claim(
                    "num1",
                    claim_type="numeric",
                    source_ids=["t0"],
                    confidence="confirmed",
                    statement="Official filing reports 10B revenue.",
                )
            ],
        )
        result = audit_claims(pack, pack["claims"], now=_NOW)
        self.assertEqual(result.verdict, "pass")

    def test_confirmed_without_official_or_two_t2_holds(self) -> None:
        pack = _pack(
            _source("t3", tier="T3_QUALITY_PRESS"),
            claims=[
                _claim(
                    "c1",
                    claim_type="general",
                    source_ids=["t3"],
                    confidence="confirmed",
                )
            ],
        )
        result = audit_claims(pack, pack["claims"], now=_NOW)
        self.assertEqual(result.verdict, "hold")
        self.assertTrue(any(i.code == "confirmed_insufficient_support" for i in result.issues))

    def test_law_policy_confirmed_without_t0_holds_if_t2_t3(self) -> None:
        pack = _pack(
            _source("t3", tier="T3_QUALITY_PRESS"),
            claims=[
                _claim(
                    "law1",
                    claim_type="law_policy",
                    source_ids=["t3"],
                    confidence="confirmed",
                    statement="Press confirms draft AI regulation text.",
                )
            ],
        )
        result = audit_claims(pack, pack["claims"], now=_NOW)
        self.assertEqual(result.verdict, "hold")
        self.assertTrue(any(i.code == "legal_confirmed_missing_t0" for i in result.issues))

    def test_law_policy_confirmed_t4_only_blocks(self) -> None:
        pack = _pack(
            _source("t4", tier="T4_AGGREGATOR_BLOG"),
            claims=[
                _claim(
                    "law1",
                    claim_type="law_policy",
                    source_ids=["t4"],
                    confidence="confirmed",
                    statement="Blog claims new AI law passed.",
                )
            ],
        )
        result = audit_claims(pack, pack["claims"], now=_NOW)
        self.assertEqual(result.verdict, "block")

    def test_executive_order_estimated_blocks(self) -> None:
        pack = _pack(
            _source("t0", tier="T0_OFFICIAL_PRIMARY"),
            claims=[
                _claim(
                    "eo1",
                    claim_type="executive_order",
                    source_ids=["t0"],
                    confidence="estimated",
                    statement="Estimated executive order timeline around Q3.",
                )
            ],
        )
        result = audit_claims(pack, pack["claims"], now=_NOW)
        self.assertEqual(result.verdict, "block")
        self.assertTrue(any(i.code == "estimated_not_allowed_for_legal" for i in result.issues))

    def test_unverified_numeric_claim_blocks(self) -> None:
        pack = _pack(
            _source("t2", tier="T2_TIER1_WIRE"),
            claims=[
                _claim(
                    "num1",
                    claim_type="funding",
                    source_ids=["t2"],
                    confidence="unverified",
                    statement="Startup raised unknown amount.",
                )
            ],
        )
        result = audit_claims(pack, pack["claims"], now=_NOW)
        self.assertEqual(result.verdict, "block")
        self.assertTrue(any(i.code == "unverified_numeric_claim" for i in result.issues))

    def test_missing_claims_holds(self) -> None:
        pack = _pack(_source("s1"))
        result = audit_claims(pack, [], now=_NOW)
        self.assertEqual(result.verdict, "hold")
        self.assertTrue(any(i.code == "claims_missing" for i in result.issues))


class KeysuriSamplePackTests(unittest.TestCase):
    def _load(self, name: str) -> dict:
        path = _REPO / "ops" / "feeds" / name
        return json.loads(path.read_text(encoding="utf-8"))

    def test_global_sample_passes(self) -> None:
        pack = self._load("keysuri_global_sources.sample.json")
        result = run_keysuri_source_gate(pack, now=_NOW)
        self.assertEqual(result.verdict, "pass", msg=[(i.code, i.message) for i in result.issues])

    def test_korea_sample_passes(self) -> None:
        pack = self._load("keysuri_korea_sources.sample.json")
        result = run_keysuri_source_gate(pack, now=_NOW)
        self.assertEqual(result.verdict, "pass", msg=[(i.code, i.message) for i in result.issues])


class KeysuriRegistryCompatibilityTests(unittest.TestCase):
    def test_keysuri_programs_source_gate_profile(self) -> None:
        for program_id in ("keysuri_global_tech", "keysuri_korea_tech"):
            with self.subTest(program_id=program_id):
                spec = get_program(program_id)
                self.assertEqual(spec.source_gate_profile, "keysuri_source_gate_v1")
                self.assertTrue(spec.source_gate_enabled)


if __name__ == "__main__":
    unittest.main()
