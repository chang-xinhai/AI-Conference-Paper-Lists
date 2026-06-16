"""CVF Open Access harvester."""

from __future__ import annotations

import html
import re
from typing import Any
from urllib.parse import urljoin

from ..schema import empty_record, venue_name
from ..util import fetch_text, now_utc


CVF_BASE = "https://openaccess.thecvf.com"
CVF_KEYS = {
    "cvpr": "CVPR",
    "iccv": "ICCV",
    "wacv": "WACV",
}


def supports(venue_key: str, year: int) -> bool:
    return venue_key in CVF_KEYS and year >= 2020


def harvest(venue_key: str, year: int) -> dict[str, Any]:
    if not supports(venue_key, year):
        raise ValueError(f"CVF route unsupported for {venue_key}{year}")

    conf = CVF_KEYS[venue_key]
    url = f"{CVF_BASE}/{conf}{year}?day=all"
    text = fetch_text(url, timeout=90)
    fetched_at = now_utc()

    # The list page alternates title dt blocks and author/pdf dd blocks.
    pattern = re.compile(
        r'<dt class="ptitle"><br><a href="(?P<html>[^"]+)">(?P<title>.*?)</a></dt>\s*'
        r"<dd>(?P<authors>.*?)</dd>\s*<dd>\s*\[<a href=\"(?P<pdf>[^\"]+)\">pdf</a>\]",
        re.S,
    )

    records = []
    for match in pattern.finditer(text):
        title = html.unescape(re.sub(r"\s+", " ", match.group("title")).strip())
        record = empty_record(venue_key, venue_name(venue_key), year, title)
        authors_html = match.group("authors")
        record["authors"] = [
            html.unescape(name).strip()
            for name in re.findall(r'value="([^"]+)"', authors_html)
            if html.unescape(name).strip()
        ]
        record["paper_url"] = urljoin(CVF_BASE, match.group("html"))
        record["pdf_url"] = urljoin(CVF_BASE, match.group("pdf"))
        record["source"] = {
            "name": "CVF Open Access",
            "url": url,
            "fetched_at": fetched_at,
            "license": "",
        }
        records.append(record)

    return {
        "source": "cvf",
        "venue_key": venue_key,
        "year": year,
        "source_url": url,
        "fetched_at": fetched_at,
        "raw_count": len(records),
        "records": records,
    }
