#!/usr/bin/env python3
"""
Runner entrypoint for the Genie orchestrator: run one job (today_genie or
tomorrow_genie), apply policy, send email and create Naver draft when allowed.
Logs a single non-PII summary line. No auto-publish.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys

from orchestrator import (
    run_genie_job,
    send_email_if_allowed,
    create_naver_draft_if_allowed,
)

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

SUPPORTED_MODES = ("today_genie", "tomorrow_genie")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Genie orchestration for one mode.")
    parser.add_argument(
        "mode",
        nargs="?",
        choices=SUPPORTED_MODES,
        help="today_genie or tomorrow_genie",
    )
    args = parser.parse_args()

    mode = args.mode or os.getenv("GENIE_MODE", "").strip()
    if mode not in SUPPORTED_MODES:
        logger.error("run_orchestrator: mode required (env GENIE_MODE or CLI arg): today_genie | tomorrow_genie")
        return 2

    result = run_genie_job(mode)
    email_sent = send_email_if_allowed(result)
    naver_draft_created = create_naver_draft_if_allowed(result)

    logger.info(
        "run_orchestrator: mode=%s reason_summary=%s email_sent=%s naver_draft_created=%s",
        mode,
        result.reason_summary,
        email_sent,
        naver_draft_created,
    )

    # Exit 1: request failed, API error, or policy suppresses distribution.
    # review_required (draft_only) is not a failure — content was generated and policy applied.
    if result.response_status is None:
        return 1
    if result.response_status != 200:
        return 1
    if result.decision.suppress_external:
        return 1
    # 200 and not suppressed: ok or review_required both succeed.
    return 0


if __name__ == "__main__":
    sys.exit(main())
