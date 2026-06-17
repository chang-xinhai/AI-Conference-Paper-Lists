"""Validation helpers."""

from __future__ import annotations

import html
import re
import unicodedata
from typing import Any

from .util import now_utc


def canonical_title(text: str) -> str:
    text = html.unescape(text or "")
    text = re.sub(r"<.*?>", " ", text)
    text = text.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    text = text.replace("—", "-").replace("–", "-").replace("−", "-")
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^a-zA-Z0-9]+", " ", text.lower())
    return re.sub(r"\s+", " ", text).strip()


def compare_records(
    *,
    venue_key: str,
    year: int,
    source_name: str,
    records: list[dict[str, Any]],
    baseline_records: list[dict[str, Any]],
    min_count_ratio: float = 0.95,
    known_baseline_issues: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    titles = {canonical_title(record.get("title", "")) for record in records if record.get("title")}
    baseline_titles = {
        canonical_title(record.get("title", ""))
        for record in baseline_records
        if record.get("title")
    }
    overlap = len(titles & baseline_titles)
    missing_from_ours = sorted(baseline_titles - titles)[:100]
    extra_in_ours = sorted(titles - baseline_titles)[:100]
    ours_count = len(titles)
    baseline_count = len(baseline_titles)
    count_ratio = ours_count / baseline_count if baseline_count else 1.0
    overlap_ratio = overlap / baseline_count if baseline_count else 1.0
    status = "ok"
    if baseline_count and count_ratio < min_count_ratio:
        status = "needs_attention"
    elif baseline_count and overlap_ratio < min_count_ratio:
        status = "title_drift"

    return {
        "schema_version": "0.1",
        "venue_key": venue_key,
        "year": year,
        "source": source_name,
        "baseline": "papercopilot",
        "generated_at": now_utc(),
        "status": status,
        "min_count_ratio": min_count_ratio,
        "counts": {
            "ours": ours_count,
            "baseline": baseline_count,
            "title_overlap": overlap,
            "count_ratio": round(count_ratio, 4),
            "overlap_ratio": round(overlap_ratio, 4),
        },
        "known_baseline_issues": known_baseline_issues or [],
        "samples": {
            "missing_from_ours": missing_from_ours,
            "extra_in_ours": extra_in_ours,
        },
    }


def no_baseline_report(
    *,
    venue_key: str,
    year: int,
    source_name: str,
    records: list[dict[str, Any]],
    baseline: str = "papercopilot",
    min_count_ratio: float = 0.95,
    known_baseline_issues: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    titles = {canonical_title(record.get("title", "")) for record in records if record.get("title")}
    return {
        "schema_version": "0.1",
        "venue_key": venue_key,
        "year": year,
        "source": source_name,
        "baseline": baseline,
        "generated_at": now_utc(),
        "status": "no_baseline",
        "min_count_ratio": min_count_ratio,
        "counts": {
            "ours": len(titles),
            "baseline": 0,
            "title_overlap": 0,
            "count_ratio": 1.0,
            "overlap_ratio": 1.0,
        },
        "known_baseline_issues": known_baseline_issues or [],
        "samples": {
            "missing_from_ours": [],
            "extra_in_ours": sorted(titles)[:100],
        },
    }
