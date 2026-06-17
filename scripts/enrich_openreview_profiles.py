#!/usr/bin/env python3
"""Enrich OpenReview normalized records with public profile institutions."""

from __future__ import annotations

import argparse
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlencode, urlparse


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aicpl.sources import openreview  # noqa: E402
from aicpl.util import fetch_json, normalize_title, now_utc, read_json, write_json  # noqa: E402


PROFILE_API = "https://api2.openreview.net/profiles"
PROFILE_SOURCE_URL = f"{PROFILE_API}?id=<openreview-profile-id>"
RETRYABLE_STATUSES = {
    "http_429",
    "TimeoutError",
    "URLError",
    "RemoteDisconnected",
    "ConnectionResetError",
}


def _paper_key(record: dict[str, Any]) -> str:
    paper_url = str(record.get("paper_url") or "")
    parsed = urlparse(paper_url)
    forum = parse_qs(parsed.query).get("id", [""])[0].strip()
    return forum or normalize_title(str(record.get("title") or ""))


def _note_key(note: dict[str, Any]) -> str:
    return str(note.get("forum") or note.get("id") or "").strip()


def _note_authorids(note: dict[str, Any]) -> list[str]:
    content = note.get("content", {})
    raw_ids = openreview._value(content.get("authorids"), [])  # noqa: SLF001
    if not isinstance(raw_ids, list):
        return []
    return [str(author_id).strip() for author_id in raw_ids if str(author_id).strip()]


def _fetch_notes(
    venue_key: str,
    year: int,
    *,
    limit: int,
) -> tuple[list[dict[str, Any]], list[str]]:
    notes: list[dict[str, Any]] = []
    source_urls: list[str] = []
    for venue_id in openreview._venue_ids_for(venue_key, year):  # noqa: SLF001
        api_url, venue_notes = openreview._fetch_notes_for_venue_id(  # noqa: SLF001
            venue_id,
            limit=limit,
        )
        notes.extend(venue_notes)
        source_urls.append(f"{api_url}?content.venueid={venue_id}")
    for invitation in openreview.METADATA_INVITATIONS.get((venue_key, year), []):
        metadata_url = f"{openreview.OPENREVIEW_API1}?invitation={invitation}"
        notes.extend(
            openreview._fetch_notes_by_invitation(  # noqa: SLF001
                openreview.OPENREVIEW_API1,
                invitation,
                limit=limit,
            )
        )
        source_urls.append(metadata_url)
    return notes, source_urls


def _institution_name(entry: dict[str, Any]) -> str:
    institution = entry.get("institution")
    if not isinstance(institution, dict):
        return ""
    return str(institution.get("name") or "").strip()


