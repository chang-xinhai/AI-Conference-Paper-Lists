"""COLT official accepted-paper page harvester."""

from __future__ import annotations

import html
import re
from typing import Any
from urllib.parse import urljoin

from ..schema import empty_record, venue_name
from ..util import fetch_text, now_utc


ACCEPTED_PAGES = {
    2026: "https://learningtheory.org/colt2026/accepted.html",
}


def supports(venue_key: str, year: int) -> bool:
    return venue_key == "colt" and year in ACCEPTED_PAGES


def _clean(text: str) -> str:
    text = html.unescape(re.sub(r"<.*?>", " ", text or ""))
    return re.sub(r"\s+", " ", text).strip()


def harvest(venue_key: str, year: int) -> dict[str, Any]:
    if not supports(venue_key, year):
        raise ValueError(f"COLT accepted-page route unsupported for {venue_key}{year}")

    url = ACCEPTED_PAGES[year]
    text = fetch_text(url, timeout=90, retries=6)
    fetched_at = now_utc()

    records = []
    pattern = re.compile(
        r"<li>\s*<b>(?P<title>.*?)</b>\s*<br\s*/?>\s*(?P<authors>.*?)</li>",
        re.I | re.S,
    )
    for match in pattern.finditer(text):
        title = _clean(match.group("title"))
        if not title:
            continue
        record = empty_record(venue_key, venue_name(venue_key), year, title)
        record["authors"] = [
            author.strip()
            for author in _clean(match.group("authors")).split(",")
            if author.strip()
        ]
        record["paper_url"] = urljoin(url, "#accepted")
        record["source"] = {
            "name": "COLT Accepted Papers",
            "url": url,
            "fetched_at": fetched_at,
            "license": "",
        }
        records.append(record)

    return {
        "source": "colt",
        "venue_key": venue_key,
        "year": year,
        "source_url": url,
        "fetched_at": fetched_at,
        "raw_count": len(records),
        "records": records,
    }
