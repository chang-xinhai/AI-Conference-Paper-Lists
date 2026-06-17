"""NeurIPS official virtual list supplement for OpenReview harvests."""

from __future__ import annotations

import html
import re
from typing import Any
from urllib.parse import urljoin

from ..schema import empty_record, normalize_keywords, venue_name
from ..util import fetch_json, fetch_text, normalize_title, now_utc
from . import openreview


VIRTUAL_BASE = "https://neurips.cc"


def supports(venue_key: str, year: int) -> bool:
    return venue_key == "nips" and year >= 2020


def _clean_title(title: str) -> str:
    return html.unescape(re.sub(r"<.*?>", "", title)).strip()


def _event_id_from_href(href: str) -> str:
    match = re.search(r"/(\d+)(?:$|[/?#])", href)
    return match.group(1) if match else ""


def _authors_from_event(event: dict[str, Any]) -> list[str]:
    authors = []
    for author in event.get("authors") or []:
        if isinstance(author, dict):
            name = str(author.get("fullname") or author.get("name") or "").strip()
        else:
            name = str(author).strip()
        if name:
            authors.append(name)
    return authors


def _affiliations_from_event(event: dict[str, Any]) -> list[str]:
    affiliations = []
    seen = set()
    for author in event.get("authors") or []:
        if not isinstance(author, dict):
            continue
        institution = str(author.get("institution") or "").strip()
        if institution and institution.lower() not in seen:
            affiliations.append(institution)
            seen.add(institution.lower())
    return affiliations


def _pdf_from_event(event: dict[str, Any]) -> str:
    value = str(event.get("paper_pdf_url") or "").strip()
    if value:
        return urljoin(VIRTUAL_BASE, value)
    for media in event.get("eventmedia") or []:
        if not isinstance(media, dict):
            continue
        media_type = str(media.get("type") or media.get("name") or "").lower()
        uri = str(media.get("uri") or media.get("file") or "").strip()
        if "pdf" in media_type and uri.lower().split("?", 1)[0].endswith(".pdf"):
            return urljoin(VIRTUAL_BASE, uri)
    return ""


def _event_metadata(year: int) -> tuple[str, dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    url = f"{VIRTUAL_BASE}/static/virtual/data/neurips-{year}-orals-posters.json"
    try:
        payload = fetch_json(url, timeout=120)
    except Exception:
        return url, {}, {}
    events = payload.get("results", []) if isinstance(payload, dict) else []
    by_id: dict[str, dict[str, Any]] = {}
    by_title: dict[str, dict[str, Any]] = {}
    for event in events:
        if not isinstance(event, dict):
            continue
        event_id = str(event.get("id") or "").strip()
        title = str(event.get("name") or "").strip()
        if event_id:
            by_id[event_id] = event
        if title:
            by_title.setdefault(normalize_title(title), event)
    return url, by_id, by_title


def _enrich_from_event(record: dict[str, Any], event: dict[str, Any], *, source_url: str) -> bool:
    changed = False
    authors = _authors_from_event(event)
    if authors and not record.get("authors"):
        record["authors"] = authors
        changed = True
    abstract = str(event.get("abstract") or "").strip()
    if abstract and not record.get("abstract"):
        record["abstract"] = abstract
        changed = True
    affiliations = _affiliations_from_event(event)
    if affiliations and not record.get("affiliations"):
        record["affiliations"] = affiliations
        record["first_institute"] = affiliations[0]
        changed = True
    keywords = normalize_keywords(event.get("keywords") or [])
    if keywords and not record.get("keywords"):
        record["keywords"] = keywords
        changed = True
    topic = str(event.get("topic") or "").strip()
    decision = str(event.get("decision") or "").strip()
    if not record.get("track"):
        record["track"] = topic or decision
        changed = changed or bool(record["track"])
    presentation = str(event.get("eventtype") or event.get("event_type") or event.get("session") or "").strip()
    if presentation and not record.get("presentation"):
        record["presentation"] = presentation
        changed = True
    pdf_url = _pdf_from_event(event)
    if pdf_url and not record.get("pdf_url"):
        record["pdf_url"] = pdf_url
        changed = True
    if changed:
        source = record.get("source") if isinstance(record.get("source"), dict) else {}
        name = str(source.get("name") or "").strip()
        if "NeurIPS virtual" not in name:
            source["name"] = f"{name} + NeurIPS virtual metadata".strip(" +")
        urls = [part.strip() for part in str(source.get("url") or "").split(";") if part.strip()]
        if source_url not in urls:
            urls.append(source_url)
        source["url"] = "; ".join(urls)
        record["source"] = source
    return changed


def _virtual_records(year: int, fetched_at: str) -> tuple[str, list[dict[str, Any]], dict[str, dict[str, Any]]]:
    url = f"{VIRTUAL_BASE}/virtual/{year}/papers.html?filter=titles"
    metadata_url, by_event_id, by_title = _event_metadata(year)
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
        event_id = _event_id_from_href(href)
        path_parts = [part for part in href.split("/") if part]
        if len(path_parts) >= 3:
            record["presentation"] = path_parts[2]
        event = by_event_id.get(event_id) or by_title.get(normalize_title(title))
        if event:
            _enrich_from_event(record, event, source_url=metadata_url)
        record["source"] = {
            "name": "NeurIPS virtual",
            "url": f"{url}; {metadata_url}",
            "fetched_at": fetched_at,
            "license": "",
        }
        records.append(record)
    return f"{url}; {metadata_url}", records, by_title


def harvest(venue_key: str, year: int) -> dict[str, Any]:
    if not supports(venue_key, year):
        raise ValueError(f"NeurIPS route unsupported for {venue_key}{year}")

    fetched_at = now_utc()
    openreview_payload = openreview.harvest(venue_key, year)
    virtual_url, virtual_records, virtual_by_title = _virtual_records(year, fetched_at)

    merged: dict[str, dict[str, Any]] = {}
    for record in openreview_payload["records"]:
        event = virtual_by_title.get(normalize_title(record["title"]))
        if event:
            _enrich_from_event(record, event, source_url=virtual_url)
        merged[normalize_title(record["title"])] = record
    for record in virtual_records:
        key = normalize_title(record["title"])
        if key in merged:
            event = virtual_by_title.get(key)
            if event:
                _enrich_from_event(merged[key], event, source_url=virtual_url)
        else:
            merged[key] = record

    return {
        "source": "neurips",
        "venue_key": venue_key,
        "year": year,
        "source_url": f"{openreview_payload['source_url']}; {virtual_url}",
        "fetched_at": fetched_at,
        "raw_count": openreview_payload["raw_count"] + len(virtual_records),
        "records": list(merged.values()),
    }
