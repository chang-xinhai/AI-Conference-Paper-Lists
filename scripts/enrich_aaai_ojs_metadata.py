#!/usr/bin/env python3
"""Enrich AAAI OJS normalized/raw records from official article metadata pages."""

from __future__ import annotations

import argparse
import html
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from html.parser import HTMLParser
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aicpl.util import fetch_text, now_utc, read_json, write_json  # noqa: E402


class MetaParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.meta: dict[str, list[str]] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "meta":
            return
        values = {name.lower(): value or "" for name, value in attrs}
        name = values.get("name")
        content = values.get("content")
        if not name or content is None:
            return
        self.meta.setdefault(name.lower(), []).append(html.unescape(content).strip())


def fetch_metadata(record: dict[str, Any], timeout: int) -> tuple[str, dict[str, Any]]:
    text = fetch_text(record["paper_url"], timeout=timeout, retries=1)
    parser = MetaParser()
    parser.feed(text)
    meta = parser.meta
    metadata = {
        "abstract": (meta.get("dc.description") or [""])[0],
        "authors": meta.get("citation_author", []),
        "affiliations": meta.get("citation_author_institution", []),
        "doi": (meta.get("citation_doi") or [""])[0],
        "pdf_url": (meta.get("citation_pdf_url") or [""])[0],
    }
    return record["id"], metadata


def update_records(records: list[dict[str, Any]], metadata_by_id: dict[str, dict[str, Any]], fetched_at: str) -> int:
    updated = 0
    for record in records:
        metadata = metadata_by_id.get(record["id"])
        if not metadata:
            continue
        before = {
            "abstract": record.get("abstract", ""),
            "authors": record.get("authors", []),
            "affiliations": record.get("affiliations", []),
            "first_institute": record.get("first_institute", ""),
            "doi": record.get("doi", ""),
            "pdf_url": record.get("pdf_url", ""),
        }
        if metadata.get("abstract"):
            record["abstract"] = metadata["abstract"]
        if metadata.get("authors"):
            record["authors"] = metadata["authors"]
        if metadata.get("affiliations"):
            record["affiliations"] = metadata["affiliations"]
            record["first_institute"] = metadata["affiliations"][0]
        if metadata.get("doi"):
            record["doi"] = metadata["doi"]
        if metadata.get("pdf_url"):
            record["pdf_url"] = metadata["pdf_url"]
        after = {
            "abstract": record.get("abstract", ""),
            "authors": record.get("authors", []),
            "affiliations": record.get("affiliations", []),
            "first_institute": record.get("first_institute", ""),
            "doi": record.get("doi", ""),
            "pdf_url": record.get("pdf_url", ""),
        }
        if before != after:
            record.setdefault("source", {})["fetched_at"] = fetched_at
            updated += 1
    return updated


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", required=True, type=int)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--timeout", type=int, default=20)
    parser.add_argument("--limit", type=int, default=0, help="Maximum records to fetch. Default: all missing abstracts.")
    args = parser.parse_args()

    normalized_path = ROOT / "data" / "normalized" / "aaai" / f"aaai{args.year}.json"
    raw_path = ROOT / "data" / "raw" / "aaai_ojs" / "aaai" / f"aaai{args.year}.json"
    normalized = read_json(normalized_path)
    raw = read_json(raw_path)

    candidates = [
        record
        for record in normalized.get("records", [])
        if record.get("paper_url")
        and (
            not record.get("abstract")
            or not record.get("doi")
            or not record.get("first_institute")
        )
    ]
    if args.limit:
        candidates = candidates[: args.limit]

    metadata_by_id: dict[str, dict[str, Any]] = {}
    failures = 0
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = [executor.submit(fetch_metadata, record, args.timeout) for record in candidates]
        for index, future in enumerate(as_completed(futures), start=1):
            try:
                record_id, metadata = future.result()
            except Exception:  # noqa: BLE001 - summarize failures and keep useful metadata.
                failures += 1
            else:
                metadata_by_id[record_id] = metadata
            if index % 100 == 0 or index == len(futures):
                abstracts = sum(bool(item.get("abstract")) for item in metadata_by_id.values())
                institutes = sum(bool(item.get("affiliations")) for item in metadata_by_id.values())
                print(
                    f"fetched={index}/{len(futures)} abstracts={abstracts} "
                    f"institutes={institutes} failures={failures}",
                    flush=True,
                )

    fetched_at = now_utc()
    normalized_updated = update_records(normalized.get("records", []), metadata_by_id, fetched_at)
    raw_updated = update_records(raw.get("records", []), metadata_by_id, fetched_at)
    normalized["fetched_at"] = fetched_at
    raw["fetched_at"] = fetched_at
    write_json(normalized_path, normalized)
    write_json(raw_path, raw)

    print(
        f"updated normalized={normalized_updated} raw={raw_updated} failures={failures} "
        f"output={normalized_path}",
        flush=True,
    )


if __name__ == "__main__":
    main()
