"""Console script wrappers."""

from __future__ import annotations

import runpy
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def build_index_main() -> None:
    runpy.run_path(str(ROOT / "scripts" / "build_conference_index.py"), run_name="__main__")


def harvest_main() -> None:
    runpy.run_path(str(ROOT / "scripts" / "harvest.py"), run_name="__main__")


def validate_main() -> None:
    runpy.run_path(str(ROOT / "scripts" / "validate_against_papercopilot.py"), run_name="__main__")
