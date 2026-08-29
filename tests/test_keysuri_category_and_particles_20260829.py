"""The 2026-08-29 07:23 qa_manual failure, and the two contracts it broke.

That run mailed a browser-privacy feature and a software-supply-chain arrest
under "배터리·EV·에너지·전력", and shipped "흐름와" and "후속를" as reader prose —
and the quality gate still called it READY and customer-ready.

Category root cause: keyword matching was bare substring, so 'ess' (energy
storage system) matched inside "addresses", "relentless" and "wellness".
Particle root cause: padding templates hard-coded 와/를 onto dynamic checkpoint
phrases (introduced in f564ab7).
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from keysuri_global_signal_scoring import (  # noqa: E402
    _keyword_matches,
    classify_global_tech_category,
)
from keysuri_korean_particles import (  # noqa: E402
    CONJUNCTION,
    INSTRUMENT,
    OBJECT,
    SUBJECT,
    TOPIC,
    attach_particle,
    correct_particles,
    particle_findings,
    select_particle,
)

CYBER = "cybersecurity_cloud_datacenter"


def _classify(title: str, body: str = "") -> str:
    return classify_global_tech_category(f"{title} {body}".strip(), title=title)[0]


class SubstringRootCauseTests(unittest.TestCase):
    def test_ess_no_longer_matches_inside_english_words(self) -> None:
        for word in ("personal email addresses", "a relentless campaign", "health and wellness"):
            self.assertFalse(_keyword_matches("ess", word), word)

    def test_ess_still_matches_as_its_own_word(self) -> None:
        self.assertTrue(_keyword_matches("ess", "grid ess deployment"))

    def test_other_short_tokens_are_bounded_too(self) -> None:
        self.assertFalse(_keyword_matches("chip", "shipping chipsets"))
        self.assertTrue(_keyword_matches("chip", "a new chip"))
        self.assertFalse(_keyword_matches("fab", "fabulous results"))

    def test_multi_word_keywords_tolerate_hyphen_or_space(self) -> None:
        self.assertTrue(_keyword_matches("data center", "expand data center footprint"))
        self.assertTrue(_keyword_matches("data center", "expand data-center footprint"))
        self.assertTrue(_keyword_matches("supply-chain attack", "a supply chain attack"))


class FailedRunCategoryTests(unittest.TestCase):
    """The exact five articles the failed run selected."""

    def test_brave_privacy_is_not_energy(self) -> None:
        got = _classify(
            "Brave’s browser one-ups Chrome with its new support for email aliases",
            "The feature allows Brave's users to sign up for websites and other online "
            "services without having to share their personal email addresses.",
        )
        self.assertEqual(got, CYBER)

    def test_teampcp_supply_chain_attack_is_not_energy(self) -> None:
        got = _classify(
            "Authorities arrest 2 alleged members of prolific hacking group TeamPCP",
            "The group infected more than 1,000 organizations in a relentless "
            "supply-chain attack campaign.",
        )
        self.assertEqual(got, CYBER)

    def test_thailand_ai_accelerator_is_not_energy(self) -> None:
        got = _classify(
            "Supporting Thailand’s next generation of AI startups",
            "OpenAI and Thailand’s MHESI launch an eight-week accelerator helping 10 "
            "health, wellness, and education startups turn AI prototypes into products.",
        )
        self.assertEqual(got, "ai_software_platform")

    def test_chip_financing_stays_semiconductor(self) -> None:
        self.assertEqual(
            _classify(
                "Neocloud Lambda secures $1B in debt to buy more chips",
                "raised $1B in private debt to buy Nvidia AI chips",
            ),
            "semiconductor_chip_infra",
        )

    def test_datacenter_ipo_stays_datacenter(self) -> None:
        self.assertEqual(
            _classify(
                "ESDS Software Solution targets Rs 720 Crore IPO, will use proceeds to "
                "expand data center footprint",
                "IPO launches today",
            ),
            CYBER,
        )


class AdversarialCategoryTests(unittest.TestCase):
    """Incidental vocabulary must not decide the category."""

    def test_privacy_article_mentioning_power_is_not_energy(self) -> None:
        got = _classify(
            "New browser privacy tool blocks trackers",
            "The feature gives users the power to hide their email addresses.",
        )
        self.assertNotEqual(got, "battery_ev_energy_grid")

    def test_security_article_mentioning_network_and_supply_is_not_energy(self) -> None:
        got = _classify(
            "Ransomware crew breached a logistics network",
            "The malware spread through the supply chain and the power was cut briefly.",
        )
        self.assertNotEqual(got, "battery_ev_energy_grid")

    def test_robot_article_mentioning_battery_is_robotics(self) -> None:
        got = _classify(
            "Startup unveils companion robot for home care",
            "The robot returns to its charging dock when the battery runs low.",
        )
        self.assertEqual(got, "robotics_automation_manufacturing")

    def test_datacenter_power_procurement_is_still_allowed_to_be_energy(self) -> None:
        """Negative evidence must not make a genuine energy story unreachable."""
        got = _classify(
            "Data center operator signs grid storage and power demand deal",
            "The site adds ess capacity and a long-term energy grid contract.",
        )
        self.assertIn(got, {"battery_ev_energy_grid", CYBER})


class ParticleAgreementTests(unittest.TestCase):
    def test_jongseong_pairs(self) -> None:
        cases = [
            ("흐름", CONJUNCTION, "과"), ("서비스", CONJUNCTION, "와"),
            ("후속", OBJECT, "을"), ("기대", OBJECT, "를"),
            ("시장", TOPIC, "은"), ("차이", TOPIC, "는"),
            ("공급망", SUBJECT, "이"), ("서비스", SUBJECT, "가"),
        ]
        for word, pair, expected in cases:
            self.assertEqual(select_particle(word, pair), expected, word)

    def test_instrument_rieul_exception(self) -> None:
        self.assertEqual(select_particle("정책", INSTRUMENT), "으로")
        self.assertEqual(select_particle("서울", INSTRUMENT), "로")   # ㄹ
        self.assertEqual(select_particle("메모리", INSTRUMENT), "로")  # vowel

    def test_non_hangul_endings_refuse_rather_than_guess(self) -> None:
        for word in ("GTM", "5G", "(팔로우온)", "NVIDIA Blog", "AI"):
            self.assertIsNone(select_particle(word, SUBJECT), word)
            self.assertIsNone(attach_particle(word, OBJECT), word)


class ParticleDetectionTests(unittest.TestCase):
    def test_the_two_mailed_defects_are_detected_and_corrected(self) -> None:
        text = "투자 환경·후속 라운드(팔로우온) 흐름와 이어집니다. GTM 후속를 봅니다."
        tokens = {f["token"] for f in particle_findings(text)}
        self.assertEqual(tokens, {"흐름와", "후속를"})
        fixed, _ = correct_particles(text)
        self.assertIn("흐름과", fixed)
        self.assertIn("후속을", fixed)
        self.assertEqual(particle_findings(fixed), [])

    def test_the_20260814_defect_is_detected(self) -> None:
        found = particle_findings("정책·규제·자본·공급망가 실제 비용입니다.")
        self.assertEqual([f["token"] for f in found], ["공급망가"])

    def test_findings_are_structured(self) -> None:
        found = particle_findings("흐름와 갑니다.", field="why_now", news_id="n1", rank=2)
        self.assertEqual(found[0]["field"], "why_now")
        self.assertEqual(found[0]["news_id"], "n1")
        self.assertEqual(found[0]["rank"], 2)
        self.assertEqual(found[0]["expected_particle"], "과")
        self.assertEqual(found[0]["actual_particle"], "와")

    def test_verbal_endings_are_not_particles(self) -> None:
        for clean in (
            "이 흐름은 국내 산업에 어떤 영향을 미칠 것인가?",
            "무엇인가 달라졌는가?",
            "같은 방향으로 가는 흐름입니다.",
        ):
            self.assertEqual(particle_findings(clean), [], clean)

    def test_nouns_ending_in_i_are_not_rewritten(self) -> None:
        """릴레이 / 플레이 / 디스플레이 end in 이; they are not noun + 이."""
        for clean in ("릴레이 경쟁이 이어집니다.", "플레이 방식을 봅니다.", "디스플레이 시장은 큽니다."):
            self.assertEqual(correct_particles(clean)[0], clean, clean)

    def test_correction_does_not_touch_non_hangul_endings(self) -> None:
        text = "GTM 후속 계획을 봅니다."
        self.assertEqual(correct_particles(text)[0], text)


class SurfaceGateTests(unittest.TestCase):
    def test_particle_defect_is_now_blocking(self) -> None:
        from keysuri_global_visible_surface import (
            GLOBAL_VISIBLE_KOREAN_PARTICLE_DEFECT,
            GLOBAL_VISIBLE_SEVERITY,
        )

        self.assertEqual(
            GLOBAL_VISIBLE_SEVERITY[GLOBAL_VISIBLE_KOREAN_PARTICLE_DEFECT], "block"
        )

    def test_repair_stage_corrects_particles_before_adjudication(self) -> None:
        from keysuri_visible_text_quality import repair_keysuri_visible_text_fields

        payload = {"top_5_news": {"items": [{"rank": 1, "why_now": "흐름와 이어집니다."}]}}
        repaired, fields = repair_keysuri_visible_text_fields(payload)
        self.assertIn("흐름과", repaired["top_5_news"]["items"][0]["why_now"])
        self.assertEqual(fields["korean_particle_repaired_count"], 1)


if __name__ == "__main__":
    unittest.main()
