"""SIGGRAPH and SIGGRAPH Asia composite harvester."""

from __future__ import annotations

import html
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from urllib.parse import urlencode, urljoin
from xml.etree import ElementTree as ET

from ..schema import empty_record, venue_name
from ..util import fetch_json, fetch_text, normalize_title, now_utc


DBLP_BASE = "https://dblp.org"
CROSSREF_BASE = "https://api.crossref.org/works"
TOG_ISSN = "0730-0301"

VENUE_CONFIG = {
    "siggraph": {
        "dblp_dir": "siggraph",
        "dblp_prefix": "siggraph",
        "event_acronym": "SIGGRAPH",
        "tog_from": "{year}-01-01",
        "tog_until": "{year}-12-31",
        "proceedings_from": "{year}-07-01",
        "proceedings_until": "{year}-08-31",
    },
    "siggraphasia": {
        "dblp_dir": "siggrapha",
        "dblp_prefix": "siggrapha",
        "event_acronym": "SA",
        "tog_from": "{year}-11-01",
        "tog_until": "{year}-12-31",
        "proceedings_from": "{year}-11-01",
        "proceedings_until": "{year}-12-31",
    },
}

KNOWN_DBLP_TOCS = {
    ("siggraph", 2020): ["courses", "edu", "et", "ip", "labs", "posters", "talks"],
    ("siggraph", 2021): ["art", "courses", "et", "festival", "happy", "ip", "posters", "talks", "vrtheater"],
    ("siggraph", 2022): ["", "courses", "edu", "et", "posters", "production"],
    ("siggraph", 2023): [
        "",
        "art",
        "courses",
        "edu",
        "et",
        "etheater",
        "happy",
        "ip",
        "labs",
        "pan",
        "posters",
        "production",
        "rtl",
        "talks",
        "vrtheater",
    ],
    ("siggraph", 2024): ["", "appyhour", "art", "courses", "edu", "et", "ip", "labs", "talks", "vrtheater"],
    ("siggraph", 2025): ["", "courses", "et", "posters"],
    ("siggraphasia", 2020): ["emerging", "posters", "tc", "xr"],
    ("siggraphasia", 2021): ["emerging", "posters", "tc", "xr"],
    ("siggraphasia", 2022): ["", "emerging", "festival", "gallery", "posters", "tc", "xr"],
    ("siggraphasia", 2023): ["", "art", "courses", "dc", "ef", "emerging", "festival", "gallery", "posters", "tc", "xr"],
    ("siggraphasia", 2024): ["", "art", "ef", "emerging", "festival", "gallery", "posters", "tc", "xr"],
}

LINKLINGS_URLS = {
    ("siggraph", 2024): "https://s2024.conference-program.org/",
}

LINKLINGS_WP_URLS = {
    ("siggraph", 2022): "https://s2022.siggraph.org/full-program/",
}

HISTORY_OVERVIEW_URLS = {
    ("siggraph", 2020): "https://history.siggraph.org/learning-overview/siggraph-2020-technical-papers/",
    ("siggraph", 2021): "https://history.siggraph.org/learning-overview/siggraph-2021-technical-papers/",
    ("siggraph", 2022): "https://history.siggraph.org/learning-overview/siggraph-2022-technical-papers/",
    ("siggraph", 2023): "https://history.siggraph.org/learning-overview/siggraph-2023-technical-papers/",
    ("siggraph", 2024): "https://history.siggraph.org/learning-overview/siggraph-2024-technical-papers/",
    ("siggraph", 2025): "https://history.siggraph.org/learning-overview/siggraph-2025-technical-papers/",
    ("siggraphasia", 2020): "https://history.siggraph.org/learning-overview/auto-draft-12/",
    ("siggraphasia", 2021): "https://history.siggraph.org/learning-overview/siggraph-asia-2021-technical-papers/",
    ("siggraphasia", 2022): "https://history.siggraph.org/learning-overview/siggraph-asia-2022-technical-papers/",
    ("siggraphasia", 2023): "https://history.siggraph.org/learning-overview/siggraph-asia-2023-technical-papers/",
    ("siggraphasia", 2024): "https://history.siggraph.org/learning-overview/siggraph-asia-2024-technical-papers/",
}

