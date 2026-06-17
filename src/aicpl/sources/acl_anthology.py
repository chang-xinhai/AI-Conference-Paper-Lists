"""ACL Anthology event page harvester."""

from __future__ import annotations

import html
import re
from typing import Any
from urllib.parse import urljoin

from ..schema import empty_record, venue_name
from ..util import fetch_text, now_utc


ACL_BASE = "https://aclanthology.org"
ACL_KEYS = {"acl", "emnlp", "naacl", "coling"}


def supports(venue_key: str, year: int) -> bool:
    return venue_key in ACL_KEYS and year >= 2020


def harvest(venue_key: str, year: int) -> dict[str, Any]:
    if not supports(venue_key, year):
        raise ValueError(f"ACL Anthology route unsupported for {venue_key}{year}")

    url = f"{ACL_BASE}/events/{venue_key}-{year}/"
    text = fetch_text(url, timeout=90)
    fetched_at = now_utc()

    block_pattern = re.compile(
        r'<div class="d-sm-flex align-items-stretch mb-3">(?P<block>.*?)</div>(?=<div class="d-sm-flex|<div id=|</div></div><button)',
        re.S,
    )
    title_pattern = re.compile(r"<strong><a class=align-middle href=(?P<href>[^ >]+)>(?P<title>.*?)</a></strong>", re.S)
    pdf_pattern = re.compile(r'href=(?P<href>https://aclanthology.org/[^ >"]+?\.pdf)')
    abstract_patterns = [
        re.compile(
            r'<div class="card[^"]*\babstract-collapse\b[^"]*"[^>]*>\s*'
            r'<div class="card-body[^"]*"[^>]*>(?P<abstract>.*?)</div>',
            re.S,
        ),
        re.compile(r'<div class="card card-body acl-abstract">(?P<abstract>.*?)</div>', re.S),
    ]

    records = []
    for block_match in block_pattern.finditer(text):
        block = block_match.group("block")
        title_match = title_pattern.search(block)
        if not title_match:
            continue
        title = html.unescape(re.sub(r"<.*?>", "", title_match.group("title")).strip())
        # Skip volume/proceedings headers that appear as pseudo-items.
        if title.lower().startswith("proceedings of "):
            continue
        record = empty_record(venue_key, venue_name(venue_key), year, title)
        href = title_match.group("href").strip('"')
        record["paper_url"] = urljoin(ACL_BASE, href)
        pdf_match = pdf_pattern.search(block)
        if pdf_match:
            record["pdf_url"] = pdf_match.group("href")
        author_part = block.split("</strong><br>", 1)[1] if "</strong><br>" in block else ""
        author_part = author_part.split("</span>", 1)[0]
        record["authors"] = [
            html.unescape(re.sub(r"<.*?>", "", part)).strip()
            for part in author_part.split("|")
            if html.unescape(re.sub(r"<.*?>", "", part)).strip()
        ]
        abs_match = next((match for pattern in abstract_patterns if (match := pattern.search(block))), None)
        if abs_match:
            record["abstract"] = html.unescape(re.sub(r"<.*?>", " ", abs_match.group("abstract")))
            record["abstract"] = re.sub(r"\s+", " ", record["abstract"]).strip()
        record["source"] = {
            "name": "ACL Anthology",
            "url": url,
            "fetched_at": fetched_at,
            "license": "",
        }
        records.append(record)

    return {
        "source": "acl_anthology",
        "venue_key": venue_key,
        "year": year,
        "source_url": url,
        "fetched_at": fetched_at,
        "raw_count": len(records),
        "records": records,
    }
