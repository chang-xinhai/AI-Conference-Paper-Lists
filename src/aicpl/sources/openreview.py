"""OpenReview API2 harvester."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

from ..schema import empty_record, normalize_keywords, venue_name
from ..util import fetch_json, now_utc


OPENREVIEW_API2 = "https://api2.openreview.net/notes"
OPENREVIEW_API1 = "https://api.openreview.net/notes"

VENUE_IDS = {
    "ai4x": "AI4X.cc/{year}/Conference",
    "3dv": "3DV/{year}/Conference",
    "aistats": "aistats.org/AISTATS/{year}/Conference",
    "alt": "algorithmiclearningtheory.org/ALT/{year}/Conference",
    "automl": "automl.cc/AutoML/{year}/Conference",
    "iclr": "ICLR.cc/{year}/Conference",
    "icml": "ICML.cc/{year}/Conference",
    "nips": "NeurIPS.cc/{year}/Conference",
    "colm": "colmweb.org/COLM/{year}/Conference",
    "corl": "robot-learning.org/CoRL/{year}/Conference",
    "uai": "auai.org/UAI/{year}/Conference",
    "www": "ACM.org/TheWebConf/{year}/Conference",
}

SUPPORTED_YEARS = {
    "3dv": {2025, 2026},
    "www": {2024, 2025},
}

EXTRA_VENUE_IDS = {
    ("nips", 2021): [
        "NeurIPS.cc/2021/Track/Datasets_and_Benchmarks/Round1",
        "NeurIPS.cc/2021/Track/Datasets_and_Benchmarks/Round2",
    ],
    ("nips", 2022): [
        "NeurIPS.cc/2022/Track/Datasets_and_Benchmarks",
    ],
    ("nips", 2023): [
        "NeurIPS.cc/2023/Track/Datasets_and_Benchmarks",
    ],
    ("nips", 2024): [
        "NeurIPS.cc/2024/Datasets_and_Benchmarks_Track",
    ],
    ("nips", 2025): [
        "NeurIPS.cc/2025/Datasets_and_Benchmarks_Track",
    ],
}


def _value(field: Any, default: Any = "") -> Any:
    if isinstance(field, dict) and "value" in field:
        return field["value"]
    return field if field is not None else default


def _is_accepted_venue(venue_text: str) -> bool:
    lower = venue_text.lower()
    if any(token in lower for token in ["submitted", "reject", "withdraw", "desk"]):
        return False
    return True


def supports(venue_key: str, year: int) -> bool:
    if venue_key not in VENUE_IDS or year < 2020:
        return False
    return year in SUPPORTED_YEARS.get(venue_key, set(range(2020, 2100)))


def _fetch_notes(api_url: str, venue_id: str, *, limit: int = 1000) -> list[dict[str, Any]]:
    notes: list[dict[str, Any]] = []
    offset = 0
    while True:
        params = {
            "content.venueid": venue_id,
            "limit": limit,
            "offset": offset,
        }
        url = f"{api_url}?{urlencode(params)}"
        payload = fetch_json(url, timeout=60)
        batch = payload.get("notes", [])
        notes.extend(batch)
        if len(batch) < limit:
            break
        offset += limit
    return notes


def _venue_ids_for(venue_key: str, year: int) -> list[str]:
    venue_ids = [VENUE_IDS[venue_key].format(year=year)]
    venue_ids.extend(EXTRA_VENUE_IDS.get((venue_key, year), []))
    return venue_ids


def _fetch_notes_for_venue_id(venue_id: str, *, limit: int) -> tuple[str, list[dict[str, Any]]]:
    notes = _fetch_notes(OPENREVIEW_API2, venue_id, limit=limit)
    if notes:
        return OPENREVIEW_API2, notes
    return OPENREVIEW_API1, _fetch_notes(OPENREVIEW_API1, venue_id, limit=limit)


def _record_from_note(note: dict[str, Any], venue_key: str, year: int, fetched_at: str, api_url: str, venue_id: str) -> dict[str, Any] | None:
    content = note.get("content", {})
    venue_text = str(_value(content.get("venue"), "")).strip()
    if venue_text and not _is_accepted_venue(venue_text):
        return None
    title = str(_value(content.get("title"), "")).strip()
    if not title:
        return None
    record = empty_record(venue_key, venue_name(venue_key), year, title)
    record["abstract"] = str(_value(content.get("abstract"), "")).strip()
    record["authors"] = [str(author).strip() for author in _value(content.get("authors"), [])]
    record["keywords"] = normalize_keywords(_value(content.get("keywords"), []))
    record["track"] = str(_value(content.get("primary_area"), "")).strip()
    record["presentation"] = venue_text.replace(f"{venue_name(venue_key)} {year}", "").strip()
    record["paper_url"] = f"https://openreview.net/forum?id={note.get('forum') or note.get('id')}"
    pdf = str(_value(content.get("pdf"), "")).strip()
    if pdf:
        record["pdf_url"] = f"https://openreview.net{pdf}" if pdf.startswith("/") else pdf
    record["source"] = {
        "name": "OpenReview API",
        "url": f"{api_url}?content.venueid={venue_id}",
        "fetched_at": fetched_at,
        "license": str(note.get("license", "")),
    }
    return record


def harvest(venue_key: str, year: int, *, limit: int = 1000) -> dict[str, Any]:
    if not supports(venue_key, year):
        raise ValueError(f"OpenReview route unsupported for {venue_key}{year}")

    venue_ids = _venue_ids_for(venue_key, year)
    fetched_at = now_utc()
    note_sources = []
    source_urls = []
    for venue_id in venue_ids:
        api_url, venue_notes = _fetch_notes_for_venue_id(venue_id, limit=limit)
        note_sources.extend((api_url, note) for note in venue_notes)
        source_urls.append(f"{api_url}?content.venueid={venue_id}")
    records = [
        record
        for api_url, note in note_sources
        if (record := _record_from_note(
            note,
            venue_key,
            year,
            fetched_at,
            api_url,
            str(_value(note.get("content", {}).get("venueid"), "")) or venue_ids[0],
        ))
    ]
    unique_records = {record["id"]: record for record in records}

    return {
        "source": "openreview",
        "venue_key": venue_key,
        "year": year,
        "source_url": "; ".join(source_urls),
        "fetched_at": fetched_at,
        "raw_count": len(note_sources),
        "records": list(unique_records.values()),
    }
