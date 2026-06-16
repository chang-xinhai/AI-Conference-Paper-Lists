"""NeurIPS official virtual list supplement for OpenReview harvests."""

from __future__ import annotations

import html
import re
from typing import Any
from urllib.parse import urljoin

from ..schema import empty_record, venue_name
from ..util import fetch_text, normalize_title, now_utc
from . import openreview


VIRTUAL_BASE = "https://neurips.cc"


def supports(venue_key: str, year: int) -> bool:
    return venue_key == "nips" and year >= 2020


def _clean_title(title: str) -> str:
    return html.unescape(re.sub(r"<.*?>", "", title)).strip()


def _virtual_records(year: int, fetched_at: str) -> tuple[str, list[dict[str, Any]]]:
    url = f"{VIRTUAL_BASE}/virtual/{year}/papers.html?filter=titles"
    text = fetch_text(url, timeout=90)
    records = []
    pattern = rf'<li><a href="(?P<href>/virtual/{year}/[^"]+)">(?P<title>.*?)</a></li>'
    for match in re.finditer(pattern, text, re.S):
        title = _clean_title(match.group("title"))
        if not title:
            continue
        record = empty_record("nips", venue_name("nips"), year, title)
        href = match.group("href")
        record["paper_url"] = urljoin(VIRTUAL_BASE, href)
        path_parts = [part for part in href.split("/") if part]
        if len(path_parts) >= 3:
            record["presentation"] = path_parts[2]
        record["source"] = {
            "name": "NeurIPS virtual",
            "url": url,
            "fetched_at": fetched_at,
            "license": "",
        }
        records.append(record)
    return url, records


def harvest(venue_key: str, year: int) -> dict[str, Any]:
    if not supports(venue_key, year):
        raise ValueError(f"NeurIPS route unsupported for {venue_key}{year}")

    fetched_at = now_utc()
    openreview_payload = openreview.harvest(venue_key, year)
    virtual_url, virtual_records = _virtual_records(year, fetched_at)

    merged: dict[str, dict[str, Any]] = {}
    for record in openreview_payload["records"]:
        merged[normalize_title(record["title"])] = record
    for record in virtual_records:
        merged.setdefault(normalize_title(record["title"]), record)

    return {
        "source": "neurips",
        "venue_key": venue_key,
        "year": year,
        "source_url": f"{openreview_payload['source_url']}; {virtual_url}",
        "fetched_at": fetched_at,
        "raw_count": openreview_payload["raw_count"] + len(virtual_records),
        "records": list(merged.values()),
    }
