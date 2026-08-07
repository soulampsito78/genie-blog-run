"""Natural-slot isolation for probe execution classes (no live network).

Expects reliability_canary / preflight_canary / smoke / verification to never
qualify as natural-slot completers even when emailed. Class strings are literals
so the suite stays readable if constants land later; when present they must
also appear in KNOWN_EXECUTION_CLASSES.
"""
from __future__ import annotations

import unittest

from today_genie_execution_identity import (
    KNOWN_EXECUTION_CLASSES,
    TODAY_NATURAL_SCHEDULED_SLOT,
    natural_slot_completer_qualification,
)

# Literals — do not rely solely on imported constants.
EXPECTED_ISOLATION_CLASSES = (
    "reliability_canary",
    "preflight_canary",
    "smoke",
    "verification",
)

_KST_DATE = "2026-08-07"
_RUN_PREFIX = "20260807_"


def _emailed_artifact(execution_class: str) -> dict:
    return {
        "run_id": f"{_RUN_PREFIX}today_genie_isolation_{execution_class}",
        "mode": "today_genie",
        "execution_class": execution_class,
        "scheduled_slot": TODAY_NATURAL_SCHEDULED_SLOT,
        "email_sent": True,
        "artifact_status": "emailed",
        "owner_review_status": "pending_review",
        "validation_result": "pass",
        "trigger_source": "manual_probe",
        "workflow_status": "validated",
    }


class ExecutionClassNaturalIsolationTests(unittest.TestCase):
    def test_01_expected_classes_known_when_registry_present(self) -> None:
        for cls in EXPECTED_ISOLATION_CLASSES:
            with self.subTest(execution_class=cls):
                self.assertIn(cls, KNOWN_EXECUTION_CLASSES)

    def test_02_emailed_probe_artifacts_do_not_qualify_natural_slot(self) -> None:
        for cls in EXPECTED_ISOLATION_CLASSES:
            with self.subTest(execution_class=cls):
                match = natural_slot_completer_qualification(
                    _emailed_artifact(cls),
                    program_id="today_genie",
                    kst_date=_KST_DATE,
                    scheduled_slot=TODAY_NATURAL_SCHEDULED_SLOT,
                )
                self.assertFalse(
                    match.qualifies,
                    f"{cls} emailed artifact must not complete natural slot",
                )
                self.assertTrue(
                    match.disqualify_reason,
                    f"{cls} must carry a disqualify_reason",
                )
                self.assertIn(cls, match.disqualify_reason)


if __name__ == "__main__":
    unittest.main()