def _year_value(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _profile_affiliation(profile: dict[str, Any], year: int) -> str:
    history = profile.get("content", {}).get("history", [])
    if not isinstance(history, list):
        return ""
    entries = [entry for entry in history if isinstance(entry, dict) and _institution_name(entry)]
    if not entries:
        return ""

    def sort_key(entry: dict[str, Any]) -> tuple[int, int]:
        start = _year_value(entry.get("start")) or 0
        end = _year_value(entry.get("end")) or 9999
        return (start, end)

    active = []
    past = []
    for entry in entries:
        start = _year_value(entry.get("start"))
        end = _year_value(entry.get("end"))
        if (start is None or start <= year) and (end is None or year <= end):
            active.append(entry)
        elif start is not None and start <= year:
            past.append(entry)
    if active:
        return _institution_name(max(active, key=sort_key))
    if past:
        return _institution_name(max(past, key=sort_key))
    return _institution_name(max(entries, key=sort_key))


def _compact_profile(
    author_id: str,
    year: int,
    fetched_at: str,
    *,
    timeout: int,
    retries: int,
) -> dict[str, Any]:
    source_url = f"{PROFILE_API}?{urlencode({'id': author_id})}"
    if not author_id.startswith("~"):
        return {
            "author_id": author_id,
            "source_url": source_url,
            "fetched_at": fetched_at,
            "status": "unsupported_authorid",
            "affiliation": "",
            "profile_count": 0,
        }
    try:
        payload = fetch_json(source_url, timeout=timeout, retries=retries)
    except HTTPError as error:
        return {
            "author_id": author_id,
            "source_url": source_url,
            "fetched_at": fetched_at,
            "status": f"http_{error.code}",
            "affiliation": "",
            "profile_count": 0,
        }
    except Exception as error:  # pragma: no cover - network-dependent reporting
        return {
            "author_id": author_id,
            "source_url": source_url,
            "fetched_at": fetched_at,
            "status": type(error).__name__,
            "affiliation": "",
            "profile_count": 0,
        }

    profiles = payload.get("profiles", [])
    if not isinstance(profiles, list):
        profiles = []
    affiliation = ""
    if profiles:
        affiliation = _profile_affiliation(profiles[0], year)
    return {
        "author_id": author_id,
        "source_url": source_url,
        "fetched_at": fetched_at,
        "status": "ok" if affiliation else "no_affiliation",
        "affiliation": affiliation,
        "profile_count": len(profiles),
    }


def _load_cache(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    data = read_json(path)
    return data.get("profiles", {}) if isinstance(data, dict) else {}


def _write_cache(path: Path, cache: dict[str, dict[str, Any]]) -> None:
    write_json(
        path,
        {
            "schema_version": "0.1",
            "source": "openreview_profiles",
            "source_url": PROFILE_SOURCE_URL,
            "count": len(cache),
            "profiles": dict(sorted(cache.items())),
        },
    )


def _cache_key(year: int, author_id: str) -> str:
    return f"{year}:{author_id}"


def _fetch_missing_profiles(
    author_ids: set[str],
    cache: dict[str, dict[str, Any]],
    *,
    year: int,
    workers: int,
    max_profiles: int,
    timeout: int,
    retries: int,
    cache_path: Path | None,
    checkpoint_every: int,
) -> int:
    missing = []
    for author_id in sorted(author_ids):
        cached = cache.get(_cache_key(year, author_id))
        if cached and str(cached.get("status") or "") not in RETRYABLE_STATUSES:
            continue
        missing.append(author_id)
    if max_profiles > 0:
        missing = missing[:max_profiles]
    if not missing:
        return 0
    fetched_at = now_utc()
    completed = 0
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(
                _compact_profile,
                author_id,
                year,
                fetched_at,
                timeout=timeout,
                retries=retries,
            ): author_id
            for author_id in missing
        }
        for future in as_completed(futures):
            author_id = futures[future]
            result = future.result()
            if str(result.get("status") or "") in RETRYABLE_STATUSES:
                cache.pop(_cache_key(year, author_id), None)
            else:
                cache[_cache_key(year, author_id)] = result
            completed += 1
            should_checkpoint = (
                cache_path is not None
                and checkpoint_every > 0
                and completed % checkpoint_every == 0
            )
            if should_checkpoint:
                _write_cache(cache_path, cache)
    return len(missing)


def _affiliations_for(
    author_ids: list[str],
    cache: dict[str, dict[str, Any]],
    *,
    year: int,
) -> list[str]:
    affiliations = []
    seen = set()
    for author_id in author_ids:
        affiliation = str(
            cache.get(_cache_key(year, author_id), {}).get("affiliation") or ""
        ).strip()
        if affiliation and affiliation not in seen:
            affiliations.append(affiliation)
            seen.add(affiliation)
    return affiliations


def _append_profile_source(record: dict[str, Any]) -> None:
    source = record.get("source") if isinstance(record.get("source"), dict) else {}
    name = str(source.get("name") or "").strip()
    if "OpenReview profiles" not in name:
        source["name"] = f"{name} + OpenReview profiles".strip(" +")
    urls = [part.strip() for part in str(source.get("url") or "").split(";") if part.strip()]
    if PROFILE_SOURCE_URL not in urls:
        urls.append(PROFILE_SOURCE_URL)
    source["url"] = "; ".join(urls)
    record["source"] = source


def enrich_one(
    venue_key: str,
    year: int,
    *,
    normalized_dir: Path,
    raw_dir: Path,
    cache_path: Path,
    limit: int,
    workers: int,
    max_profiles: int,
    profile_timeout: int,
    profile_retries: int,
    checkpoint_every: int,
    cache_only: bool,
    dry_run: bool,
) -> tuple[int, int, int]:
    normalized_path = normalized_dir / venue_key / f"{venue_key}{year}.json"
    raw_path = raw_dir / "openreview" / venue_key / f"{venue_key}{year}.json"
    if not normalized_path.exists():
        raise FileNotFoundError(normalized_path)

    normalized = read_json(normalized_path)
    if normalized.get("source") != "openreview":
        raise ValueError(f"{venue_key}{year} is source={normalized.get('source')}, not openreview")

    notes, note_source_urls = _fetch_notes(venue_key, year, limit=limit)
    note_authorids_by_key: dict[str, list[str]] = {}
    note_authorids_by_title: dict[str, list[str]] = {}
    for note in notes:
        authorids = _note_authorids(note)
        if not authorids:
            continue
        content = note.get("content", {})
        title = normalize_title(str(openreview._value(content.get("title"), "")))  # noqa: SLF001
        if key := _note_key(note):
            note_authorids_by_key[key] = authorids
        if title:
            note_authorids_by_title[title] = authorids

    records = normalized.get("records", [])
    paper_authorids: dict[str, list[str]] = {}
    unique_authorids: set[str] = set()
    for record in records:
        if record.get("affiliations"):
            continue
        authorids = note_authorids_by_key.get(_paper_key(record))
        if not authorids:
            title_key = normalize_title(str(record.get("title") or ""))
            authorids = note_authorids_by_title.get(title_key, [])
        if authorids:
            paper_authorids[str(record.get("id") or "")] = authorids
            unique_authorids.update(authorids)

    cache = _load_cache(cache_path)
    fetched_profiles = 0
    if not cache_only:
        fetched_profiles = _fetch_missing_profiles(
            unique_authorids,
            cache,
            year=year,
            workers=workers,
            max_profiles=max_profiles,
            timeout=profile_timeout,
            retries=profile_retries,
            cache_path=None if dry_run else cache_path,
            checkpoint_every=checkpoint_every,
        )

    updated_records = 0
    enriched_snapshot_records = []
    for record in records:
        authorids = paper_authorids.get(str(record.get("id") or ""), [])
        affiliations = _affiliations_for(authorids, cache, year=year)
        if affiliations:
            enriched_snapshot_records.append(
                {
                    "paper_id": record.get("id", ""),
                    "title": record.get("title", ""),
                    "paper_url": record.get("paper_url", ""),
                    "authorids": authorids,
                    "affiliations": affiliations,
                    "first_institute": affiliations[0],
                }
            )
            if not record.get("affiliations"):
                record["affiliations"] = affiliations
                record["first_institute"] = affiliations[0]
                _append_profile_source(record)
                updated_records += 1

    if dry_run:
        return updated_records, fetched_profiles, len(enriched_snapshot_records)

    if updated_records == 0:
        if fetched_profiles > 0:
            _write_cache(cache_path, cache)
        return updated_records, fetched_profiles, len(enriched_snapshot_records)

    fetched_at = now_utc()
    normalized["source_url"] = normalized.get("source_url") or "; ".join(note_source_urls)
    if PROFILE_SOURCE_URL not in normalized["source_url"]:
        normalized["source_url"] = f"{normalized['source_url']}; {PROFILE_SOURCE_URL}"
    normalized["fetched_at"] = fetched_at
    normalized["count"] = len(records)
    write_json(normalized_path, normalized)

    if raw_path.exists():
        raw_payload = read_json(raw_path)
        raw_by_id = {
            str(record.get("id") or ""): record
            for record in raw_payload.get("records", [])
        }
        for record in records:
            raw_record = raw_by_id.get(str(record.get("id") or ""))
            if raw_record is not None and record.get("affiliations"):
                raw_record["affiliations"] = record["affiliations"]
                raw_record["first_institute"] = record.get("first_institute", "")
                _append_profile_source(raw_record)
        raw_payload["source_url"] = normalized["source_url"]
        raw_payload["fetched_at"] = fetched_at
        write_json(raw_path, raw_payload)

    _write_cache(cache_path, cache)
    snapshot_path = raw_dir / "openreview_profiles" / venue_key / f"{venue_key}{year}.json"
    write_json(
        snapshot_path,
        {
            "schema_version": "0.1",
            "source": "openreview_profiles",
            "venue_key": venue_key,
            "year": year,
            "source_url": f"{'; '.join(note_source_urls)}; {PROFILE_SOURCE_URL}",
            "fetched_at": fetched_at,
            "count": len(enriched_snapshot_records),
            "profile_count": len(unique_authorids),
            "records": enriched_snapshot_records,
        },
    )
    return updated_records, fetched_profiles, len(enriched_snapshot_records)


def discover_targets(normalized_dir: Path) -> list[tuple[str, int]]:
    targets = []
    for path in sorted(normalized_dir.glob("*/*.json")):
        payload = read_json(path)
        if payload.get("source") != "openreview":
            continue
        records = payload.get("records", [])
        if any(not record.get("affiliations") for record in records):
            targets.append((str(payload["venue_key"]), int(payload["year"])))
    return targets


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--conference", action="append", default=[])
    parser.add_argument("--year", type=int, action="append", default=[])
    parser.add_argument(
        "--all",
        action="store_true",
        help="Enrich every source=openreview normalized file with missing affiliations.",
    )
    parser.add_argument("--normalized-dir", default="data/normalized")
    parser.add_argument("--raw-dir", default="data/raw")
    parser.add_argument("--cache-path", default="data/raw/openreview_profiles/profile_cache.json")
    parser.add_argument("--limit", type=int, default=1000)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument(
        "--max-profiles",
        type=int,
        default=50,
        help="Fetch at most this many missing profiles per venue/year; 0 means no cap.",
    )
    parser.add_argument("--profile-timeout", type=int, default=12)
    parser.add_argument("--profile-retries", type=int, default=1)
    parser.add_argument("--checkpoint-every", type=int, default=5)
    parser.add_argument(
        "--cache-only",
        action="store_true",
        help="Apply cached profile institutions without fetching new profiles.",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    normalized_dir = ROOT / args.normalized_dir
    raw_dir = ROOT / args.raw_dir
    cache_path = ROOT / args.cache_path
    if args.all:
        targets = discover_targets(normalized_dir)
    else:
        if len(args.conference) != len(args.year):
            parser.error("provide matching --conference and --year values, or use --all")
        targets = [
            (conference.lower(), year)
            for conference, year in zip(args.conference, args.year)
        ]

    total_updated = 0
    total_fetched = 0
    for venue_key, year in targets:
        updated, fetched, snapshot_count = enrich_one(
            venue_key,
            year,
            normalized_dir=normalized_dir,
            raw_dir=raw_dir,
            cache_path=cache_path,
            limit=args.limit,
            workers=max(1, args.workers),
            max_profiles=args.max_profiles,
            profile_timeout=max(1, args.profile_timeout),
            profile_retries=max(0, args.profile_retries),
            checkpoint_every=max(0, args.checkpoint_every),
            cache_only=args.cache_only,
            dry_run=args.dry_run,
        )
        total_updated += updated
        total_fetched += fetched
        print(
            f"{venue_key}{year}: updated_records={updated} "
            f"fetched_profiles={fetched} snapshot_records={snapshot_count}"
        )
    print(f"total: updated_records={total_updated} fetched_profiles={total_fetched}")


if __name__ == "__main__":
    main()
