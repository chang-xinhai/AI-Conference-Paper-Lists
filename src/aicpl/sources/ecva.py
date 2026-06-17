"""ECVA/ECCV harvester."""

from __future__ import annotations

import html
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from urllib.parse import urljoin
from xml.etree import ElementTree as ET

from ..schema import empty_record, venue_name
from ..util import fetch_text, now_utc


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


def _records_from_papers_index(year: int, fetched_at: str) -> tuple[str, list[dict[str, Any]]]:
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
    _enrich_ecva_abstracts(records)
    return ECVA_PAPERS_URL, records


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
