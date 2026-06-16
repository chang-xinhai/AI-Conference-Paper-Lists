"""Paper Copilot fallback and comparison loader."""

from __future__ import annotations

from typing import Any

from ..schema import empty_record, normalize_authors, normalize_keywords, venue_name
from ..util import fetch_json, now_utc


RAW_BASE = "https://raw.githubusercontent.com/papercopilot/paperlists/main"


def path_for(venue_key: str, year: int) -> str:
    return f"{venue_key}/{venue_key}{year}.json"


def load(venue_key: str, year: int) -> list[dict[str, Any]]:
    return fetch_json(f"{RAW_BASE}/{path_for(venue_key, year)}", timeout=60)


def normalize(venue_key: str, year: int, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    fetched_at = now_utc()
    records = []
    for row in rows:
        title = str(row.get("title") or "").strip()
        if not title:
            continue
        record = empty_record(venue_key, venue_name(venue_key), year, title)
        record["abstract"] = str(row.get("abstract") or "").strip()
        record["authors"] = normalize_authors(row.get("author"))
        record["affiliations"] = normalize_authors(row.get("aff"))
        record["first_institute"] = record["affiliations"][0].split("+")[0].strip() if record["affiliations"] else ""
        record["status"] = str(row.get("status") or "accepted")
        record["track"] = str(row.get("track") or row.get("primary_area") or row.get("topic") or "")
        record["paper_url"] = str(row.get("site") or row.get("doi") or row.get("pdf") or "")
        record["pdf_url"] = str(row.get("pdf") or "")
        record["github_url"] = str(row.get("github") or "")
        record["project_url"] = str(row.get("project") or "")
        record["doi"] = str(row.get("doi") or "")
        record["keywords"] = normalize_keywords(row.get("keywords"))
        record["source"] = {
            "name": "Paper Copilot paperlists",
            "url": f"{RAW_BASE}/{path_for(venue_key, year)}",
            "fetched_at": fetched_at,
            "license": "",
        }
        records.append(record)
    return records


def harvest(venue_key: str, year: int) -> dict[str, Any]:
    rows = load(venue_key, year)
    return {
        "source": "papercopilot",
        "venue_key": venue_key,
        "year": year,
        "source_url": f"{RAW_BASE}/{path_for(venue_key, year)}",
        "fetched_at": now_utc(),
        "raw_count": len(rows),
        "records": normalize(venue_key, year, rows),
    }
