#!/usr/bin/env python3
"""Audit Paper Copilot validation statuses from the coverage report."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aicpl.util import now_utc, read_json, write_json  # noqa: E402


def validation_item(result: dict) -> dict:
    return {
        "venue_key": result.get("venue_key", ""),
        "year": result.get("year"),
        "source": result.get("source", ""),
        "validation_status": result.get("validation_status", ""),
        "validation_counts": result.get("validation_counts", {}),
        "known_baseline_issues": result.get("validation_known_baseline_issues", []),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="data/reports/validation_audit.json")
    parser.add_argument("--no-fail", action="store_true")
    args = parser.parse_args()

    coverage = read_json(ROOT / "data" / "reports" / "coverage.json")
    results = coverage.get("results", [])

    needs_attention = [
        validation_item(result)
        for result in results
        if result.get("validation_status") == "needs_attention"
    ]
    unexplained_title_drift = [
        validation_item(result)
        for result in results
        if result.get("validation_status") == "title_drift"
        and not result.get("validation_known_baseline_issues")
    ]
    known_title_drift = [
        validation_item(result)
        for result in results
        if result.get("validation_status") == "title_drift"
        and result.get("validation_known_baseline_issues")
    ]

    critical = needs_attention + unexplained_title_drift
    report = {
        "schema_version": "0.1",
        "generated_at": now_utc(),
        "coverage_report": "data/reports/coverage.json",
        "status": "critical" if critical else "warning" if known_title_drift else "ok",
        "summary": {
            "needs_attention_count": len(needs_attention),
            "unexplained_title_drift_count": len(unexplained_title_drift),
            "known_title_drift_count": len(known_title_drift),
        },
        "needs_attention": needs_attention,
        "unexplained_title_drift": unexplained_title_drift,
        "known_title_drift": known_title_drift,
    }
    output = ROOT / args.output
    write_json(output, report)
    print(f"validation audit: status={report['status']} summary={report['summary']}")
    print(f"report: {output}")
    if critical and not args.no_fail:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
