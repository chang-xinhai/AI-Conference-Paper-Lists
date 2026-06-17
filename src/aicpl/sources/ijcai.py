"""IJCAI official proceedings harvester."""

from __future__ import annotations

import bisect
import html
import re
from typing import Any
from urllib.parse import urljoin

from ..schema import empty_record, venue_name
from ..util import fetch_text, now_utc


BASE_URL = "https://www.ijcai.org/proceedings/{year}/"


def supports(venue_key: str, year: int) -> bool:
    return venue_key == "ijcai" and year >= 2020


def _clean(value: str) -> str:
    value = html.unescape(re.sub(r"<.*?>", " ", value or ""))
    return " ".join(value.split())


def _last_context(contexts: list[tuple[int, str]], position: int) -> str:
    if not contexts:
        return ""
    index = bisect.bisect_right([item[0] for item in contexts], position) - 1
    return contexts[index][1] if index >= 0 else ""


def harvest(venue_key: str, year: int) -> dict[str, Any]:
    if not supports(venue_key, year):
        raise ValueError(f"IJCAI route unsupported for {venue_key}{year}")

    url = BASE_URL.format(year=year)
    text = fetch_text(url, timeout=90, retries=6)
    fetched_at = now_utc()

    sections = [
        (match.start(), _clean(match.group("section")))
        for match in re.finditer(r'<div class="section_title"><h3>(?P<section>.*?)</h3></div>', text, re.S)
    ]
    subsections = [
        (match.start(), _clean(match.group("subsection")))
        for match in re.finditer(r'<div class="subsection_title">(?P<subsection>.*?)</div>', text, re.S)
    ]
    starts = list(re.finditer(r'<div id="paper(?P<number>\d+)" class="paper_wrapper">', text))

    records = []
    for index, match in enumerate(starts):
        end = starts[index + 1].start() if index + 1 < len(starts) else len(text)
        block = text[match.start() : end]
        title_match = re.search(r'<div class="title">(?P<title>.*?)</div>', block, re.S)
        if not title_match:
            continue
        title = _clean(title_match.group("title"))
        if not title:
            continue

        record = empty_record(venue_key, venue_name(venue_key), year, title)
        authors_match = re.search(r'<div class="authors">(?P<authors>.*?)</div>', block, re.S)
        if authors_match:
            authors = _clean(authors_match.group("authors"))
            record["authors"] = [part.strip() for part in authors.split(",") if part.strip()]

        section = _last_context(sections, match.start())
        subsection = _last_context(subsections, match.start())
        record["track"] = " / ".join(part for part in [section, subsection] if part)

        pdf_match = re.search(r'<a href="(?P<href>[^"]+\.pdf)">PDF</a>', block)
        if pdf_match:
            record["pdf_url"] = urljoin(url, pdf_match.group("href"))
        detail_match = re.search(r'<a href="(?P<href>/proceedings/\d+/\d+)">\s*Details</a>', block)
        if detail_match:
            record["paper_url"] = urljoin(url, detail_match.group("href"))

        record["source"] = {
            "name": "IJCAI Proceedings",
            "url": url,
            "fetched_at": fetched_at,
            "license": "",
        }
        records.append(record)

    return {
        "source": "ijcai",
        "venue_key": venue_key,
        "year": year,
        "source_url": url,
        "fetched_at": fetched_at,
        "raw_count": len(records),
        "records": records,
    }
