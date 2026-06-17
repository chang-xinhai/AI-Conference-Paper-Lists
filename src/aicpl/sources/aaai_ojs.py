"""AAAI official OJS proceedings harvester."""

from __future__ import annotations

import bisect
import html
import re
from typing import Any

from ..schema import empty_record, venue_name
from ..util import fetch_text, normalize_title, now_utc


ARCHIVE_URL = "https://ojs.aaai.org/index.php/AAAI/issue/archive"


def supports(venue_key: str, year: int) -> bool:
    return venue_key == "aaai" and year >= 2020


def _clean(value: str) -> str:
    value = html.unescape(re.sub(r"<.*?>", " ", value or ""))
    return " ".join(value.split())


def _archive_issue_links(year: int) -> list[tuple[str, str]]:
    year_suffix = f"{year % 100:02d}"
    issue_pattern = re.compile(rf"\bAAAI-{year_suffix}\b", re.I)
    links: list[tuple[str, str]] = []
    seen = set()
    url = ARCHIVE_URL

    for _ in range(12):
        text = fetch_text(url, timeout=90, retries=6)
        for match in re.finditer(r'<a[^>]+href="(?P<href>[^"]+/issue/view/[^"]+)"[^>]*>(?P<body>.*?)</a>', text, re.S):
            title = _clean(match.group("body"))
            href = html.unescape(match.group("href"))
            if issue_pattern.search(title) and href not in seen:
                links.append((href, title))
                seen.add(href)
        next_match = re.search(r'<a class="next" href="(?P<href>[^"]+)">Next</a>', text)
        if not next_match:
            break
        url = html.unescape(next_match.group("href"))
        if links and not issue_pattern.search(text):
            break
    return links


def _last_context(contexts: list[tuple[int, str]], position: int) -> str:
    if not contexts:
        return ""
    index = bisect.bisect_right([item[0] for item in contexts], position) - 1
    return contexts[index][1] if index >= 0 else ""


def _issue_records(
    venue_key: str,
    year: int,
    issue_url: str,
    issue_title: str,
    fetched_at: str,
) -> list[dict[str, Any]]:
    text = fetch_text(issue_url, timeout=90, retries=6)
    sections = [
        (match.start(), _clean(match.group("section")))
        for match in re.finditer(r"<h2>\s*(?P<section>.*?)\s*</h2>", text, re.S)
    ]
    starts = list(re.finditer(r'<div class="obj_article_summary">', text))
    records = []
    for index, match in enumerate(starts):
        end = starts[index + 1].start() if index + 1 < len(starts) else len(text)
        block = text[match.start() : end]
        title_match = re.search(
            r'<h3 class="title">\s*<a[^>]+href="(?P<href>[^"]+)"[^>]*>(?P<title>.*?)</a>\s*</h3>',
            block,
            re.S,
        )
        if not title_match:
            continue
        title = _clean(title_match.group("title"))
        if not title:
            continue
        record = empty_record(venue_key, venue_name(venue_key), year, title)
        record["paper_url"] = html.unescape(title_match.group("href"))

        authors_match = re.search(r'<div class="authors">\s*(?P<authors>.*?)\s*</div>', block, re.S)
        if authors_match:
            authors = _clean(authors_match.group("authors"))
            record["authors"] = [part.strip() for part in authors.split(",") if part.strip()]

        section = _last_context(sections, match.start())
        record["track"] = " / ".join(part for part in [issue_title, section] if part)

        pdf_match = re.search(r'<a class="obj_galley_link pdf" href="(?P<href>[^"]+)"', block)
        if pdf_match:
            record["pdf_url"] = html.unescape(pdf_match.group("href"))

        record["source"] = {
            "name": "AAAI OJS Proceedings",
            "url": issue_url,
            "fetched_at": fetched_at,
            "license": "",
        }
        records.append(record)
    return records


def harvest(venue_key: str, year: int) -> dict[str, Any]:
    if not supports(venue_key, year):
        raise ValueError(f"AAAI OJS route unsupported for {venue_key}{year}")

    fetched_at = now_utc()
    issue_links = _archive_issue_links(year)
    records = []
    source_urls = []
    for issue_url, issue_title in issue_links:
        issue_records = _issue_records(venue_key, year, issue_url, issue_title, fetched_at)
        records.extend(issue_records)
        source_urls.append(issue_url)

    merged = {normalize_title(record["title"]): record for record in records if record.get("title")}
    return {
        "source": "aaai_ojs",
        "venue_key": venue_key,
        "year": year,
        "source_url": "; ".join(source_urls),
        "fetched_at": fetched_at,
        "raw_count": len(records),
        "records": list(merged.values()),
    }
