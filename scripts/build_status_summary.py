#!/usr/bin/env python3
"""Build a concise per-conference status summary."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aicpl.util import now_utc, read_json, write_json  # noqa: E402


def latest_by_year(results: list[dict]) -> dict[str, dict]:
    latest = {}
    for result in results:
        venue_key = result["venue_key"]
        current = latest.get(venue_key)
        if current is None or result["year"] > current["year"]:
            latest[venue_key] = result
    return latest


def gaps_by_venue(gaps: list[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for gap in gaps:
        grouped.setdefault(gap.get("venue_key", ""), []).append(gap)
    return grouped


def main() -> None:
    conferences = read_json(ROOT / "config" / "conferences.json")["conferences"]
    coverage = read_json(ROOT / "data" / "reports" / "coverage.json")["results"]
    source_gaps = read_json(ROOT / "data" / "reports" / "source_gaps.json")
    calendar = read_json(ROOT / "data" / "reports" / "calendar_coverage.json")
    latest = latest_by_year(coverage)
    gaps = gaps_by_venue(source_gaps.get("gaps", []))

    rows = []
    for conference in conferences:
        venue_key = conference["key"]
        latest_result = latest.get(venue_key, {})
        venue_gaps = sorted(
            gaps.get(venue_key, []),
            key=lambda item: (item.get("year") or 0, item.get("id", "")),
        )
        rows.append(
            {
                "venue_key": venue_key,
                "target_years": conference.get("target_years", []),
                "latest_target_year": latest_result.get("year"),
                "latest_source": latest_result.get("source", ""),
                "latest_count": latest_result.get("count", 0),
                "latest_validation_status": latest_result.get("validation_status", ""),
                "latest_has_source_issue": bool(latest_result.get("source_issues")),
                "current_year_gaps": [
                    {
                        "id": gap.get("id", ""),
                        "year": gap.get("year"),
                        "status": gap.get("status", ""),
                        "evidence": gap.get("evidence", ""),
                    }
                    for gap in venue_gaps
                ],
            }
        )

    summary = {
        "conference_count": len(rows),
        "target_count": calendar["summary"]["target_count"],
        "harvested_latest_count": sum(1 for row in rows if row["latest_target_year"]),
        "latest_source_issue_count": sum(1 for row in rows if row["latest_has_source_issue"]),
        "venues_with_current_year_gaps": sum(1 for row in rows if row["current_year_gaps"]),
    }
    report = {
        "schema_version": "0.1",
        "generated_at": now_utc(),
        "coverage_report": "data/reports/coverage.json",
        "source_gap_report": "data/reports/source_gaps.json",
        "calendar_coverage_report": "data/reports/calendar_coverage.json",
        "summary": summary,
        "conferences": rows,
    }
    output = ROOT / "data" / "reports" / "status_summary.json"
    write_json(output, report)
    print(f"status summary: {summary}")
    print(f"report: {output}")


if __name__ == "__main__":
    main()
