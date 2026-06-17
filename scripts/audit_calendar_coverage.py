#!/usr/bin/env python3
"""Audit configured calendar coverage against the Paper Copilot-compatible matrix."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aicpl.util import now_utc, read_json, write_json  # noqa: E402


IRREGULAR_NON_EVENT_YEARS = {
    ("3dv", 2023),
    ("coling", 2021),
    ("coling", 2023),
    ("naacl", 2023),
}


def normalized_path(venue_key: str, year: int) -> Path:
    return ROOT / "data" / "normalized" / venue_key / f"{venue_key}{year}.json"


def non_target_reason(
    venue_key: str,
    year: int,
    target_years: set[int],
    source_gap_index: dict[tuple[str, int], dict],
) -> dict:
    gap = source_gap_index.get((venue_key, year))
    if gap:
        return {
            "reason": "tracked_official_source_gap",
            "gap_id": gap.get("id", ""),
            "gap_status": gap.get("status", ""),
            "evidence": gap.get("evidence", ""),
        }
    if target_years and year < min(target_years):
        return {"reason": "before_first_configured_target"}
    if venue_key == "eccv" and year % 2 == 1:
        return {"reason": "biennial_even_year_cadence"}
    if venue_key == "iccv" and year % 2 == 0:
        return {"reason": "biennial_odd_year_cadence"}
    if (venue_key, year) in IRREGULAR_NON_EVENT_YEARS:
        return {"reason": "irregular_non_event_year"}
    return {"reason": "outside_configured_target_matrix"}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="data/reports/calendar_coverage.json")
    parser.add_argument("--current-year", type=int, default=2026)
    parser.add_argument("--no-fail", action="store_true")
    args = parser.parse_args()

    index = read_json(ROOT / "config" / "conferences.json")
    source_gap_path = ROOT / "data" / "reports" / "source_gaps.json"
    source_gap_index = {}
    if source_gap_path.exists():
        source_gap_report = read_json(source_gap_path)
        source_gap_index = {
            (gap.get("venue_key"), gap.get("year")): gap
            for gap in source_gap_report.get("gaps", [])
        }
    missing_papercopilot_years = []
    tracked_unavailable_papercopilot_years = []
    missing_target_data = []
    empty_target_data = []
    papercopilot_sourced_targets = []
    fallback_targets = []
    non_target_calendar_years = []

    for conference in index["conferences"]:
        venue_key = conference["key"]
        target_years = set(conference.get("target_years", []))
        paper_copilot_years = {
            year
            for year in conference.get("paper_copilot_years", [])
            if 2020 <= year <= args.current_year
        }

        for year in sorted(paper_copilot_years - target_years):
            gap = source_gap_index.get((venue_key, year))
            item = {"venue_key": venue_key, "year": year}
            if gap:
                tracked_unavailable_papercopilot_years.append(
                    {
                        **item,
                        "gap_id": gap.get("id", ""),
                        "gap_status": gap.get("status", ""),
                        "evidence": gap.get("evidence", ""),
                    }
                )
            else:
                missing_papercopilot_years.append(item)

        for year in range(2020, args.current_year + 1):
            if year not in target_years:
                non_target_calendar_years.append(
                    {
                        "venue_key": venue_key,
                        "year": year,
                        **non_target_reason(venue_key, year, target_years, source_gap_index),
                    }
                )

        for year in sorted(target_years):
            path = normalized_path(venue_key, year)
            if not path.exists():
                missing_target_data.append({"venue_key": venue_key, "year": year, "path": str(path.relative_to(ROOT))})
                continue
            data = read_json(path)
            count = data.get("count", len(data.get("records", [])))
            source = data.get("source", "")
            if count <= 0:
                empty_target_data.append({"venue_key": venue_key, "year": year, "path": str(path.relative_to(ROOT))})
            if source == "papercopilot":
                papercopilot_sourced_targets.append({"venue_key": venue_key, "year": year, "path": str(path.relative_to(ROOT))})
            if source == "dblp":
                fallback_targets.append({"venue_key": venue_key, "year": year, "source": source})

    critical = missing_papercopilot_years + missing_target_data + empty_target_data + papercopilot_sourced_targets
    report = {
        "schema_version": "0.1",
        "generated_at": now_utc(),
        "current_year": args.current_year,
        "source_gap_report": str(source_gap_path.relative_to(ROOT)) if source_gap_path.exists() else "",
        "status": "critical" if critical else "warning" if fallback_targets else "ok",
        "summary": {
            "conference_count": len(index["conferences"]),
            "target_count": sum(len(conference.get("target_years", [])) for conference in index["conferences"]),
            "missing_papercopilot_year_count": len(missing_papercopilot_years),
            "tracked_unavailable_papercopilot_year_count": len(tracked_unavailable_papercopilot_years),
            "missing_target_data_count": len(missing_target_data),
            "empty_target_data_count": len(empty_target_data),
            "papercopilot_sourced_target_count": len(papercopilot_sourced_targets),
            "fallback_target_count": len(fallback_targets),
            "non_target_calendar_year_count": len(non_target_calendar_years),
            "non_target_by_reason": {
                reason: sum(1 for item in non_target_calendar_years if item["reason"] == reason)
                for reason in sorted({item["reason"] for item in non_target_calendar_years})
            },
        },
        "missing_papercopilot_years": missing_papercopilot_years,
        "tracked_unavailable_papercopilot_years": tracked_unavailable_papercopilot_years,
        "missing_target_data": missing_target_data,
        "empty_target_data": empty_target_data,
        "papercopilot_sourced_targets": papercopilot_sourced_targets,
        "fallback_targets": fallback_targets,
        "non_target_calendar_years": non_target_calendar_years,
    }
    output = ROOT / args.output
    write_json(output, report)
    print(f"calendar coverage: status={report['status']} summary={report['summary']}")
    print(f"report: {output}")
    if critical and not args.no_fail:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
