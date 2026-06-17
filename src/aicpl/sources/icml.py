"""ICML virtual-site harvester for latest public paper lists."""

from __future__ import annotations

import html
import re
from typing import Any
from urllib.parse import urljoin

from ..schema import empty_record, venue_name
from ..util import fetch_json, fetch_text, now_utc


ICML_VIRTUAL_URLS = {
    2026: "https://icml.cc/virtual/2026/papers.html?filter=titles",
}

ICML_METADATA_URLS = {
    2026: {
        "papers": "https://icml.cc/static/virtual/data/icml-2026-orals-posters.json",
        "abstracts": "https://icml.cc/static/virtual/data/icml-2026-abstracts.json",
    },
}


def supports(venue_key: str, year: int) -> bool:
    return venue_key == "icml" and year in ICML_VIRTUAL_URLS


def harvest(venue_key: str, year: int) -> dict[str, Any]:
    if not supports(venue_key, year):
        raise ValueError(f"ICML virtual route unsupported for {venue_key}{year}")

    url = ICML_VIRTUAL_URLS[year]
    text = fetch_text(url, timeout=90, retries=3)
    fetched_at = now_utc()
    metadata_urls = ICML_METADATA_URLS.get(year, {})
    metadata_by_id: dict[str, dict[str, Any]] = {}
    abstracts: dict[str, str] = {}
    if metadata_urls:
        paper_payload = fetch_json(metadata_urls["papers"], timeout=90, retries=3)
        metadata_by_id = {
            str(item.get("id")): item
            for item in paper_payload.get("results", [])
            if item.get("id") is not None
        }
        abstracts = {
            str(paper_id): str(abstract or "").strip()
            for paper_id, abstract in fetch_json(metadata_urls["abstracts"], timeout=90, retries=3).items()
        }

    records = []
    pattern = rf'<li><a href="(?P<href>/virtual/{year}/(?P<presentation>[^/]+)/(?P<paper_id>\d+))">(?P<title>.*?)</a></li>'
    for match in re.finditer(pattern, text, re.S):
        title = html.unescape(re.sub(r"<.*?>", " ", match.group("title")))
        title = " ".join(title.split()).strip()
        if not title:
            continue
        paper_id = match.group("paper_id")
        metadata = metadata_by_id.get(paper_id, {})
        record = empty_record(venue_key, venue_name(venue_key), year, title)
        record["abstract"] = abstracts.get(paper_id, "")
        record["authors"] = [
            str(author.get("fullname") or "").strip()
            for author in metadata.get("authors", [])
            if str(author.get("fullname") or "").strip()
        ]
        record["affiliations"] = [
            str(author.get("institution") or "").strip()
            for author in metadata.get("authors", [])
            if str(author.get("institution") or "").strip()
        ]
        record["first_institute"] = record["affiliations"][0] if record["affiliations"] else ""
        record["keywords"] = [
            str(keyword).strip()
            for keyword in metadata.get("keywords", [])
            if str(keyword).strip()
        ]
        record["track"] = str(metadata.get("topic") or metadata.get("session") or "").strip()
        record["presentation"] = str(metadata.get("event_type") or match.group("presentation")).strip()
        record["paper_url"] = urljoin("https://icml.cc", match.group("href"))
        if metadata.get("paper_pdf_url"):
            record["pdf_url"] = str(metadata["paper_pdf_url"])
        record["source"] = {
            "name": "ICML virtual",
            "url": "; ".join([url, *metadata_urls.values()]) if metadata_urls else url,
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
