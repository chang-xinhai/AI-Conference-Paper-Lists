"""IEEE proceedings harvester via publisher DOI metadata in Crossref."""

from __future__ import annotations

import html
import re
from typing import Any
from urllib.parse import urlencode

from ..schema import empty_record, venue_name
from ..util import fetch_json, normalize_title, now_utc


CROSSREF_BASE = "https://api.crossref.org/works"

FRONT_MATTER = {
    "author index",
    "back cover",
    "committee",
    "conference information",
    "conference title page",
    "contents",
    "content list",
    "contributor page",
    "copyright",
    "cover page",
    "editorial board",
    "exhibitors",
    "front cover",
    "foreword",
    "forums",
    "index of papers",
    "organizations",
    "organizing committee",
    "organising committee",
    "oral presentation sessions overview",
    "preface",
    "plenary and keynote speakers",
    "program",
    "program at a glance",
    "programme",
    "programme at a glance",
    "reviewers",
    "session index",
    "sponsors",
    "sponsors and partners",
    "statistics",
    "table of contents",
    "technical program at glance",
    "toc",
    "title page",
    "top menu",
    "welcome",
    "welcome page",
    "workshops and tutorials",
}


def supports(venue_key: str, year: int) -> bool:
    return venue_key in {"icra", "iros"} and 2020 <= year <= 2025


def _clean_title(title: str) -> str:
    title = html.unescape(re.sub(r"<.*?>", " ", title or ""))
    title = " ".join(title.split())
    return title[:-1] if title.endswith(".") else title


def _event_name(venue_key: str, year: int) -> str:
    if venue_key == "icra":
        return f"{year} IEEE International Conference on Robotics and Automation (ICRA)"
    if venue_key == "iros":
        return f"{year} IEEE/RSJ International Conference on Intelligent Robots and Systems (IROS)"
    raise ValueError(f"IEEE route unsupported for {venue_key}{year}")


def _query_text(venue_key: str, year: int) -> str:
    if venue_key == "icra":
        return f"ICRA {year} IEEE International Conference on Robotics and Automation"
    return f"IROS {year} Intelligent Robots and Systems"


def _is_front_matter(title: str, venue_key: str, year: int) -> bool:
    canonical = re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()
    canonical = re.sub(r"\s+", " ", canonical)
    stripped = canonical
    for token in [venue_key, str(year)]:
        stripped = re.sub(rf"\b{re.escape(token)}\b", " ", stripped)
    stripped = re.sub(r"\s+", " ", stripped).strip()
    if stripped in FRONT_MATTER:
        return True
    return bool(
        re.match(r"^(awards and finalists|competitions|conference editorial board)$", stripped)
        or re.match(r"^(content list|index of papers|.+ papers presented at)\b", stripped)
        or re.match(r"^ieee rsj international conference on intelligent robots and systems$", stripped)
    )


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
    if not title or _is_front_matter(title, venue_key, year):
        return None
    record = empty_record(venue_key, venue_name(venue_key), year, title)
    doi = str(item.get("DOI") or "")
    record["doi"] = doi
    record["paper_url"] = f"https://doi.org/{doi}" if doi else ""
    record["authors"] = _authors(item)
    container_titles = item.get("container-title") or []
    record["track"] = str(container_titles[0] if container_titles else "")
    record["source"] = {
        "name": "IEEE Crossref DOI metadata",
        "url": source_url,
        "fetched_at": fetched_at,
        "license": "",
    }
    return record


def harvest(venue_key: str, year: int) -> dict[str, Any]:
    if not supports(venue_key, year):
        raise ValueError(f"IEEE route unsupported for {venue_key}{year}")

    event_name = _event_name(venue_key, year)
    fetched_at = now_utc()
    cursor = "*"
    records: list[dict[str, Any]] = []
    source_urls = []
    empty_relevant_pages = 0

    for _ in range(6):
        filters = ",".join(
            [
                "prefix:10.1109",
                "type:proceedings-article",
                f"from-pub-date:{year}-01-01",
                f"until-pub-date:{year}-12-31",
            ]
        )
        params = {
            "filter": filters,
            "query.bibliographic": _query_text(venue_key, year),
            "rows": 1000,
            "cursor": cursor,
            "select": "DOI,title,author,container-title,event,published-print,published-online,type",
        }
        url = f"{CROSSREF_BASE}?{urlencode(params)}"
        payload = fetch_json(url, timeout=90, retries=6)
        source_urls.append(url)
        items = payload.get("message", {}).get("items", [])
        relevant_count = 0
        for item in items:
            if str((item.get("event") or {}).get("name") or "").lower() != event_name.lower():
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
        "source": "ieee",
        "venue_key": venue_key,
        "year": year,
        "source_url": "; ".join(source_urls[:2]),
        "fetched_at": fetched_at,
        "raw_count": len(records),
        "records": list(merged.values()),
    }
