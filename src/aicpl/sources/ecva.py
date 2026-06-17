"""ECVA/ECCV harvester."""

from __future__ import annotations

import html
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from urllib.parse import urljoin
from xml.etree import ElementTree as ET

from ..schema import empty_record, venue_name
from ..util import fetch_text, normalize_title, now_utc


DBLP_BASE = "https://dblp.org"
ECVA_BASE = "https://www.ecva.net"
ECVA_PAPERS_URL = f"{ECVA_BASE}/papers.php"
ECCV_VIRTUAL_URLS = {
    2024: "https://eccv.ecva.net/virtual/2024/papers.html",
}
ECCV_ACCEPTED_URLS = {
    2020: "https://eccv2020.eu/posters/",
    2022: "https://eccv2022.ecva.net/program/accepted-papers/",
}


def supports(venue_key: str, year: int) -> bool:
    return venue_key == "eccv" and year in {2020, 2022, 2024}


def _clean_title(title: str) -> str:
    title = html.unescape(re.sub(r"<.*?>", " ", title))
    return " ".join(title.split()).strip().strip('"')


def _entry_text(entry: ET.Element, tag: str) -> str:
    child = entry.find(tag)
    if child is None:
        return ""
    return "".join(child.itertext()).strip()


def _records_from_virtual(year: int, fetched_at: str) -> tuple[str, list[dict[str, Any]]]:
    url = ECCV_VIRTUAL_URLS[year]
    text = fetch_text(url, timeout=90, retries=3)
    records = []
    pattern = (
        rf'<li><a href="(?P<href>/virtual/{year}/'
        rf'(?P<presentation>poster|oral)/\d+)">(?P<title>.*?)</a></li>'
    )
    for match in re.finditer(pattern, text, re.S):
        title = _clean_title(match.group("title"))
        if not title:
            continue
        record = empty_record("eccv", venue_name("eccv"), year, title)
        record["presentation"] = match.group("presentation")
        record["paper_url"] = urljoin("https://eccv.ecva.net", match.group("href"))
        record["source"] = {
            "name": "ECVA virtual",
            "url": url,
            "fetched_at": fetched_at,
            "license": "",
        }
        records.append(record)
    _enrich_virtual_metadata(records)
    _merge_papers_index_metadata(records, year, fetched_at)
    return url, records


def _table_cells(row_html: str) -> list[str]:
    cells = []
    for cell in re.findall(r"<td[^>]*>(.*?)</td>", row_html, re.S):
        cells.append(_clean_title(cell))
    return cells


def _extract_abstract(text: str) -> str:
    match = re.search(r'<div id="abstract">(.*?)</div>', text, re.S)
    if not match:
        return ""
    abstract = _clean_title(match.group(1))
    if len(abstract) >= 2 and abstract[0] == abstract[-1] == '"':
        abstract = abstract[1:-1].strip()
    return abstract


def _json_ld_authors(text: str) -> list[str]:
    pattern = r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(?P<json>.*?)</script>'
    for match in re.finditer(pattern, text, re.S | re.I):
        try:
            payload = json.loads(html.unescape(match.group("json")).strip())
        except json.JSONDecodeError:
            continue
        authors = payload.get("author", [])
        if not isinstance(authors, list):
            continue
        names = []
        for author in authors:
            name = author.get("name", "") if isinstance(author, dict) else author
            clean_name = _clean_title(str(name))
            if clean_name:
                names.append(clean_name)
        if names:
            return names
    return []


def _organizer_authors(text: str) -> list[str]:
    match = re.search(r'<div class="event-organizers">(?P<authors>.*?)</div>', text, re.S | re.I)
    if not match:
        return []
    return [
        author
        for part in re.split(r"\s*[⋅·]\s*", match.group("authors"))
        if (author := _clean_title(part))
    ]


def _first_link_matching(text: str, patterns: list[str]) -> str:
    for href in re.findall(r'<a\b[^>]+href=["\'](?P<href>[^"\']+)["\']', text, re.I):
        href = html.unescape(href)
        lower = href.lower()
        if all(pattern in lower for pattern in patterns):
            return href
    return ""


def _project_link(text: str) -> str:
    match = re.search(
        r'<a\b(?=[^>]*class=["\'][^"\']*\bproject\b)(?=[^>]*href=["\'](?P<href>[^"\']+)["\'])',
        text,
        re.I,
    )
    return html.unescape(match.group("href")) if match else ""


