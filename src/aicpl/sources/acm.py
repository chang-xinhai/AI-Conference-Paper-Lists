"""ACM proceedings harvester via publisher DOI metadata in Crossref."""

from __future__ import annotations

import html
import re
from typing import Any
from urllib.parse import urlencode

from ..schema import empty_record, venue_name
from ..util import fetch_json, normalize_title, now_utc


CROSSREF_BASE = "https://api.crossref.org/works"


def supports(venue_key: str, year: int) -> bool:
    if venue_key == "acmmm":
        return year >= 2024
    if venue_key == "kdd":
        return 2023 <= year <= 2025
    if venue_key == "www":
        return year >= 2024
    return False


def _clean_title(title: str) -> str:
    title = html.unescape(re.sub(r"<.*?>", " ", title or ""))
    title = " ".join(title.split())
    return title[:-1] if title.endswith(".") else title


def _query_config(venue_key: str, year: int) -> dict[str, str]:
    yy = f"{year % 100:02d}"
    if venue_key == "acmmm":
        return {
            "query_field": "query.event-acronym",
            "query_value": f"MM '{yy}",
            "event_acronym": f"MM '{yy}",
        }
    if venue_key == "kdd":
        return {
            "query_field": "query.event-acronym",
            "query_value": f"KDD '{yy}",
            "event_acronym": f"KDD '{yy}",
        }
    if venue_key == "www":
        return {
            "query_field": "query.event-name",
            "query_value": f"The ACM Web Conference {year}",
            "event_name": f"WWW '{yy}: The ACM Web Conference {year}",
        }
    raise ValueError(f"ACM route unsupported for {venue_key}{year}")


def _is_relevant(item: dict[str, Any], config: dict[str, str]) -> bool:
    event = item.get("event") or {}
    if acronym := config.get("event_acronym"):
        return str(event.get("acronym") or "").lower() == acronym.lower()
    if name := config.get("event_name"):
        return str(event.get("name") or "").lower() == name.lower()
    return False


def _authors(item: dict[str, Any]) -> list[str]:
    authors = []
    for author in item.get("author") or []:
        parts = [str(author.get("given") or "").strip(), str(author.get("family") or "").strip()]
        name = " ".join(part for part in parts if part)
        if name:
            authors.append(name)
    return authors


def _record_from_item(
    venue_key: str,
    year: int,
    item: dict[str, Any],
    fetched_at: str,
    source_url: str,
) -> dict[str, Any] | None:
    titles = item.get("title") or []
    title = _clean_title(str(titles[0] if titles else ""))
    subtitles = item.get("subtitle") or []
    subtitle = _clean_title(str(subtitles[0] if subtitles else ""))
    if subtitle and subtitle.lower() not in title.lower():
        title = f"{title}: {subtitle}"
    if not title:
        return None

    record = empty_record(venue_key, venue_name(venue_key), year, title)
    doi = str(item.get("DOI") or "")
    record["doi"] = doi
    record["paper_url"] = f"https://doi.org/{doi}" if doi else ""
    record["authors"] = _authors(item)
    container_titles = item.get("container-title") or []
    record["track"] = str(container_titles[0] if container_titles else "")
    record["source"] = {
        "name": "ACM Crossref DOI metadata",
        "url": source_url,
        "fetched_at": fetched_at,
        "license": "",
    }
    return record


def harvest(venue_key: str, year: int) -> dict[str, Any]:
    if not supports(venue_key, year):
        raise ValueError(f"ACM route unsupported for {venue_key}{year}")

    config = _query_config(venue_key, year)
    fetched_at = now_utc()
    records: list[dict[str, Any]] = []
    source_urls = []
    cursor = "*"
    empty_relevant_pages = 0

    for _ in range(8):
        filters = ",".join(
            [
                "prefix:10.1145",
                "type:proceedings-article",
                f"from-pub-date:{year}-01-01",
                f"until-pub-date:{year}-12-31",
            ]
        )
        params = {
            "filter": filters,
            config["query_field"]: config["query_value"],
            "rows": 1000,
            "cursor": cursor,
            "select": "DOI,title,subtitle,author,container-title,event,published-print,published-online,type",
        }
        url = f"{CROSSREF_BASE}?{urlencode(params)}"
        payload = fetch_json(url, timeout=90, retries=6)
        source_urls.append(url)
        items = payload.get("message", {}).get("items", [])
        relevant_count = 0
        for item in items:
            if not _is_relevant(item, config):
                continue
            relevant_count += 1
            if record := _record_from_item(venue_key, year, item, fetched_at, url):
                records.append(record)
        if not items:
            break
        if relevant_count:
            empty_relevant_pages = 0
        elif records:
            empty_relevant_pages += 1
            if empty_relevant_pages >= 2:
                break
        cursor = payload.get("message", {}).get("next-cursor") or ""
        if not cursor:
            break

    merged = {normalize_title(record["title"]): record for record in records if record.get("title")}
    return {
        "source": "acm",
        "venue_key": venue_key,
        "year": year,
        "source_url": "; ".join(source_urls[:2]),
        "fetched_at": fetched_at,
        "raw_count": len(records),
        "records": list(merged.values()),
    }
