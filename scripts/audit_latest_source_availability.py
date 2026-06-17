#!/usr/bin/env python3
"""Fail when a probed complete official source is available but unharvested."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aicpl.util import now_utc, read_json, write_json  # noqa: E402


def harvested_targets(coverage_results: list[dict]) -> set[tuple[str, int]]:
    return {
        (result.get("venue_key", ""), int(result.get("year")))
        for result in coverage_results
        if result.get("status") == "harvested"
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="data/reports/latest_source_audit.json")
    parser.add_argument("--no-fail", action="store_true")
    args = parser.parse_args()

    latest = read_json(ROOT / "data" / "reports" / "latest_source_probes.json")
    coverage = read_json(ROOT / "data" / "reports" / "coverage.json")
    harvested = harvested_targets(coverage.get("results", []))

    unharvested_available = []
    reachable_without_parser = []
    for result in latest.get("results", []):
        venue_key = result.get("venue_key", "")
        year = result.get("year")
        target = (venue_key, int(year)) if year is not None else ("", 0)
        item = {
            "id": result.get("id", ""),
            "venue_key": venue_key,
            "year": year,
            "status": result.get("status", ""),
            "evidence": result.get("evidence", ""),
        }
        if result.get("status") == "available" and target not in harvested:
            unharvested_available.append(item)
        if result.get("status") == "reachable" and target not in harvested:
            reachable_without_parser.append(item)

    critical = unharvested_available + reachable_without_parser
    report = {
        "schema_version": "0.1",
        "generated_at": now_utc(),
        "latest_source_probe": "data/reports/latest_source_probes.json",
        "coverage_report": "data/reports/coverage.json",
        "status": "critical" if critical else "ok",
        "summary": {
            "unharvested_available_count": len(unharvested_available),
            "reachable_without_parser_count": len(reachable_without_parser),
        },
        "unharvested_available": unharvested_available,
        "reachable_without_parser": reachable_without_parser,
    }
    output = ROOT / args.output
    write_json(output, report)
    print(f"latest source audit: status={report['status']} summary={report['summary']}")
    print(f"report: {output}")
    if critical and not args.no_fail:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