def _virtual_detail_metadata(record: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    source_url = str(record.get("paper_url", ""))
    text = fetch_text(source_url, timeout=20, retries=1)
    abstract_match = re.search(
        r'<div class="abstract-text-inner">\s*(?P<abstract>.*?)\s*</div>',
        text,
        re.S | re.I,
    )
    pdf_url = _first_link_matching(text, ["papers_eccv/papers/", ".pdf"])
    if "-supp.pdf" in pdf_url.lower():
        pdf_url = ""
    project_url = _project_link(text)
    return (
        str(record.get("id", "")),
        {
            "abstract": _clean_title(abstract_match.group("abstract")) if abstract_match else "",
            "authors": _json_ld_authors(text) or _organizer_authors(text),
            "pdf_url": urljoin(source_url, pdf_url) if pdf_url else "",
            "project_url": urljoin(source_url, project_url) if project_url else "",
            "github_url": project_url if "github.com" in project_url.lower() else "",
        },
    )


def _enrich_virtual_metadata(records: list[dict[str, Any]], *, workers: int = 16) -> None:
    records_by_id = {str(record.get("id", "")): record for record in records}
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(_virtual_detail_metadata, record) for record in records]
        for future in as_completed(futures):
            try:
                record_id, metadata = future.result()
            except Exception:
                continue
            record = records_by_id.get(record_id)
            if not record:
                continue
            for field in ("abstract", "pdf_url", "project_url", "github_url"):
                if metadata.get(field):
                    record[field] = metadata[field]
            if metadata.get("authors"):
                record["authors"] = metadata["authors"]


def _enrich_ecva_abstracts(records: list[dict[str, Any]], *, workers: int = 16) -> None:
    def fetch_abstract(record: dict[str, Any]) -> tuple[str, str]:
        try:
            text = fetch_text(str(record.get("paper_url", "")), timeout=20, retries=1)
        except Exception:
            return str(record.get("id", "")), ""
        return str(record.get("id", "")), _extract_abstract(text)

    records_by_id = {str(record.get("id", "")): record for record in records}
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(fetch_abstract, record) for record in records]
        for future in as_completed(futures):
            record_id, abstract = future.result()
            if abstract:
                records_by_id[record_id]["abstract"] = abstract


def _records_from_papers_index(
    year: int,
    fetched_at: str,
    *,
    enrich_abstracts: bool = True,
) -> tuple[str, list[dict[str, Any]]]:
    text = fetch_text(ECVA_PAPERS_URL, timeout=90, retries=3)
    pattern = re.compile(
        rf'<dt class="ptitle"><br>\s*'
        rf'<a href=(?P<html>papers/eccv_{year}/papers_ECCV/html/[^>\s]+)>\s*'
        r"(?P<title>.*?)</a>\s*</dt><dd>\s*"
        r"(?P<authors>.*?)</dd>\s*<dd>(?P<links>.*?)(?=<dt class=\"ptitle\"|</dl>)",
        re.S,
    )
    records = []
    for match in pattern.finditer(text):
        title = _clean_title(match.group("title"))
        if not title:
            continue
        record = empty_record("eccv", venue_name("eccv"), year, title)
        authors_text = _clean_title(match.group("authors"))
        record["authors"] = [
            part.strip().rstrip("*")
            for part in authors_text.split(",")
            if part.strip()
        ]
        record["paper_url"] = urljoin(f"{ECVA_BASE}/", match.group("html"))
        links = match.group("links")
        if pdf_match := re.search(
            rf"href=['\"](?P<pdf>papers/eccv_{year}/papers_ECCV/papers/[^'\"]+\.pdf)",
            links,
        ):
            record["pdf_url"] = urljoin(f"{ECVA_BASE}/", pdf_match.group("pdf"))
        doi_pattern = r"https://link\.springer\.com/chapter/(?P<doi>10\.1007/[^\"<]+)"
        if doi_match := re.search(doi_pattern, links):
            record["doi"] = html.unescape(doi_match.group("doi")).strip()
        record["source"] = {
            "name": "ECVA papers index",
            "url": ECVA_PAPERS_URL,
            "fetched_at": fetched_at,
            "license": "",
        }
        records.append(record)
    if enrich_abstracts:
        _enrich_ecva_abstracts(records)
    return ECVA_PAPERS_URL, records


def _merge_papers_index_metadata(records: list[dict[str, Any]], year: int, fetched_at: str) -> None:
    _, index_records = _records_from_papers_index(year, fetched_at, enrich_abstracts=False)
    records_by_title = {
        normalize_title(str(record.get("title", ""))): record
        for record in records
        if record.get("title")
    }
    records_by_pdf = {
        str(record.get("pdf_url", "")): record
        for record in records
        if record.get("pdf_url")
    }
    for index_record in index_records:
        record = records_by_title.get(normalize_title(str(index_record.get("title", ""))))
        if not record:
            record = records_by_pdf.get(str(index_record.get("pdf_url", "")))
        if not record:
            continue
        if index_record.get("doi") and not record.get("doi"):
            record["doi"] = index_record["doi"]
        if index_record.get("pdf_url") and not record.get("pdf_url"):
            record["pdf_url"] = index_record["pdf_url"]
        source = record.get("source") if isinstance(record.get("source"), dict) else {}
        name = str(source.get("name") or "").strip()
        if "ECVA papers index" not in name:
            source["name"] = f"{name} + ECVA papers index".strip(" +")
        urls = [part.strip() for part in str(source.get("url") or "").split(";") if part.strip()]
        if ECVA_PAPERS_URL not in urls:
            urls.append(ECVA_PAPERS_URL)
        source["url"] = "; ".join(urls)
        record["source"] = source


