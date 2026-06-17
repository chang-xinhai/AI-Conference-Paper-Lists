#!/usr/bin/env python3
"""Rebuild data/reports/coverage.json from existing normalized data and reports."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aicpl.harvesters import available_sources  # noqa: E402
from aicpl.issues import issues_for  # noqa: E402
from aicpl.util import now_utc, read_json, write_json  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--conferences", default="", help="Comma-separated venue keys. Default: all.")
    parser.add_argument("--years", default="", help="Comma-separated years. Default: target years from config.")
    parser.add_argument("--allow-papercopilot-fallback", action="store_true")
    args = parser.parse_args()

    conferences_filter = {item.strip() for item in args.conferences.split(",") if item.strip()}
    years_filter = {int(item.strip()) for item in args.years.split(",") if item.strip()}
    index = read_json(ROOT / "config" / "conferences.json")
    routes = read_json(ROOT / "config" / "sources.json")["routes"]

    summary = {
        "schema_version": "0.1",
        "generated_at": now_utc(),
        "validate_against_papercopilot": True,
        "source": "existing_normalized_data",
        "allow_papercopilot_fallback": args.allow_papercopilot_fallback,
        "results": [],
    }

    for conference in index["conferences"]:
        venue_key = conference["key"]
        if conferences_filter and venue_key not in conferences_filter:
            continue
        for year in conference["target_years"]:
            if years_filter and year not in years_filter:
                continue
            preferred = routes.get(venue_key, [])
            if not args.allow_papercopilot_fallback:
                preferred = [source for source in preferred if source != "papercopilot"]
            candidates = available_sources(venue_key, year, preferred)
            result = {
                "venue_key": venue_key,
                "year": year,
                "candidate_sources": candidates,
                "status": "not_started",
                "source": "",
                "count": 0,
                "message": "",
            }

            source_issues = issues_for(ROOT / "config" / "source_issues.json", venue_key, year)
            if source_issues:
                result["source_issues"] = source_issues

            normalized_path = ROOT / "data" / "normalized" / venue_key / f"{venue_key}{year}.json"
            if normalized_path.exists():
                normalized = read_json(normalized_path)
                result.update(
                    {
                        "status": "harvested",
                        "source": normalized.get("source", ""),
                        "count": normalized.get("count", len(normalized.get("records", []))),
                    }
                )
                report_path = ROOT / "data" / "reports" / venue_key / f"{venue_key}{year}.json"
                if report_path.exists():
                    report = read_json(report_path)
                    result["validation_status"] = report["status"]
                    result["validation_counts"] = report["counts"]
                    if report.get("known_baseline_issues"):
                        result["validation_known_baseline_issues"] = [
                            issue.get("id", "") for issue in report["known_baseline_issues"]
                        ]
                else:
                    result["validation_status"] = "no_baseline"
                    result["validation_counts"] = {}
            elif candidates:
                result["status"] = "missing"
                result["message"] = "Normalized data file is missing."
            else:
                result["status"] = "unsupported"
                result["message"] = "No implemented official harvester for this conference/year."

            summary["results"].append(result)

    coverage_path = ROOT / "data" / "reports" / "coverage.json"
    write_json(coverage_path, summary)
    harvested = sum(1 for result in summary["results"] if result["status"] == "harvested")
    unsupported = sum(1 for result in summary["results"] if result["status"] == "unsupported")
    missing = sum(1 for result in summary["results"] if result["status"] == "missing")
    print(f"coverage: harvested={harvested} unsupported={unsupported} missing={missing}")
    print(f"coverage report: {coverage_path}")


if __name__ == "__main__":
    main()
