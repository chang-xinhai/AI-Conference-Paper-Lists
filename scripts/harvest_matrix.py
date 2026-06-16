#!/usr/bin/env python3
"""Batch-harvest conference/year targets from config/conferences.json."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aicpl.harvesters import available_sources, harvest_with_source  # noqa: E402
from aicpl.sources import papercopilot  # noqa: E402
from aicpl.util import now_utc, read_json, write_json  # noqa: E402
from aicpl.validation import compare_records  # noqa: E402


def is_accepted_like(record: dict) -> bool:
    status = str(record.get("status") or "").lower()
    return not any(token in status for token in ["reject", "withdraw", "desk"])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--conferences", default="", help="Comma-separated venue keys. Default: all.")
    parser.add_argument("--years", default="", help="Comma-separated years. Default: target years from config.")
    parser.add_argument("--validate", action="store_true")
    parser.add_argument("--paperlists", default="", help="Optional local papercopilot/paperlists checkout")
    parser.add_argument("--min-count-ratio", type=float, default=0.95)
    parser.add_argument("--allow-papercopilot-fallback", action="store_true")
    args = parser.parse_args()

    conferences_filter = {item.strip() for item in args.conferences.split(",") if item.strip()}
    years_filter = {int(item.strip()) for item in args.years.split(",") if item.strip()}
    index = read_json(ROOT / "config" / "conferences.json")
    routes = read_json(ROOT / "config" / "sources.json")["routes"]

    summary = {
        "schema_version": "0.1",
        "generated_at": now_utc(),
        "validate_against_papercopilot": args.validate,
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
            if not candidates:
                result["status"] = "unsupported"
                result["message"] = "No implemented official harvester for this conference/year."
                summary["results"].append(result)
                print(f"{venue_key}{year}: unsupported", flush=True)
                continue

            source = candidates[0]
            try:
                payload = harvest_with_source(source, venue_key, year)
                raw_path = ROOT / "data" / "raw" / source / venue_key / f"{venue_key}{year}.json"
                normalized_path = ROOT / "data" / "normalized" / venue_key / f"{venue_key}{year}.json"
                write_json(raw_path, payload)
                normalized = {
                    "schema_version": "0.1",
                    "venue_key": venue_key,
                    "year": year,
                    "source": source,
                    "source_url": payload["source_url"],
                    "fetched_at": payload["fetched_at"],
                    "count": len(payload["records"]),
                    "records": payload["records"],
                }
                write_json(normalized_path, normalized)
                result["status"] = "harvested"
                result["source"] = source
                result["count"] = len(payload["records"])
                if args.validate:
                    try:
                        if args.paperlists:
                            pc_path = papercopilot.path_for(venue_key, year)
                            blob = subprocess.check_output(
                                ["git", "show", f"HEAD:{pc_path}"],
                                cwd=args.paperlists,
                                stderr=subprocess.DEVNULL,
                            )
                            baseline_rows = json.loads(blob)
                        else:
                            baseline_rows = papercopilot.load(venue_key, year)
                    except Exception:
                        result["validation_status"] = "no_baseline"
                        result["validation_counts"] = {}
                    else:
                        baseline_records = [
                            record
                            for record in papercopilot.normalize(venue_key, year, baseline_rows)
                            if is_accepted_like(record)
                        ]
                        report = compare_records(
                            venue_key=venue_key,
                            year=year,
                            source_name=source,
                            records=payload["records"],
                            baseline_records=baseline_records,
                            min_count_ratio=args.min_count_ratio,
                        )
                        report_path = ROOT / "data" / "reports" / venue_key / f"{venue_key}{year}.json"
                        write_json(report_path, report)
                        result["validation_status"] = report["status"]
                        result["validation_counts"] = report["counts"]
                print(f"{venue_key}{year}: harvested {result['count']} from {source}", flush=True)
            except Exception as exc:  # noqa: BLE001 - report and continue in batch mode.
                result["status"] = "failed"
                result["source"] = source
                result["message"] = str(exc)
                print(f"{venue_key}{year}: failed via {source}: {exc}", flush=True)
            summary["results"].append(result)

    coverage_path = ROOT / "data" / "reports" / "coverage.json"
    write_json(coverage_path, summary)
    harvested = sum(1 for result in summary["results"] if result["status"] == "harvested")
    unsupported = sum(1 for result in summary["results"] if result["status"] == "unsupported")
    failed = sum(1 for result in summary["results"] if result["status"] == "failed")
    print(f"coverage: harvested={harvested} unsupported={unsupported} failed={failed}", flush=True)
    print(f"coverage report: {coverage_path}", flush=True)


if __name__ == "__main__":
    main()