def _records_from_accepted_page(year: int, fetched_at: str) -> tuple[str, list[dict[str, Any]]]:
    url = ECCV_ACCEPTED_URLS[year]
    text = fetch_text(url, timeout=90, retries=3)
    records_by_title: dict[str, dict[str, Any]] = {}
    for row_html in re.findall(r"<tr[^>]*>(.*?)</tr>", text, re.S):
        cells = _table_cells(row_html)
        if year == 2020:
            if len(cells) < 8 or not cells[0].isdigit():
                continue
            title = cells[3]
            authors = [f"{cells[1]} {cells[2]}".strip()] if cells[1] or cells[2] else []
            presentation = cells[7]
        else:
            if len(cells) < 3 or not cells[0].isdigit():
                continue
            title = cells[1]
            authors = [part.strip().rstrip("*") for part in cells[2].split(";") if part.strip()]
            presentation = ""
        if not title:
            continue
        record = empty_record("eccv", venue_name("eccv"), year, title)
        record["authors"] = authors
        record["presentation"] = presentation
        record["paper_url"] = url
        record["source"] = {
            "name": "ECVA accepted papers",
            "url": url,
            "fetched_at": fetched_at,
            "license": "",
        }
        records_by_title.setdefault(title.lower(), record)
    return url, list(records_by_title.values())


def _dblp_urls(year: int) -> list[str]:
    index_url = f"{DBLP_BASE}/db/conf/eccv/index.html"
    text = fetch_text(index_url, timeout=90, retries=3)
    pattern = rf'https://dblp\.org/db/conf/eccv/eccv{year}[^"#]*\.html'
    return [url[:-5] + ".xml" for url in sorted(set(re.findall(pattern, text)))]


def _records_from_dblp_url(year: int, url: str, fetched_at: str) -> list[dict[str, Any]]:
    text = fetch_text(url, timeout=10, retries=0)
    root = ET.fromstring(f"<root>{text}</root>")
    records = []
    for entry in root.iter():
        if entry.tag != "inproceedings":
            continue
        if _entry_text(entry, "year") != str(year):
            continue
        title = _clean_title(_entry_text(entry, "title"))
        if title.endswith("."):
            title = title[:-1]
        if not title:
            continue
        record = empty_record("eccv", venue_name("eccv"), year, title)
        record["authors"] = [
            " ".join("".join(author.itertext()).split())
            for author in entry.findall("author")
            if "".join(author.itertext()).strip()
        ]
        for ee in entry.findall("ee"):
            value = "".join(ee.itertext()).strip()
            if value and "wikidata.org" not in value:
                record["paper_url"] = value
                record["doi"] = value.split("doi.org/", 1)[1] if "doi.org/" in value else ""
                break
        record["source"] = {
            "name": "DBLP",
            "url": url,
            "fetched_at": fetched_at,
            "license": "",
            "key": entry.attrib.get("key", ""),
        }
        records.append(record)
    return records


def harvest(venue_key: str, year: int) -> dict[str, Any]:
    if not supports(venue_key, year):
        raise ValueError(f"ECVA route unsupported for {venue_key}{year}")

    fetched_at = now_utc()
    if year in ECCV_VIRTUAL_URLS:
        source_url, records = _records_from_virtual(year, fetched_at)
        if ECVA_PAPERS_URL not in source_url:
            source_url = f"{source_url}; {ECVA_PAPERS_URL}"
        return {
            "source": "ecva",
            "venue_key": venue_key,
            "year": year,
            "source_url": source_url,
            "fetched_at": fetched_at,
            "raw_count": len(records),
            "records": records,
        }
    if year in ECCV_ACCEPTED_URLS:
        source_url, records = _records_from_papers_index(year, fetched_at)
        return {
            "source": "ecva",
            "venue_key": venue_key,
            "year": year,
            "source_url": source_url,
            "fetched_at": fetched_at,
            "raw_count": len(records),
            "records": records,
        }

    records = []
    source_urls = []
    for url in _dblp_urls(year):
        try:
            records.extend(_records_from_dblp_url(year, url, fetched_at))
            source_urls.append(url)
        except Exception:
            continue
    return {
        "source": "ecva",
        "venue_key": venue_key,
        "year": year,
        "source_url": "; ".join(source_urls),
        "fetched_at": fetched_at,
        "raw_count": len(records),
        "records": records,
    }
