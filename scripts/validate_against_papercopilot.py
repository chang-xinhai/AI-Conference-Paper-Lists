#!/usr/bin/env python3
"""Compare a normalized harvest against Paper Copilot for the same venue/year."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aicpl.issues import issues_for  # noqa: E402
from aicpl.sources import papercopilot  # noqa: E402
from aicpl.util import read_json, write_json  # noqa: E402
from aicpl.validation import compare_records, no_baseline_report  # noqa: E402


def is_accepted_like(record: dict) -> bool:
    status = str(record.get("status") or "").lower()
    if any(token in status for token in ["reject", "withdraw", "desk"]):
        return False
    return True


def load_papercopilot_records(venue_key: str, year: int, local_repo: str | None) -> list[dict]:
    if local_repo:
        path = papercopilot.path_for(venue_key, year)
        blob = subprocess.check_output(["git", "show", f"HEAD:{path}"], cwd=local_repo)
        rows = json.loads(blob)
    else:
        rows = papercopilot.load(venue_key, year)
    return [record for record in papercopilot.normalize(venue_key, year, rows) if is_accepted_like(record)]


def known_baseline_issues_for(venue_key: str, year: int) -> list[dict]:
    return issues_for(ROOT / "config" / "baseline_issues.json", venue_key, year)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--conference", required=True)
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--normalized-dir", default="data/normalized")
    parser.add_argument("--reports-dir", default="data/reports")
    parser.add_argument("--paperlists", default="", help="Optional local papercopilot/paperlists checkout")
    parser.add_argument("--min-count-ratio", type=float, default=0.95)
    args = parser.parse_args()

    venue_key = args.conference.lower()
    normalized_path = ROOT / args.normalized_dir / venue_key / f"{venue_key}{args.year}.json"
    normalized = read_json(normalized_path)
    try:
        baseline = load_papercopilot_records(venue_key, args.year, args.paperlists or None)
    except Exception:
        report = no_baseline_report(
            venue_key=venue_key,
            year=args.year,
            source_name=normalized.get("source", ""),
            records=normalized["records"],
            min_count_ratio=args.min_count_ratio,
            known_baseline_issues=known_baseline_issues_for(venue_key, args.year),
        )
    else:
        report = compare_records(
            venue_key=venue_key,
            year=args.year,
            source_name=normalized.get("source", ""),
            records=normalized["records"],
            baseline_records=baseline,
            min_count_ratio=args.min_count_ratio,
            known_baseline_issues=known_baseline_issues_for(venue_key, args.year),
        )
    report_path = ROOT / args.reports_dir / venue_key / f"{venue_key}{args.year}.json"
    write_json(report_path, report)
    print(
        f"{venue_key}{args.year}: {report['status']} "
        f"ours={report['counts']['ours']} baseline={report['counts']['baseline']} "
        f"overlap={report['counts']['title_overlap']}"
    )
    print(f"report: {report_path}")
    if report["status"] == "needs_attention":
        sys.exit(2)


if __name__ == "__main__":
    main()
