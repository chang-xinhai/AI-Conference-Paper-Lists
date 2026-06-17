"""PMLR volume harvester for configured venue/year volumes."""

from __future__ import annotations

import html
import re
from typing import Any
from urllib.parse import urljoin

from ..schema import empty_record, venue_name
from ..util import fetch_text, now_utc


PMLR_BASE = "https://proceedings.mlr.press"

# Seeded with high-confidence 2020+ volumes for common Paper Copilot venues.
# This map is intentionally explicit; ambiguous venues should not guess volumes.
PMLR_VOLUMES: dict[tuple[str, int], str] = {
    ("icml", 2020): "v119",
    ("icml", 2021): "v139",
    ("icml", 2022): "v162",
    ("icml", 2023): "v202",
    ("icml", 2024): "v235",
    ("icml", 2025): "v267",
    ("aistats", 2020): "v108",
    ("aistats", 2021): "v130",
    ("aistats", 2022): "v151",
    ("aistats", 2023): "v206",
    ("aistats", 2024): "v238",
    ("acml", 2020): "v129",
    ("acml", 2021): "v157",
    ("acml", 2022): "v189",
    ("acml", 2023): "v222",
    ("acml", 2024): "v260",
    ("acml", 2025): "v304",
    ("colt", 2020): "v125",
    ("colt", 2021): "v134",
    ("colt", 2022): "v178",
    ("colt", 2023): "v195",
    ("colt", 2024): "v247",
    ("colt", 2025): "v291",
    ("uai", 2020): "v124",
    ("uai", 2021): "v161",
    ("uai", 2022): "v180",
    ("uai", 2023): "v216",
    ("uai", 2024): "v244",
    ("uai", 2025): "v286",
    ("automl", 2022): "v188",
    ("automl", 2023): "v224",
    ("automl", 2024): "v256",
    ("automl", 2025): "v293",
    ("corl", 2021): "v164",
    ("corl", 2022): "v205",
    ("corl", 2023): "v229",
    ("corl", 2024): "v270",
    ("corl", 2025): "v305",
}


def supports(venue_key: str, year: int) -> bool:
    return (venue_key, year) in PMLR_VOLUMES


def harvest(venue_key: str, year: int) -> dict[str, Any]:
    volume = PMLR_VOLUMES.get((venue_key, year))
    if not volume:
        raise ValueError(f"PMLR volume unsupported for {venue_key}{year}")

    url = f"{PMLR_BASE}/{volume}/"
    text = fetch_text(url, timeout=90)
    fetched_at = now_utc()

    records = []
    for block in text.split('<div class="paper">')[1:]:
        block = block.split("</div>", 1)[0]
        title_match = re.search(r'<p class="title">(?P<title>.*?)</p>', block, re.S)
        if not title_match:
            continue
        title = html.unescape(re.sub(r"<.*?>", "", title_match.group("title")).strip())
        record = empty_record(venue_key, venue_name(venue_key), year, title)
        authors_match = re.search(r'<span class="authors">(?P<authors>.*?)</span>', block, re.S)
        if authors_match:
            authors_text = html.unescape(re.sub(r"<.*?>", "", authors_match.group("authors")))
            record["authors"] = [part.strip() for part in authors_text.split(",") if part.strip()]
        links = {
            label: href
            for href, label in re.findall(
                r'<a href="(?P<href>[^"]+)"[^>]*>(?P<label>abs|Download PDF|pdf)</a>',
                block,
            )
        }
        abs_href = links.get("abs")
        pdf_href = links.get("Download PDF") or links.get("pdf")
        if abs_href:
            record["paper_url"] = urljoin(url, abs_href)
        if pdf_href:
            record["pdf_url"] = urljoin(url, pdf_href)
        record["source"] = {
            "name": "PMLR",
            "url": url,
            "fetched_at": fetched_at,
            "license": "",
        }
        records.append(record)

    return {
        "source": "pmlr",
        "venue_key": venue_key,
        "year": year,
        "source_url": url,
        "fetched_at": fetched_at,
        "raw_count": len(records),
        "records": records,
    }
