from keysuri_editorial_policy import (
    FIDELITY_RULES,
    policy_block,
)
from keysuri_generation_prompt import GLOBAL_NATURAL_KOREAN_RULES


EXPECTED_FRAGMENTS = [
    "semantic subject and object roles",
    "metric identity and scope",
    "limited preview",
    "media comparisons",
    "publication date from historical event date",
    "validated clinical therapy",
]


def test_all_new_rules_present_in_fidelity_rules():
    for fragment in EXPECTED_FRAGMENTS:
        assert any(fragment in rule for rule in FIDELITY_RULES)


def test_fidelity_rules_reach_policy_block_and_global_natural_korean():
    block = policy_block()
    global_set = set(GLOBAL_NATURAL_KOREAN_RULES)
    for fragment in EXPECTED_FRAGMENTS:
        assert any(fragment in rule for rule in global_set)
        assert fragment in block
