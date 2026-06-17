"""Machine-readable issue annotations for validation and source routing."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .util import read_json


def issues_for(path: Path, venue_key: str, year: int) -> list[dict[str, Any]]:
    """Return configured issue annotations for one venue/year."""
    if not path.exists():
        return []
    issues = read_json(path).get("issues", {})
    return issues.get(f"{venue_key}{year}", [])
