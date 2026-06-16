"""ICML virtual-site harvester for latest public paper lists."""

from __future__ import annotations

import html
import re
from typing import Any
from urllib.parse import urljoin

from ..schema import empty_record, venue_name
from ..util import fetch_text, now_utc


ICML_VIRTUAL_URLS = {
    2026: "https://icml.cc/virtual/2026/papers.html?filter=titles",
}


def supports(venue_key: str, year: int) -> bool:
    return venue_key == "icml" and year in ICML_VIRTUAL_URLS


def harvest(venue_key: str, year: int) -> dict[str, Any]:
    if not supports(venue_key, year):
        raise ValueError(f"ICML virtual route unsupported for {venue_key}{year}")

    url = ICML_VIRTUAL_URLS[year]
    text = fetch_text(url, timeout=90, retries=3)
    fetched_at = now_utc()
    records = []
    pattern = rf'<li><a href="(?P<href>/virtual/{year}/(?P<presentation>[^/]+)/\d+)">(?P<title>.*?)</a></li>'
    for match in re.finditer(pattern, text, re.S):
        title = html.unescape(re.sub(r"<.*?>", " ", match.group("title")))
        title = " ".join(title.split()).strip()
        if not title:
            continue
        record = empty_record(venue_key, venue_name(venue_key), year, title)
        record["presentation"] = match.group("presentation")
        record["paper_url"] = urljoin("https://icml.cc", match.group("href"))
        record["source"] = {
            "name": "ICML virtual",
            "url": url,
            "fetched_at": fetched_at,
            "license": "",
        }
        records.append(record)

    return {
        "source": "icml",
        "venue_key": venue_key,
        "year": year,
        "source_url": url,
        "fetched_at": fetched_at,
        "raw_count": len(records),
        "records": records,
    }
