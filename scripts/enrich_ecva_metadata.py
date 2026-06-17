#!/usr/bin/env python3
"""Enrich ECVA/ECCV records from official virtual paper pages."""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any
from urllib.parse import urljoin


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aicpl.util import fetch_text, now_utc, read_json, write_json  # noqa: E402


def clean(value: str) -> str:
    value = html.unescape(re.sub(r"<.*?>", " ", value or ""))
    return " ".join(value.split()).strip()


def parse_json_ld_authors(text: str) -> list[str]:
    for match in re.finditer(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(?P<json>.*?)</script>',
        text,
        re.S | re.I,
    ):
        try:
            payload = json.loads(html.unescape(match.group("json")).strip())
        except json.JSONDecodeError:
            continue
        authors = payload.get("author", [])
        if not isinstance(authors, list):
            continue
        names = []
        for author in authors:
            if isinstance(author, dict):
                name = clean(str(author.get("name", "")))
            else:
                name = clean(str(author))
            if name:
                names.append(name)
        if names:
            return names
    return []


def parse_organizer_authors(text: str) -> list[str]:
    match = re.search(r'<div class="event-organizers">(?P<authors>.*?)</div>', text, re.S | re.I)
    if not match:
        return []
    return [clean(part) for part in re.split(r"\s*[⋅·]\s*", match.group("authors")) if clean(part)]


def parse_first_link(text: str, patterns: list[str]) -> str:
    for href in re.findall(r'<a\b[^>]+href=["\'](?P<href>[^"\']+)["\']', text, re.I):
        href = html.unescape(href)
        lower = href.lower()
        if all(pattern in lower for pattern in patterns):
            return href
    return ""


def parse_project_link(text: str) -> str:
    match = re.search(
        r'<a\b(?=[^>]*class=["\'][^"\']*\bproject\b)(?=[^>]*href=["\'](?P<href>[^"\']+)["\'])',
        text,
        re.I,
    )
    return html.unescape(match.group("href")) if match else ""


def parse_metadata(record: dict[str, Any], timeout: int) -> tuple[str, dict[str, Any]]:
    source_url = record["paper_url"]
    text = fetch_text(source_url, timeout=timeout, retries=1)
    abstract_match = re.search(
        r'<div class="abstract-text-inner">\s*(?P<abstract>.*?)\s*</div>',
        text,
        re.S | re.I,
    )
    pdf_url = parse_first_link(text, ["papers_eccv/papers/", ".pdf"])
    if "-supp.pdf" in pdf_url.lower():
        pdf_url = ""
    project_url = parse_project_link(text)
    github_url = project_url if "github.com" in project_url.lower() else ""
    return (
        record["id"],
        {
            "abstract": clean(abstract_match.group("abstract")) if abstract_match else "",
            "authors": parse_json_ld_authors(text) or parse_organizer_authors(text),
            "pdf_url": urljoin(source_url, pdf_url) if pdf_url else "",
            "project_url": urljoin(source_url, project_url) if project_url else "",
            "github_url": github_url,
        },
    )


def update_records(records: list[dict[str, Any]], metadata_by_id: dict[str, dict[str, Any]], fetched_at: str) -> int:
    updated = 0
    for record in records:
        metadata = metadata_by_id.get(record["id"])
        if not metadata:
            continue
        before = {
            "abstract": record.get("abstract", ""),
            "authors": record.get("authors", []),
            "pdf_url": record.get("pdf_url", ""),
            "project_url": record.get("project_url", ""),
            "github_url": record.get("github_url", ""),
        }
        for field in ("abstract", "pdf_url", "project_url", "github_url"):
            if metadata.get(field):
                record[field] = metadata[field]
        if metadata.get("authors"):
            record["authors"] = metadata["authors"]
        after = {
            "abstract": record.get("abstract", ""),
            "authors": record.get("authors", []),
            "pdf_url": record.get("pdf_url", ""),
            "project_url": record.get("project_url", ""),
            "github_url": record.get("github_url", ""),
        }
        if before != after:
            record.setdefault("source", {})["fetched_at"] = fetched_at
            updated += 1
    return updated


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", required=True, type=int, choices=[2024])
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--timeout", type=int, default=20)
    parser.add_argument("--limit", type=int, default=0, help="Maximum records to fetch. Default: all missing metadata.")
    args = parser.parse_args()

    normalized_path = ROOT / "data" / "normalized" / "eccv" / f"eccv{args.year}.json"
    raw_path = ROOT / "data" / "raw" / "ecva" / "eccv" / f"eccv{args.year}.json"
    normalized = read_json(normalized_path)
    raw = read_json(raw_path)

    candidates = [
        record
        for record in normalized.get("records", [])
        if record.get("paper_url")
        and (
            not record.get("abstract")
            or not record.get("authors")
            or not record.get("pdf_url")
        )
    ]
    if args.limit:
        candidates = candidates[: args.limit]

    metadata_by_id: dict[str, dict[str, Any]] = {}
    failures = 0
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = [executor.submit(parse_metadata, record, args.timeout) for record in candidates]
        for index, future in enumerate(as_completed(futures), start=1):
            try:
                record_id, metadata = future.result()
            except Exception:  # noqa: BLE001 - summarize failures and keep useful metadata.
                failures += 1
            else:
                metadata_by_id[record_id] = metadata
            if index % 100 == 0 or index == len(futures):
                abstracts = sum(bool(item.get("abstract")) for item in metadata_by_id.values())
                pdfs = sum(bool(item.get("pdf_url")) for item in metadata_by_id.values())
                authors = sum(bool(item.get("authors")) for item in metadata_by_id.values())
                print(
                    f"fetched={index}/{len(futures)} abstracts={abstracts} pdfs={pdfs} "
                    f"authors={authors} failures={failures}",
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
