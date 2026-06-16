"""OpenReview API2 harvester."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

from ..schema import empty_record, normalize_keywords, venue_name
from ..util import fetch_json, now_utc


OPENREVIEW_API = "https://api2.openreview.net/notes"

VENUE_IDS = {
    "iclr": "ICLR.cc/{year}/Conference",
    "icml": "ICML.cc/{year}/Conference",
    "nips": "NeurIPS.cc/{year}/Conference",
    "colm": "colmweb.org/COLM/{year}/Conference",
    "corl": "robot-learning.org/CoRL/{year}/Conference",
}


def _value(field: Any, default: Any = "") -> Any:
    if isinstance(field, dict) and "value" in field:
        return field["value"]
    return field if field is not None else default


def supports(venue_key: str, year: int) -> bool:
    return venue_key in VENUE_IDS and year >= 2020


def harvest(venue_key: str, year: int, *, limit: int = 1000) -> dict[str, Any]:
    if not supports(venue_key, year):
        raise ValueError(f"OpenReview route unsupported for {venue_key}{year}")

    venue_id = VENUE_IDS[venue_key].format(year=year)
    notes: list[dict[str, Any]] = []
    offset = 0
    while True:
        params = {
            "content.venueid": venue_id,
            "limit": limit,
            "offset": offset,
        }
        url = f"{OPENREVIEW_API}?{urlencode(params)}"
        payload = fetch_json(url, timeout=60)
        batch = payload.get("notes", [])
        notes.extend(batch)
        if len(batch) < limit:
            break
        offset += limit

    fetched_at = now_utc()
    records = []
    for note in notes:
        content = note.get("content", {})
        title = str(_value(content.get("title"), "")).strip()
        if not title:
            continue
        record = empty_record(venue_key, venue_name(venue_key), year, title)
        record["abstract"] = str(_value(content.get("abstract"), "")).strip()
        record["authors"] = [str(author).strip() for author in _value(content.get("authors"), [])]
        record["keywords"] = normalize_keywords(_value(content.get("keywords"), []))
        record["track"] = str(_value(content.get("primary_area"), "")).strip()
        venue_text = str(_value(content.get("venue"), "")).strip()
        record["presentation"] = venue_text.replace(f"{venue_name(venue_key)} {year}", "").strip()
        record["paper_url"] = f"https://openreview.net/forum?id={note.get('forum') or note.get('id')}"
        pdf = str(_value(content.get("pdf"), "")).strip()
        if pdf:
            record["pdf_url"] = f"https://openreview.net{pdf}" if pdf.startswith("/") else pdf
        record["source"] = {
            "name": "OpenReview API2",
            "url": f"{OPENREVIEW_API}?content.venueid={venue_id}",
            "fetched_at": fetched_at,
            "license": str(note.get("license", "")),
        }
        records.append(record)

    return {
        "source": "openreview",
        "venue_key": venue_key,
        "year": year,
        "source_url": f"{OPENREVIEW_API}?content.venueid={venue_id}",
        "fetched_at": fetched_at,
        "raw_count": len(notes),
        "records": records,
    }
