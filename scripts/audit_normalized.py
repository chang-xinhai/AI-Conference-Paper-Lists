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

from aicpl.util import now_utc, read_json, stable_id, write_json  # noqa: E402


FRONT_MATTER_TITLES = {
    "author index",
    "back cover",
    "committee",
    "conference committee",
    "conference information",
    "conference title page",
    "contents",
    "copyright",
    "cover page",
    "editorial board",
    "emergency reviewers",
    "front cover",
    "foreword",
    "index of papers",
    "organising committee",
    "organizing committee",
    "preface",
    "program",
    "program committee",
    "reviewers",
    "session index",
    "sponsors",
    "sponsors and partners",
    "statistics",
    "steering committee",
    "table of contents",
    "title page",
    "welcome",
    "welcome message",
    "welcome page",
}

FRONT_MATTER_PATTERNS = [
    re.compile(r"^message from (the )?.*chairs?$"),
    re.compile(r"^.*conference committee$"),
    re.compile(r"^.*program committee$"),
]


def canonical_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()


def strip_venue_tokens(title: str, venue_key: str, year: int) -> str:
    stripped = title
    tokens = {venue_key, str(year)}
    if venue_key == "nips":
        tokens.add("neurips")
    for token in tokens:
        stripped = re.sub(rf"\b{re.escape(token)}\b", " ", stripped)
    return re.sub(r"\s+", " ", stripped).strip()


def is_front_matter_title(title: str, venue_key: str, year: int) -> bool:
    canonical = strip_venue_tokens(canonical_title(title), venue_key, year)
    return canonical in FRONT_MATTER_TITLES or any(
        pattern.match(canonical) for pattern in FRONT_MATTER_PATTERNS
    )


def malformed_url(value: object) -> bool:
    if not value:
        return False
    text = str(value).strip()
    return not (text.startswith("http://") or text.startswith("https://"))


def issue_samples(records: list[dict], predicate, *, limit: int = 20) -> list[dict]:
    samples = []
    for index, record in enumerate(records):
        if predicate(record):
            samples.append(
                {
                    "index": index,
                    "id": record.get("id", ""),
                    "title": str(record.get("title") or "")[:160],
                }
            )
        if len(samples) >= limit:
            break
    return samples


def source_name(record: dict) -> str:
    source = record.get("source")
    if not isinstance(source, dict):
        return ""
    return str(source.get("name") or "")


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

    record_id_mismatches = issue_samples(
        records,
        lambda record: record.get("id")
        != stable_id(venue_key, year, str(record.get("title") or "")),
    )
    if record_id_mismatches:
        result["critical"].append(
            {
                "id": "record_id_mismatches",
                "count": sum(
                    1
                    for record in records
                    if record.get("id")
                    != stable_id(venue_key, year, str(record.get("title") or ""))
                ),
                "samples": record_id_mismatches,
            }
        )

    venue_key_mismatches = issue_samples(
        records,
        lambda record: record.get("venue_key") != venue_key,
    )
    if venue_key_mismatches:
        result["critical"].append(
            {
                "id": "record_venue_key_mismatches",
                "count": sum(1 for record in records if record.get("venue_key") != venue_key),
                "samples": venue_key_mismatches,
            }
        )

    year_mismatches = issue_samples(records, lambda record: record.get("year") != year)
    if year_mismatches:
        result["critical"].append(
            {
                "id": "record_year_mismatches",
                "count": sum(1 for record in records if record.get("year") != year),
                "samples": year_mismatches,
            }
        )

    blank_title_count = sum(1 for record in records if not str(record.get("title") or "").strip())
    if blank_title_count:
        result["critical"].append({"id": "blank_titles", "count": blank_title_count})

    front_matter_titles = [
        str(record.get("title") or "")
        for record in records
        if is_front_matter_title(str(record.get("title") or ""), venue_key, year)
    ]
    if front_matter_titles:
        result["critical"].append(
            {
                "id": "front_matter_titles",
                "count": len(front_matter_titles),
                "samples": front_matter_titles[:20],
            }
        )

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

    records_without_source = sum(1 for record in records if not source_name(record))
    if records_without_source:
        result["critical"].append(
            {
                "id": "records_without_source",
                "count": records_without_source,
            }
        )

    non_dict_sources = issue_samples(records, lambda record: not isinstance(record.get("source"), dict))
    if non_dict_sources:
        result["critical"].append(
            {
                "id": "non_dict_sources",
                "count": sum(1 for record in records if not isinstance(record.get("source"), dict)),
                "samples": non_dict_sources,
            }
        )

    for field in ["authors", "affiliations", "keywords"]:
        bad_values = issue_samples(
            records,
            lambda record, field=field: not isinstance(record.get(field), list),
        )
        if bad_values:
            result["critical"].append(
                {
                    "id": f"non_list_{field}",
                    "count": sum(1 for record in records if not isinstance(record.get(field), list)),
                    "samples": bad_values,
                }
            )

    abstract_in_authors = issue_samples(
        records,
        lambda record: bool(record.get("abstract"))
        and any(str(record.get("abstract") or "")[:80] in str(author) for author in record.get("authors", [])),
    )
    if abstract_in_authors:
        result["critical"].append(
            {
                "id": "abstract_text_in_authors",
                "count": sum(
                    1
                    for record in records
                    if record.get("abstract")
                    and any(
                        str(record.get("abstract") or "")[:80] in str(author)
                        for author in record.get("authors", [])
                    )
                ),
                "samples": abstract_in_authors,
            }
        )

    for field in ["paper_url", "pdf_url", "arxiv_url", "project_url", "github_url"]:
        bad_urls = issue_samples(records, lambda record, field=field: malformed_url(record.get(field)))
        if bad_urls:
            result["critical"].append(
                {
                    "id": f"malformed_{field}",
                    "count": sum(1 for record in records if malformed_url(record.get(field))),
                    "samples": bad_urls,
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
