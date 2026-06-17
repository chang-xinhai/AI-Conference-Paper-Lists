#!/usr/bin/env python3
"""Audit normalized records for structural data quality."""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aicpl.util import now_utc, read_json, write_json  # noqa: E402


def canonical_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()


def audit_year(venue_key: str, year: int) -> dict:
    path = ROOT / "data" / "normalized" / venue_key / f"{venue_key}{year}.json"
    result = {
        "venue_key": venue_key,
        "year": year,
        "path": str(path.relative_to(ROOT)),
        "status": "ok",
        "source": "",
        "count": 0,
        "critical": [],
        "warnings": [],
    }
    if not path.exists():
        result["status"] = "critical"
        result["critical"].append("missing_normalized_file")
        return result

    data = read_json(path)
    records = data.get("records", [])
    result["source"] = data.get("source", "")
    result["count"] = len(records)
    declared_count = data.get("count")
    if declared_count != len(records):
        result["critical"].append(
            {
                "id": "count_mismatch",
                "declared": declared_count,
                "actual": len(records),
            }
        )
    if not result["source"]:
        result["critical"].append("blank_source")

    blank_title_count = sum(1 for record in records if not str(record.get("title") or "").strip())
    if blank_title_count:
        result["critical"].append({"id": "blank_titles", "count": blank_title_count})

    titles = [
        canonical_title(str(record.get("title") or ""))
        for record in records
        if str(record.get("title") or "").strip()
    ]
    duplicate_titles = sorted(title for title, count in Counter(titles).items() if count > 1)
    if duplicate_titles:
        result["warnings"].append(
            {
                "id": "duplicate_canonical_titles",
                "count": len(duplicate_titles),
                "samples": duplicate_titles[:20],
            }
        )

    records_without_source = sum(1 for record in records if not (record.get("source") or {}).get("name"))
    if records_without_source:
        result["critical"].append(
            {
                "id": "records_without_source",
                "count": records_without_source,
            }
        )

    if result["critical"]:
        result["status"] = "critical"
    elif result["warnings"]:
        result["status"] = "warning"
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="data/reports/data_quality.json")
    parser.add_argument("--no-fail", action="store_true")
    args = parser.parse_args()

    index = read_json(ROOT / "config" / "conferences.json")
    results = [
        audit_year(conference["key"], year)
        for conference in index["conferences"]
        for year in conference["target_years"]
    ]
    critical = [result for result in results if result["critical"]]
    warnings = [result for result in results if result["warnings"]]
    report = {
        "schema_version": "0.1",
        "generated_at": now_utc(),
        "target_count": len(results),
        "status": "critical" if critical else "warning" if warnings else "ok",
        "summary": {
            "ok": sum(1 for result in results if result["status"] == "ok"),
            "warning": sum(1 for result in results if result["status"] == "warning"),
            "critical": sum(1 for result in results if result["status"] == "critical"),
        },
        "results": results,
    }
    write_json(ROOT / args.output, report)
    print(
        "data quality: "
        f"targets={report['target_count']} "
        f"ok={report['summary']['ok']} "
        f"warning={report['summary']['warning']} "
        f"critical={report['summary']['critical']}"
    )
    print(f"report: {ROOT / args.output}")
    if critical and not args.no_fail:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