LINKLINGS_TECH_TYPES = {
    ("siggraph", 2022): ["sstype128"],
    ("siggraph", 2023): ["sstype101"],
    ("siggraph", 2024): ["sstype101"],
}


def supports(venue_key: str, year: int) -> bool:
    return venue_key in VENUE_CONFIG and year >= 2020


def _entry_text(entry: ET.Element, tag: str) -> str:
    child = entry.find(tag)
    if child is None:
        return ""
    return "".join(child.itertext()).strip()


def _clean_title(title: str) -> str:
    title = html.unescape(title)
    title = " ".join(title.split())
    return title[:-1] if title.endswith(".") else title


def _paper_url(entry: ET.Element) -> tuple[str, str]:
    for ee in entry.findall("ee"):
        value = "".join(ee.itertext()).strip()
        if value and "wikidata.org" not in value:
            doi = value.split("doi.org/", 1)[1] if "doi.org/" in value else ""
            return value, doi
    dblp_url = _entry_text(entry, "url")
    if dblp_url:
        return urljoin(f"{DBLP_BASE}/", dblp_url), ""
    return "", ""


def _dblp_toc_urls(venue_key: str, year: int) -> list[str]:
    config = VENUE_CONFIG[venue_key]
    known_suffixes = KNOWN_DBLP_TOCS.get((venue_key, year))
    if known_suffixes is not None:
        urls = []
        for suffix in known_suffixes:
            stem = f"{config['dblp_prefix']}{year}{suffix}"
            urls.append(f"{DBLP_BASE}/db/conf/{config['dblp_dir']}/{stem}.xml")
        return urls
    index_url = f"{DBLP_BASE}/db/conf/{config['dblp_dir']}/index.html"
    text = fetch_text(index_url, timeout=90, retries=6)
    pattern = (
        rf'https://dblp\.org/db/conf/{re.escape(config["dblp_dir"])}/'
        rf'{re.escape(config["dblp_prefix"])}{year}[^"#]*\.html'
    )
    html_urls = sorted(set(re.findall(pattern, text)))
    return [url[:-5] + ".xml" for url in html_urls]


def _records_from_dblp_toc(venue_key: str, year: int, url: str, fetched_at: str) -> list[dict[str, Any]]:
    text = fetch_text(url, timeout=10, retries=0)
    root = ET.fromstring(f"<root>{text}</root>")
    records = []
    for entry in root.iter():
        if entry.tag not in {"inproceedings", "article"}:
            continue
        if _entry_text(entry, "year") != str(year):
            continue
        title = _clean_title(_entry_text(entry, "title"))
        if not title:
            continue
        record = empty_record(venue_key, venue_name(venue_key), year, title)
        record["authors"] = [
            " ".join("".join(author.itertext()).split())
            for author in entry.findall("author")
            if "".join(author.itertext()).strip()
        ]
        record["track"] = _entry_text(entry, "booktitle") or _entry_text(entry, "journal")
        paper_url, doi = _paper_url(entry)
        record["paper_url"] = paper_url
        record["doi"] = doi
        record["source"] = {
            "name": "DBLP",
            "url": url,
            "fetched_at": fetched_at,
            "license": "",
            "key": entry.attrib.get("key", ""),
        }
        records.append(record)
    return records


