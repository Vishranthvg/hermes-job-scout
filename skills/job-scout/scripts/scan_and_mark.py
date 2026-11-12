#!/usr/bin/env python3
"""Wrapper that scans and marks matches as seen in one pass.

Point a Hermes `--no-agent` cron job at this file so the digest is final
and those postings are not shown again tomorrow.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from job_scout import main

if __name__ == "__main__":
    args = sys.argv[1:]
    if "--update-seen-after-scan" not in args and "--update-seen" not in args:
        args = ["--update-seen-after-scan", *args]
    sys.exit(main(args))
