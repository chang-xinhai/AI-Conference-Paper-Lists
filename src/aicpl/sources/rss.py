"""RSS proceedings harvester."""

from __future__ import annotations

import html
import re
from typing import Any
from urllib.parse import urljoin

from ..schema import empty_record, venue_name
from ..util import fetch_text, now_utc


RSS_BASE = "https://www.roboticsproceedings.org"


def supports(venue_key: str, year: int) -> bool:
    return venue_key == "rss" and year >= 2020


def rss_number(year: int) -> int:
    # RSS 2005 was RSS I, so RSS 2024 is RSS XX.
    return year - 2004


def harvest(venue_key: str, year: int) -> dict[str, Any]:
    if not supports(venue_key, year):
        raise ValueError(f"RSS route unsupported for {venue_key}{year}")

    number = rss_number(year)
    url = f"{RSS_BASE}/rss{number}/"
    text = fetch_text(url, timeout=60)
    fetched_at = now_utc()

    row_pattern = re.compile(
        r'<a href="(?P<html>p\d+\.html)"[^>]*>(?P<title>.*?)</a><br>\s*'
        r"<i>(?P<authors>.*?)</i>.*?"
        r'<a href="(?P<pdf>p\d+\.pdf)"',
        re.S,
    )

    records = []
    for match in row_pattern.finditer(text):
        title = html.unescape(re.sub(r"\s+", " ", match.group("title")).strip())
        record = empty_record(venue_key, venue_name(venue_key), year, title)
        authors_text = html.unescape(re.sub(r"<.*?>", "", match.group("authors")))
        record["authors"] = [part.strip() for part in authors_text.split(",") if part.strip()]
        record["paper_url"] = urljoin(url, match.group("html"))
        record["pdf_url"] = urljoin(url, match.group("pdf"))
        record["source"] = {
            "name": "RSS Proceedings",
            "url": url,
            "fetched_at": fetched_at,
            "license": "",
        }
        records.append(record)

    return {
        "source": "rss",
        "venue_key": venue_key,
        "year": year,
        "source_url": url,
        "fetched_at": fetched_at,
        "raw_count": len(records),
        "records": records,
    }