def _record_from_crossref_item(
    venue_key: str,
    year: int,
    item: dict[str, Any],
    fetched_at: str,
    url: str,
    track: str,
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
    container_titles = item.get("container-title") or []
    record["track"] = str(container_titles[0] if container_titles else track)
    doi = str(item.get("DOI") or "")
    record["doi"] = doi
    record["paper_url"] = f"https://doi.org/{doi}" if doi else ""
    record["authors"] = [
        " ".join(part for part in [str(author.get("given", "")).strip(), str(author.get("family", "")).strip()] if part)
        for author in item.get("author", [])
        if isinstance(author, dict)
        and (str(author.get("given", "")).strip() or str(author.get("family", "")).strip())
    ]
    for link in item.get("link", []):
        if not isinstance(link, dict):
            continue
        content_type = str(link.get("content-type") or "").lower()
        url_value = str(link.get("URL") or "")
        if "pdf" in content_type and url_value:
            record["pdf_url"] = url_value
            break
    record["source"] = {
        "name": "Crossref",
        "url": url,
        "fetched_at": fetched_at,
        "license": "",
    }
    return record


def _crossref_tog_records(venue_key: str, year: int, fetched_at: str) -> tuple[str, list[dict[str, Any]]]:
    config = VENUE_CONFIG[venue_key]
    filters = ",".join(
        [
            f"issn:{TOG_ISSN}",
            f"from-pub-date:{config['tog_from'].format(year=year)}",
            f"until-pub-date:{config['tog_until'].format(year=year)}",
            "type:journal-article",
        ]
    )
    params = {
        "filter": filters,
        "rows": 1000,
        "select": "DOI,title,subtitle,container-title,volume,issue,published-print,published-online,type,author,link",
    }
    url = f"{CROSSREF_BASE}?{urlencode(params)}"
    payload = fetch_json(url, timeout=90, retries=6)
    records = []
    for item in payload.get("message", {}).get("items", []):
        if record := _record_from_crossref_item(venue_key, year, item, fetched_at, url, "ACM Transactions on Graphics"):
            records.append(record)
    return url, records


def _crossref_proceedings_records(venue_key: str, year: int, fetched_at: str) -> tuple[str, list[dict[str, Any]]]:
    config = VENUE_CONFIG[venue_key]
    filters = ",".join(
        [
            f"from-pub-date:{config['proceedings_from'].format(year=year)}",
            f"until-pub-date:{config['proceedings_until'].format(year=year)}",
            "type:proceedings-article",
        ]
    )
    params = {
        "filter": filters,
        "query.event-acronym": config["event_acronym"],
        "rows": 1000,
        "select": "DOI,title,subtitle,container-title,event,type,author,link",
    }
    url = f"{CROSSREF_BASE}?{urlencode(params)}"
    payload = fetch_json(url, timeout=90, retries=6)
    records = []
    for item in payload.get("message", {}).get("items", []):
        if record := _record_from_crossref_item(venue_key, year, item, fetched_at, url, "SIGGRAPH proceedings"):
            records.append(record)
    return url, records


def _linklings_records(venue_key: str, year: int, fetched_at: str) -> tuple[str, list[dict[str, Any]]]:
    url = LINKLINGS_URLS.get((venue_key, year))
    if not url:
        return "", []
    text = fetch_text(url, timeout=90, retries=3)
    session_ids = set(
        re.findall(
            r'<tr class="agenda-item presentation-row primary-session[^"]*"[^>]*etypes="[^"]*sstype101[^"]*"[^>]*psid="([^"]+)"',
            text,
        )
    )
    records = []
    for session_id in session_ids:
        segment_match = re.search(
            r'<tr class="' + re.escape(session_id) + r' slots-slidedown".*?(?=<tr class="agenda-item presentation-row|<div class="[0-9]{4}-[0-9]{2}-[0-9]{2} date|\Z)',
            text,
            re.S,
        )
        if not segment_match:
            continue
        segment = segment_match.group(0)
        for title_match in re.finditer(
            r'<td class="title-speakers-td">(?P<body>.*?)(?=<td class="hide-med hide-small">|<td class="calendar-td">)',
            segment,
            re.S,
        ):
            body = title_match.group("body")
            title_html = re.split(r'<div class="(?:author|contributor|moderator) speakers-line">', body, 1)[0]
            title = _clean_title(re.sub(r"<.*?>", "", title_html))
            if not title:
                continue
            record = empty_record(venue_key, venue_name(venue_key), year, title)
            record["track"] = "Technical Papers"
            record["source"] = {
                "name": "SIGGRAPH Linklings program",
                "url": url,
                "fetched_at": fetched_at,
                "license": "",
            }
            records.append(record)
    return url, records


def _linklings_tech_type_pattern(venue_key: str, year: int) -> str:
    types = LINKLINGS_TECH_TYPES.get((venue_key, year), ["sstype101"])
    return "|".join(re.escape(item) for item in types)


def _linklings_wp_text_records(
    venue_key: str,
    year: int,
    text: str,
    source_url: str,
    fetched_at: str,
) -> list[dict[str, Any]]:
    type_pattern = _linklings_tech_type_pattern(venue_key, year)
    session_ids = set(
        re.findall(
            r'<tr class="agenda-item presentation-row[^"]*"[^>]*etypes="[^"]*(?:'
            + type_pattern
            + r')[^"]*"[^>]*psid="([^"]+)"',
            text,
        )
    )
    records = []
    for session_id in session_ids:
        segment_match = re.search(
            r'<tr class="' + re.escape(session_id) + r' slots-slidedown".*?(?=<tr class="agenda-item presentation-row|\Z)',
            text,
            re.S,
        )
        if not segment_match:
            continue
        segment = segment_match.group(0)
        for title_match in re.finditer(
            r'<td class="title-speakers-td">(?P<body>.*?)(?=<td class="hide-med hide-small">|<td class="calendar-td">)',
            segment,
            re.S,
        ):
            body = title_match.group("body")
            title_html = re.split(r'<div class="(?:author|contributor|presenter|moderator) speakers-line">', body, 1)[0]
            title = _clean_title(re.sub(r"<.*?>", "", title_html))
            if not title or title.lower() in {"interactive discussions"}:
                continue
            record = empty_record(venue_key, venue_name(venue_key), year, title)
            record["track"] = "Technical Papers"
            record["source"] = {
                "name": "SIGGRAPH Linklings WordPress program",
                "url": source_url,
                "fetched_at": fetched_at,
                "license": "",
            }
            records.append(record)
    return records


def _linklings_wp_records(venue_key: str, year: int, fetched_at: str) -> tuple[str, list[dict[str, Any]]]:
    url = LINKLINGS_WP_URLS.get((venue_key, year))
    if not url:
        return "", []
    text = fetch_text(url, timeout=90, retries=3)
    source_urls = [url]
    records = _linklings_wp_text_records(venue_key, year, text, url, fetched_at)
    snippet_urls = sorted(
        {
            html.unescape(match).replace("&amp;", "&")
            for match in re.findall(r'source="([^"]+linklings_snippets/[^"]+\.txt[^"]*)"', text)
        }
    )
    for snippet_url in snippet_urls:
        snippet_text = fetch_text(snippet_url, timeout=90, retries=3)
        source_urls.append(snippet_url)
        records.extend(_linklings_wp_text_records(venue_key, year, snippet_text, snippet_url, fetched_at))
    return "; ".join(source_urls), records


def _history_overview_records(venue_key: str, year: int, fetched_at: str) -> tuple[str, list[dict[str, Any]]]:
    url = HISTORY_OVERVIEW_URLS.get((venue_key, year))
    if not url:
        return "", []
    text = fetch_text(url, timeout=90, retries=3)
    records = []
    seen_titles = set()
    history_link_pattern = (
        r'<a href="(?P<link>https://history\.siggraph\.org/learning/[^"#?]+/)">'
        r"(?P<body>.*?)</a>"
    )
    for match in re.finditer(history_link_pattern, text, re.S):
        title = _clean_title(re.sub(r"<.*?>", " ", match.group("body")))
        title_key = normalize_title(title)
        if not title or title_key in seen_titles:
            continue
        seen_titles.add(title_key)
        record = empty_record(venue_key, venue_name(venue_key), year, title)
        record["track"] = "Technical Papers"
        record["project_url"] = match.group("link")
        record["source"] = {
            "name": "ACM SIGGRAPH History Archives",
            "url": url,
            "fetched_at": fetched_at,
            "license": "",
        }
        records.append(record)
    _enrich_history_details(records)
    return url, records


def _history_abstract(text: str) -> str:
    match = re.search(
        r"<u>Abstract:</u>.*?<ul[^>]*id=\"indentlist\"[^>]*>(?P<abstract>.*?)</ul>",
        text,
        re.S | re.I,
    )
    if not match:
        return ""
    return _clean_title(re.sub(r"<.*?>", " ", match.group("abstract")))


def _history_detail_metadata(record: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    url = str(record.get("project_url", ""))
    text = fetch_text(url, timeout=30, retries=1)
    authors = [
        _clean_title(author)
        for author in re.findall(r'<meta\s+name="citation_author"\s+content="([^"]+)"', text)
        if _clean_title(author)
    ]
    paper_url = ""
    doi = ""
    doi_match = re.search(r'https://dl\.acm\.org/doi/(?P<doi>10\.\d{4,9}/[^"\s<]+)', text)
    if doi_match:
        doi = html.unescape(doi_match.group("doi")).strip()
        paper_url = f"https://dl.acm.org/doi/{doi}"
    return (
        str(record.get("id", "")),
        {
            "abstract": _history_abstract(text),
            "authors": authors,
            "paper_url": paper_url,
            "doi": doi,
        },
    )


def _enrich_history_details(records: list[dict[str, Any]], *, workers: int = 12) -> None:
    records_by_id = {str(record.get("id", "")): record for record in records}
    candidates = [record for record in records if record.get("project_url")]
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(_history_detail_metadata, record) for record in candidates]
        for future in as_completed(futures):
            try:
                record_id, metadata = future.result()
            except Exception:
                continue
            record = records_by_id.get(record_id)
            if not record:
                continue
            if metadata.get("authors"):
                record["authors"] = metadata["authors"]
            for field in ("abstract", "paper_url", "doi"):
                if metadata.get(field):
                    record[field] = metadata[field]
            source = record.get("source") if isinstance(record.get("source"), dict) else {}
            name = str(source.get("name") or "").strip()
            if "detail pages" not in name:
                source["name"] = f"{name} detail pages".strip()
            record["source"] = source


def _append_source(existing: dict[str, Any], incoming: dict[str, Any]) -> None:
    incoming_source = incoming.get("source") if isinstance(incoming.get("source"), dict) else {}
    if not incoming_source:
        return
    source = existing.get("source") if isinstance(existing.get("source"), dict) else {}
    incoming_name = str(incoming_source.get("name") or "").strip()
    current_name = str(source.get("name") or "").strip()
    if incoming_name and incoming_name not in current_name:
        source["name"] = f"{current_name} + {incoming_name}".strip(" +")
    urls = [part.strip() for part in str(source.get("url") or "").split(";") if part.strip()]
    incoming_urls = [
        part.strip()
        for part in str(incoming_source.get("url") or "").split(";")
        if part.strip()
    ]
    for url in incoming_urls:
        if url not in urls:
            urls.append(url)
    if urls:
        source["url"] = "; ".join(urls)
    existing["source"] = source


def _merge_record(existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    updated = False
    for field in ("authors", "affiliations", "keywords"):
        if not existing.get(field) and incoming.get(field):
            existing[field] = incoming[field]
            updated = True
    for field in (
        "abstract",
        "tldr",
        "first_institute",
        "track",
        "presentation",
        "paper_url",
        "pdf_url",
        "arxiv_url",
        "project_url",
        "github_url",
        "doi",
    ):
        if not existing.get(field) and incoming.get(field):
            existing[field] = incoming[field]
            updated = True
    if updated:
        _append_source(existing, incoming)
    return existing


def harvest(venue_key: str, year: int) -> dict[str, Any]:
    if not supports(venue_key, year):
        raise ValueError(f"SIGGRAPH route unsupported for {venue_key}{year}")

    fetched_at = now_utc()
    records = []
    source_urls = []
    for source_url, source_records in [
        _crossref_proceedings_records(venue_key, year, fetched_at),
        _crossref_tog_records(venue_key, year, fetched_at),
        _linklings_records(venue_key, year, fetched_at),
        _linklings_wp_records(venue_key, year, fetched_at),
        _history_overview_records(venue_key, year, fetched_at),
    ]:
        records.extend(source_records)
        if source_url:
            source_urls.append(source_url)

    merged: dict[str, dict[str, Any]] = {}
    for record in records:
        if not record.get("title"):
            continue
        title_key = normalize_title(record["title"])
        if title_key in merged:
            _merge_record(merged[title_key], record)
        else:
            merged[title_key] = record
    return {
        "source": "siggraph",
        "venue_key": venue_key,
        "year": year,
        "source_url": "; ".join(source_urls),
        "fetched_at": fetched_at,
        "raw_count": len(records),
        "records": list(merged.values()),
    }
