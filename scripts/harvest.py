#!/usr/bin/env python3
"""Harvest one conference/year from an official or fallback source."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aicpl.harvesters import available_sources, harvest_with_source  # noqa: E402
from aicpl.util import read_json, write_json  # noqa: E402


def source_routes() -> dict:
    return read_json(ROOT / "config" / "sources.json")["routes"]


def choose_source(venue_key: str, year: int, requested: str) -> str:
    routes = source_routes()
    preferred = routes.get(venue_key, [])
    if requested != "auto":
        return requested
    official = [source for source in preferred if source != "papercopilot"]
    candidates = available_sources(venue_key, year, official)
    if candidates:
        return candidates[0]
    raise ValueError(
        f"No implemented official source for {venue_key}{year}. "
        "Use --source papercopilot only for fallback bootstrapping."
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--conference", required=True, help="Paper Copilot-compatible venue key")
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--source", default="auto", help="auto, openreview, cvf, acl_anthology, pmlr, rss, papercopilot")
    parser.add_argument("--raw-dir", default="data/raw")
    parser.add_argument("--normalized-dir", default="data/normalized")
    args = parser.parse_args()

    venue_key = args.conference.lower()
    source = choose_source(venue_key, args.year, args.source)
    payload = harvest_with_source(source, venue_key, args.year)

    raw_path = ROOT / args.raw_dir / source / venue_key / f"{venue_key}{args.year}.json"
    normalized_path = ROOT / args.normalized_dir / venue_key / f"{venue_key}{args.year}.json"
    write_json(raw_path, payload)
    write_json(
        normalized_path,
        {
            "schema_version": "0.1",
            "venue_key": venue_key,
            "year": args.year,
            "source": source,
            "source_url": payload["source_url"],
            "fetched_at": payload["fetched_at"],
            "count": len(payload["records"]),
            "records": payload["records"],
        },
    )
    print(f"{venue_key}{args.year}: harvested {len(payload['records'])} records from {source}")
    print(f"raw: {raw_path}")
    print(f"normalized: {normalized_path}")


if __name__ == "__main__":
    main()
