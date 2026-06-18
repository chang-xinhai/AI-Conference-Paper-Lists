#!/usr/bin/env python3
"""Enrich normalized/raw records with high-confidence arXiv matches."""

from __future__ import annotations

import argparse
import re
import sys
import time
import unicodedata
import urllib.parse
import xml.etree.ElementTree as ET
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aicpl.util import fetch_text, now_utc, read_json, write_json  # noqa: E402


ARXIV_API_URL = "https://export.arxiv.org/api/query"
ARXIV_SOURCE_URL = "https://export.arxiv.org/api/query?search_query=ti:<paper-title>"
ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}


def compact_title(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    return " ".join(re.findall(r"[a-z0-9]+", ascii_text.lower()))


def title_score(left: str, right: str) -> float:
    left_norm = compact_title(left)
    right_norm = compact_title(right)
    if not left_norm or not right_norm:
        return 0.0
    if left_norm == right_norm:
        return 1.0
    return SequenceMatcher(None, left_norm, right_norm).ratio()


def surname(value: str) -> str:
    tokens = re.findall(r"[a-z]+", unicodedata.normalize("NFKD", value or "").lower())
    return tokens[-1] if tokens else ""


def author_check(record_authors: list[str], arxiv_authors: list[str]) -> dict[str, Any]:
    record_surnames = [name for name in (surname(author) for author in record_authors) if name]
    arxiv_surnames = [name for name in (surname(author) for author in arxiv_authors) if name]
    if not record_surnames or not arxiv_surnames:
        return {
            "ok": True,
            "overlap": 0,
            "required_overlap": 0,
            "record_surnames": record_surnames,
            "arxiv_surnames": arxiv_surnames,
        }

    overlap = len(set(record_surnames) & set(arxiv_surnames))
    required = 1 if min(len(record_surnames), len(arxiv_surnames)) <= 2 else 2
    first_author_match = record_surnames[0] == arxiv_surnames[0]
    return {
        "ok": overlap >= required or first_author_match,
        "overlap": overlap,
        "required_overlap": required,
        "first_author_match": first_author_match,
        "record_surnames": record_surnames[:8],
        "arxiv_surnames": arxiv_surnames[:8],
    }


def query_url(title: str, max_results: int) -> str:
    params = {
        "search_query": f'ti:"{title}"',
        "start": "0",
        "max_results": str(max_results),
        "sortBy": "relevance",
        "sortOrder": "descending",
    }
    return f"{ARXIV_API_URL}?{urllib.parse.urlencode(params)}"


def arxiv_abs_url(entry_id: str) -> str:
    match = re.search(r"/abs/([^/?#]+)", entry_id or "")
    if not match:
        return ""
    arxiv_id = re.sub(r"v\d+$", "", match.group(1))
    return f"https://arxiv.org/abs/{arxiv_id}"


def text_of(entry: ET.Element, name: str) -> str:
    value = entry.findtext(f"atom:{name}", default="", namespaces=ATOM_NS)
    return " ".join(value.split()).strip()


def parse_feed(text: str) -> list[dict[str, Any]]:
    root = ET.fromstring(text)
    candidates: list[dict[str, Any]] = []
    for entry in root.findall("atom:entry", ATOM_NS):
        authors = [
            text_of(author, "name")
            for author in entry.findall("atom:author", ATOM_NS)
            if text_of(author, "name")
        ]
        candidates.append(
            {
                "id": text_of(entry, "id"),
                "title": text_of(entry, "title"),
                "summary": text_of(entry, "summary"),
                "published": text_of(entry, "published"),
                "updated": text_of(entry, "updated"),
                "authors": authors,
                "arxiv_url": arxiv_abs_url(text_of(entry, "id")),
            }
        )
    return candidates


def load_cache(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "schema_version": "0.1",
            "source": "arxiv",
            "source_url": ARXIV_API_URL,
            "fetched_at": "",
            "queries": [],
        }
    return read_json(path)


def cache_by_record(cache: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(item.get("record_id")): item
        for item in cache.get("queries", [])
        if item.get("record_id")
    }


def choose_match(record: dict[str, Any], candidates: list[dict[str, Any]]) -> dict[str, Any]:
    scored: list[dict[str, Any]] = []
    for candidate in candidates:
        score = title_score(record.get("title", ""), candidate.get("title", ""))
        check = author_check(record.get("authors", []), candidate.get("authors", []))
        published_year = int((candidate.get("published") or "0000")[:4] or 0)
        scored.append(
            {
                **candidate,
                "title_score": round(score, 6),
                "author_check": check,
                "published_year": published_year,
            }
        )

    exact = [candidate for candidate in scored if candidate["title_score"] == 1.0]
    unique_urls = {candidate.get("arxiv_url") for candidate in exact if candidate.get("arxiv_url")}
    if not exact:
        return {
            "status": "rejected",
            "reason": "no_exact_title_match",
            "candidates": scored,
        }
    if len(unique_urls) != 1:
        return {
            "status": "ambiguous",
            "reason": "multiple_exact_title_matches",
            "candidates": exact,
        }

    candidate = exact[0]
    if not candidate.get("author_check", {}).get("ok"):
        return {
            "status": "rejected",
            "reason": "author_mismatch",
            "candidates": exact,
        }
    if candidate.get("published_year", 0) > int(record.get("year") or 0) + 1:
        return {
            "status": "rejected",
            "reason": "future_arxiv_year",
            "candidates": exact,
        }
    return {
        "status": "matched",
        "reason": "exact_title_author_year_match",
        "match": candidate,
        "candidates": scored,
    }


def append_source_marker(value: str) -> str:
    if ARXIV_SOURCE_URL in (value or ""):
        return value
    return f"{value}; {ARXIV_SOURCE_URL}" if value else ARXIV_SOURCE_URL


def append_source_name(value: str) -> str:
    if "arXiv API" in (value or ""):
        return value
    return f"{value} + arXiv API" if value else "arXiv API"


def update_records(
    records: list[dict[str, Any]],
    matches: dict[str, dict[str, Any]],
    fetched_at: str,
) -> int:
    updated = 0
    for record in records:
        match = matches.get(record.get("id", ""))
        if not match:
            continue
        before = (
            record.get("arxiv_url", ""),
            record.get("abstract", ""),
            record.get("source", {}).get("name", ""),
            record.get("source", {}).get("url", ""),
        )
        if match.get("arxiv_url"):
            record["arxiv_url"] = match["arxiv_url"]
        if match.get("summary") and not record.get("abstract"):
            record["abstract"] = match["summary"]
        source = record.setdefault("source", {})
        source["name"] = append_source_name(str(source.get("name") or ""))
        source["url"] = append_source_marker(str(source.get("url") or ""))
        source["fetched_at"] = fetched_at
        after = (
            record.get("arxiv_url", ""),
            record.get("abstract", ""),
            record.get("source", {}).get("name", ""),
            record.get("source", {}).get("url", ""),
        )
        if before != after:
            updated += 1
    return updated


def find_raw_path(conference: str, year: int, raw_source: str | None, preferred_source: str) -> Path:
    filename = f"{conference}{year}.json"
    if raw_source:
        return ROOT / "data" / "raw" / raw_source / conference / filename
    if preferred_source:
        preferred = ROOT / "data" / "raw" / preferred_source / conference / filename
        if preferred.exists():
            return preferred
    candidates = sorted(
        path
        for path in (ROOT / "data" / "raw").glob(f"*/{conference}/{filename}")
        if path.parts[-3] != "arxiv_queries"
    )
    if len(candidates) != 1:
        raise SystemExit(
            "Could not infer raw source path; pass --raw-source. "
            f"Candidates: {', '.join(str(path) for path in candidates)}"
        )
    return candidates[0]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--conference", required=True)
    parser.add_argument("--year", required=True, type=int)
    parser.add_argument("--raw-source", default="")
    parser.add_argument("--limit", type=int, default=0, help="Maximum missing arXiv records to query. Default: all.")
    parser.add_argument("--max-results", type=int, default=5)
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--delay", type=float, default=3.0)
    parser.add_argument("--force", action="store_true", help="Re-query records already present in the cache.")
    parser.add_argument(
        "--retry-errors",
        action="store_true",
        help="Re-query cached records whose previous status was error.",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    normalized_path = ROOT / "data" / "normalized" / args.conference / f"{args.conference}{args.year}.json"
    normalized = read_json(normalized_path)
    raw_path = find_raw_path(
        args.conference,
        args.year,
        args.raw_source or None,
        str(normalized.get("source") or ""),
    )
    cache_path = ROOT / "data" / "raw" / "arxiv_queries" / args.conference / f"{args.conference}{args.year}.json"
    report_path = ROOT / "data" / "reports" / "arxiv" / args.conference / f"{args.conference}{args.year}.json"

    raw = read_json(raw_path)
    cache = load_cache(cache_path)
    cached = cache_by_record(cache)

    candidates = [
        record
        for record in normalized.get("records", [])
        if record.get("title") and not record.get("arxiv_url")
    ]
    if args.limit:
        candidates = candidates[: args.limit]

    queried = 0
    failures = 0
    fetched_at = now_utc()
    for index, record in enumerate(candidates, start=1):
        record_id = str(record.get("id"))
        cached_record = cached.get(record_id)
        should_retry_error = args.retry_errors and cached_record and cached_record.get("status") == "error"
        if not args.force and record_id in cached and not should_retry_error:
            continue
        url = query_url(str(record.get("title") or ""), args.max_results)
        query_record: dict[str, Any] = {
            "record_id": record_id,
            "title": record.get("title", ""),
            "authors": record.get("authors", []),
            "query_url": url,
            "queried_at": now_utc(),
        }
        try:
            feed = fetch_text(url, timeout=args.timeout, retries=2)
            candidates_from_feed = parse_feed(feed)
            decision = choose_match(record, candidates_from_feed)
            query_record.update(decision)
            queried += 1
        except Exception as error:  # noqa: BLE001 - keep the batch resumable.
            query_record.update(
                {
                    "status": "error",
                    "reason": type(error).__name__,
                    "error": str(error),
                    "candidates": [],
                }
            )
            failures += 1

        cached[record_id] = query_record
        cache["queries"] = list(cached.values())
        cache["fetched_at"] = fetched_at
        if not args.dry_run:
            write_json(cache_path, cache)
        if args.delay and index != len(candidates):
            time.sleep(args.delay)
        if index % 25 == 0 or index == len(candidates):
            matched_so_far = sum(1 for item in cached.values() if item.get("status") == "matched")
            print(
                f"processed={index}/{len(candidates)} queried={queried} "
                f"matched_cache={matched_so_far} failures={failures}",
                flush=True,
            )

    matches = {
        record_id: item["match"]
        for record_id, item in cached.items()
        if item.get("status") == "matched" and item.get("match", {}).get("arxiv_url")
    }
    normalized_updated = update_records(normalized.get("records", []), matches, fetched_at)
    raw_updated = update_records(raw.get("records", []), matches, fetched_at)
    if normalized_updated:
        normalized["source_url"] = append_source_marker(str(normalized.get("source_url") or ""))
        normalized["fetched_at"] = fetched_at
    if raw_updated:
        raw["source_url"] = append_source_marker(str(raw.get("source_url") or ""))
        raw["fetched_at"] = fetched_at

    summary = {
        "schema_version": "0.1",
        "venue_key": args.conference,
        "year": args.year,
        "source": "arxiv",
        "source_url": ARXIV_API_URL,
        "generated_at": fetched_at,
        "queried": len(cached),
        "current_run_queried": queried,
        "cached_queries": len(cached),
        "matched": len(matches),
        "normalized_updated": normalized_updated,
        "raw_updated": raw_updated,
        "failures": failures,
        "by_status": {},
        "by_reason": {},
    }
    for item in cached.values():
        status = str(item.get("status") or "unknown")
        reason = str(item.get("reason") or "unknown")
        summary["by_status"][status] = summary["by_status"].get(status, 0) + 1
        summary["by_reason"][reason] = summary["by_reason"].get(reason, 0) + 1

    if not args.dry_run:
        write_json(normalized_path, normalized)
        write_json(raw_path, raw)
        write_json(report_path, summary)

    print(
        f"updated normalized={normalized_updated} raw={raw_updated} "
        f"matches={len(matches)} queried={queried} failures={failures} "
        f"cache={cache_path} report={report_path}",
        flush=True,
    )


if __name__ == "__main__":
    main()
