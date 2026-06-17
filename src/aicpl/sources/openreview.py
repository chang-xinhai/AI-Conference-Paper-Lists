"""OpenReview API2 harvester."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

from ..schema import empty_record, normalize_keywords, venue_name
from ..util import fetch_json, normalize_title, now_utc


OPENREVIEW_API2 = "https://api2.openreview.net/notes"
OPENREVIEW_API1 = "https://api.openreview.net/notes"

VENUE_IDS = {
    "ai4x": "AI4X.cc/{year}/Conference",
    "3dv": "3DV/{year}/Conference",
    "acml": "ACML.org/{year}/Conference",
    "acmmm": "acmmm.org/ACMMM/{year}/Conference",
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
    ("acml", 2026): [
        "ACML.org/2026/Journal_Track",
    ],
    ("acmmm", 2026): [
        "acmmm.org/ACMMM/2026/Dataset_Track",
        "acmmm.org/ACMMM/2026/Brave_New_Ideas_Track",
        "acmmm.org/ACMMM/2026/Open_Source_Software_Track",
    ],
    ("automl", 2025): [
        "automl.cc/AutoML/2025/ABCD_Track",
    ],
    ("automl", 2026): [
        "automl.cc/AutoML/2026/ABCD_Track",
        "automl.cc/AutoML/2026/Hot_Off_the_Press_Track",
        "automl.cc/AutoML/2026/Late_Breaking_Track",
    ],
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

VENUE_ID_OVERRIDES = {
    ("automl", 2025): [
        "automl.cc/AutoML/2025/Methods_Track",
    ],
    ("automl", 2026): [
        "automl.cc/AutoML/2026/Methods_Track",
    ],
}

METADATA_INVITATIONS = {
    ("iclr", 2020): [
        "ICLR.cc/2020/Conference/-/Blind_Submission",
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


def _doi(content: dict[str, Any]) -> str:
    value = _value(content.get("DOI"), "") or _value(content.get("doi"), "")
    text = str(value or "").strip()
    for prefix in (
        "https://doi.org/",
        "http://doi.org/",
        "https://dx.doi.org/",
        "http://dx.doi.org/",
    ):
        if text.lower().startswith(prefix):
            return text[len(prefix) :].strip()
    return text


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
    venue_ids = [
        venue_id.format(year=year)
        for venue_id in VENUE_ID_OVERRIDES.get(
            (venue_key, year),
            [VENUE_IDS[venue_key]],
        )
    ]
    venue_ids.extend(EXTRA_VENUE_IDS.get((venue_key, year), []))
    return venue_ids


def _fetch_notes_for_venue_id(venue_id: str, *, limit: int) -> tuple[str, list[dict[str, Any]]]:
    notes = _fetch_notes(OPENREVIEW_API2, venue_id, limit=limit)
    if notes:
        return OPENREVIEW_API2, notes
    return OPENREVIEW_API1, _fetch_notes(OPENREVIEW_API1, venue_id, limit=limit)


def _fetch_notes_by_invitation(api_url: str, invitation: str, *, limit: int = 1000) -> list[dict[str, Any]]:
    notes: list[dict[str, Any]] = []
    offset = 0
    while True:
        params = {
            "invitation": invitation,
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


def _tldr(content: dict[str, Any]) -> str:
    return str(
        _value(content.get("TLDR"), "")
        or _value(content.get("tldr"), "")
        or _value(content.get("TL;DR"), "")
        or _value(content.get("tl;dr"), "")
    ).strip()


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
    record["tldr"] = _tldr(content)
    record["authors"] = [str(author).strip() for author in _value(content.get("authors"), [])]
    record["keywords"] = normalize_keywords(_value(content.get("keywords"), []))
    record["track"] = str(_value(content.get("primary_area"), "")).strip()
    record["presentation"] = venue_text.replace(f"{venue_name(venue_key)} {year}", "").strip()
    record["paper_url"] = f"https://openreview.net/forum?id={note.get('forum') or note.get('id')}"
    pdf = str(_value(content.get("pdf"), "")).strip()
    if pdf:
        record["pdf_url"] = f"https://openreview.net{pdf}" if pdf.startswith("/") else pdf
    record["doi"] = _doi(content)
    record["source"] = {
        "name": "OpenReview API",
        "url": f"{api_url}?content.venueid={venue_id}",
        "fetched_at": fetched_at,
        "license": str(note.get("license", "")),
    }
    return record


def _enrich_from_metadata_note(record: dict[str, Any], note: dict[str, Any], source_url: str) -> None:
    content = note.get("content", {})
    abstract = str(_value(content.get("abstract"), "")).strip()
    if abstract and not record.get("abstract"):
        record["abstract"] = abstract
    tldr = _tldr(content)
    if tldr and not record.get("tldr"):
        record["tldr"] = tldr
    keywords = normalize_keywords(_value(content.get("keywords"), []))
    if keywords and not record.get("keywords"):
        record["keywords"] = keywords
    pdf = str(_value(content.get("pdf"), "")).strip()
    if pdf and not record.get("pdf_url"):
        record["pdf_url"] = f"https://openreview.net{pdf}" if pdf.startswith("/") else pdf
    source = record.get("source") if isinstance(record.get("source"), dict) else {}
    name = str(source.get("name") or "").strip()
    if "OpenReview submission metadata" not in name:
        source["name"] = f"{name} + OpenReview submission metadata".strip(" +")
    urls = [part.strip() for part in str(source.get("url") or "").split(";") if part.strip()]
    if source_url not in urls:
        urls.append(source_url)
    source["url"] = "; ".join(urls)
    record["source"] = source


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
    metadata_source_urls = []
    if invitations := METADATA_INVITATIONS.get((venue_key, year)):
        records_by_title = {
            normalize_title(record["title"]): record
            for record in unique_records.values()
            if record.get("title")
        }
        for invitation in invitations:
            metadata_url = f"{OPENREVIEW_API1}?invitation={invitation}"
            metadata_source_urls.append(metadata_url)
            for note in _fetch_notes_by_invitation(OPENREVIEW_API1, invitation, limit=limit):
                content = note.get("content", {})
                title = normalize_title(str(_value(content.get("title"), "")))
                if title in records_by_title:
                    _enrich_from_metadata_note(records_by_title[title], note, metadata_url)

    return {
        "source": "openreview",
        "venue_key": venue_key,
        "year": year,
        "source_url": "; ".join(source_urls + metadata_source_urls),
        "fetched_at": fetched_at,
        "raw_count": len(note_sources),
        "records": list(unique_records.values()),
    }
