"""DBLP TOC harvester for proceedings-style conference lists."""

from __future__ import annotations

from typing import Any
from urllib.parse import urljoin
from xml.etree import ElementTree as ET

from ..schema import empty_record, venue_name
from ..util import fetch_text, now_utc


DBLP_BASE = "https://dblp.org"

DBLP_PATHS = {
    "3dv": "3dim/3dv{year}",
    "aaai": "aaai/aaai{year}",
    "acmmm": "mm/mm{year}",
    "icra": "icra/icra{year}",
    "ijcai": "ijcai/ijcai{year}",
    "iros": "iros/iros{year}",
    "kdd": "kdd/kdd{year}",
    "siggraph": "siggraph/siggraph{year}",
    "siggraphasia": "siggrapha/siggrapha{year}",
    "www": "www/www{year}",
}


def supports(venue_key: str, year: int) -> bool:
    return venue_key in DBLP_PATHS and year >= 2020


def _entry_text(entry: ET.Element, tag: str) -> str:
    child = entry.find(tag)
    if child is None:
        return ""
    return "".join(child.itertext()).strip()


def _clean_title(title: str) -> str:
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


def harvest(venue_key: str, year: int) -> dict[str, Any]:
    if not supports(venue_key, year):
        raise ValueError(f"DBLP route unsupported for {venue_key}{year}")

    path = DBLP_PATHS[venue_key].format(year=year)
    url = f"{DBLP_BASE}/db/conf/{path}.xml"
    text = fetch_text(url, timeout=90, retries=6)
    fetched_at = now_utc()
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

    return {
        "source": "dblp",
        "venue_key": venue_key,
        "year": year,
        "source_url": url,
        "fetched_at": fetched_at,
        "raw_count": len(records),
        "records": records,
    }
