#!/usr/bin/env python3
"""Kee-Suri manual opt-in wardrobe canary runner (R5B-II — preflight/dry-run only)."""
from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from keysuri_manual_opt_in_canary_runner import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
