#!/usr/bin/env python3
"""Enrich CVF normalized/raw records with abstracts from official detail pages."""

from __future__ import annotations

import argparse
import html
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aicpl.util import fetch_text, now_utc, read_json, write_json  # noqa: E402


def clean(value: str) -> str:
    value = html.unescape(re.sub(r"<.*?>", " ", value or ""))
    return " ".join(value.split()).strip()


def fetch_abstract(record: dict[str, Any], timeout: int) -> tuple[str, str]:
    text = fetch_text(record["paper_url"], timeout=timeout, retries=1)
    abstract_match = re.search(r'<div id="abstract"[^>]*>\s*(?P<abstract>.*?)\s*</div>', text, re.S)
    return record["id"], clean(abstract_match.group("abstract")) if abstract_match else ""


def update_records(records: list[dict[str, Any]], abstract_by_id: dict[str, str], fetched_at: str) -> int:
    updated = 0
    for record in records:
        abstract = abstract_by_id.get(record["id"])
        if not abstract or record.get("abstract") == abstract:
            continue
        record["abstract"] = abstract
        record.setdefault("source", {})["fetched_at"] = fetched_at
        updated += 1
    return updated


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--conference", required=True, choices=["cvpr", "iccv", "wacv"])
    parser.add_argument("--year", required=True, type=int)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--timeout", type=int, default=15)
    parser.add_argument("--limit", type=int, default=0, help="Maximum missing abstracts to fetch. Default: all.")
    parser.add_argument(
        "--flush-every",
        type=int,
        default=250,
        help="Write fetched abstracts every N completed requests. Use 0 to write only at the end.",
    )
    args = parser.parse_args()

    normalized_path = ROOT / "data" / "normalized" / args.conference / f"{args.conference}{args.year}.json"
    raw_path = ROOT / "data" / "raw" / "cvf" / args.conference / f"{args.conference}{args.year}.json"
    normalized = read_json(normalized_path)
    raw = read_json(raw_path)

    candidates = [
        record
        for record in normalized.get("records", [])
        if record.get("paper_url") and not record.get("abstract")
    ]
    if args.limit:
        candidates = candidates[: args.limit]

    pending_abstracts: dict[str, str] = {}
    fetched_at = now_utc()
    fetched_abstracts = 0
    failures = 0
    normalized_updated = 0
    raw_updated = 0

    def flush_updates() -> None:
        nonlocal normalized_updated, raw_updated
        if not pending_abstracts:
            return
        normalized_delta = update_records(normalized.get("records", []), pending_abstracts, fetched_at)
        raw_delta = update_records(raw.get("records", []), pending_abstracts, fetched_at)
        if normalized_delta or raw_delta:
            normalized["fetched_at"] = fetched_at
            raw["fetched_at"] = fetched_at
            write_json(normalized_path, normalized)
            write_json(raw_path, raw)
            normalized_updated += normalized_delta
            raw_updated += raw_delta
        pending_abstracts.clear()

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = [executor.submit(fetch_abstract, record, args.timeout) for record in candidates]
        for index, future in enumerate(as_completed(futures), start=1):
            try:
                record_id, abstract = future.result()
            except Exception:  # noqa: BLE001 - summarize failures and keep useful fetched abstracts.
                failures += 1
            else:
                if abstract:
                    pending_abstracts[record_id] = abstract
                    fetched_abstracts += 1
            if args.flush_every and index % args.flush_every == 0:
                flush_updates()
            if index % 100 == 0 or index == len(futures):
                print(
                    f"fetched={index}/{len(futures)} abstracts={fetched_abstracts} failures={failures}",
                    flush=True,
                )

    flush_updates()

    print(
        f"updated normalized={normalized_updated} raw={raw_updated} failures={failures} "
        f"output={normalized_path}",
        flush=True,
    )


if __name__ == "__main__":
    main()
