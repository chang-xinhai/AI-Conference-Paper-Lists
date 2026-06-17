"""PaperCept/PaperPlaza program harvester for robotics venues."""

from __future__ import annotations

import bisect
import html
import re
from typing import Any
from urllib.parse import urljoin

from ..schema import empty_record, venue_name
from ..util import fetch_text, normalize_title, now_utc


PROGRAM_URLS = {
    ("icra", 2026): [
        "https://ras.papercept.net/conferences/conferences/ICRA26/program/ICRA26_ContentListWeb_3.html",
        "https://ras.papercept.net/conferences/conferences/ICRA26/program/ICRA26_ContentListWeb_4.html",
        "https://ras.papercept.net/conferences/conferences/ICRA26/program/ICRA26_ContentListWeb_5.html",
    ],
    ("iros", 2025): [
        "https://ras.papercept.net/conferences/conferences/IROS25/program/IROS25_ContentListWeb_1.html",
        "https://ras.papercept.net/conferences/conferences/IROS25/program/IROS25_ContentListWeb_2.html",
        "https://ras.papercept.net/conferences/conferences/IROS25/program/IROS25_ContentListWeb_3.html",
    ],
}


def supports(venue_key: str, year: int) -> bool:
    return (venue_key, year) in PROGRAM_URLS


def _clean(value: str) -> str:
    value = html.unescape(re.sub(r"<.*?>", " ", value or ""))
    value = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", value)
    return " ".join(value.split())


def _last_context(contexts: list[tuple[int, str]], position: int) -> str:
    if not contexts:
        return ""
    index = bisect.bisect_right([item[0] for item in contexts], position) - 1
    return contexts[index][1] if index >= 0 else ""


def _page_records(venue_key: str, year: int, url: str, fetched_at: str) -> list[dict[str, Any]]:
    text = fetch_text(url, timeout=90, retries=6)
    sessions = [
        (match.start(), _clean(match.group("session")))
        for match in re.finditer(r'<tr class="sHdr">(?P<session>.*?)</tr>', text, re.S)
    ]
    starts = list(
        re.finditer(
            r'<tr class="pHdr"><td valign="bottom"><a name="(?P<anchor>[^"]+)">(?P<header>.*?)</a>',
            text,
            re.S,
        )
    )
    records = []
    for index, match in enumerate(starts):
        end = starts[index + 1].start() if index + 1 < len(starts) else len(text)
        block = text[match.start() : end]
        title_match = re.search(r'<span class="pTtl">(?P<title>.*?)</span>', block, re.S)
        if not title_match:
            continue
        title = _clean(title_match.group("title"))
        if not title:
            continue

        record = empty_record(venue_key, venue_name(venue_key), year, title)
        record["presentation"] = _clean(match.group("header"))
        record["track"] = _last_context(sessions, match.start())
        record["paper_url"] = urljoin(url, f"#{match.group('anchor')}")
        authors = []
        affiliations = []
        for author_match in re.finditer(
            r'<tr><td><a href="[^"]*AuthorIndexWeb\.html#[^"]*"[^>]*>(?P<author>.*?)</a></td><td class="r">(?P<affiliation>.*?)</td></tr>',
            block,
            re.S,
        ):
            author = _clean(author_match.group("author"))
            affiliation = _clean(author_match.group("affiliation"))
            if author:
                authors.append(author)
            if affiliation:
                affiliations.append(affiliation)
        record["authors"] = authors
        record["affiliations"] = affiliations
        record["first_institute"] = affiliations[0] if affiliations else ""
        abstract_match = re.search(r"<strong>Abstract:</strong>(?P<abstract>.*?)</div>", block, re.S)
        if abstract_match:
            record["abstract"] = _clean(abstract_match.group("abstract"))
        keywords_match = re.search(r"<strong>Keywords:</strong>(?P<keywords>.*?)<br>", block, re.S)
        if keywords_match:
            record["keywords"] = [
                _clean(keyword)
                for keyword in re.findall(r"<a [^>]*>(.*?)</a>", keywords_match.group("keywords"), re.S)
                if _clean(keyword)
            ]
        record["source"] = {
            "name": "PaperCept program",
            "url": url,
            "fetched_at": fetched_at,
            "license": "",
        }
        records.append(record)
    return records


def harvest(venue_key: str, year: int) -> dict[str, Any]:
    urls = PROGRAM_URLS.get((venue_key, year))
    if not urls:
        raise ValueError(f"PaperCept route unsupported for {venue_key}{year}")

    fetched_at = now_utc()
    records = []
    for url in urls:
        records.extend(_page_records(venue_key, year, url, fetched_at))
    merged = {normalize_title(record["title"]): record for record in records if record.get("title")}
    return {
        "source": "papercept",
        "venue_key": venue_key,
        "year": year,
        "source_url": "; ".join(urls),
        "fetched_at": fetched_at,
        "raw_count": len(records),
        "records": list(merged.values()),
    }
