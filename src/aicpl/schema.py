"""Normalized paper record helpers."""

from __future__ import annotations

from typing import Any

from .util import now_utc, stable_id


def empty_record(venue_key: str, venue: str, year: int, title: str) -> dict[str, Any]:
    return {
        "id": stable_id(venue_key, year, title),
        "title": title,
        "abstract": "",
        "authors": [],
        "affiliations": [],
        "first_institute": "",
        "venue": venue,
        "venue_key": venue_key,
        "year": year,
        "status": "accepted",
        "track": "",
        "presentation": "",
        "paper_url": "",
        "pdf_url": "",
        "arxiv_url": "",
        "project_url": "",
        "github_url": "",
        "doi": "",
        "keywords": [],
        "source": {
            "name": "",
            "url": "",
            "fetched_at": now_utc(),
            "license": "",
        },
    }


def venue_name(venue_key: str) -> str:
    names = {
        "3dv": "3DV",
        "aaai": "AAAI",
        "acl": "ACL",
        "acml": "ACML",
        "acmmm": "ACM MM",
        "ai4x": "AI4X",
        "aistats": "AISTATS",
        "alt": "ALT",
        "automl": "AutoML",
        "coling": "COLING",
        "colm": "COLM",
        "colt": "COLT",
        "corl": "CoRL",
        "cvpr": "CVPR",
        "eccv": "ECCV",
        "emnlp": "EMNLP",
        "iccv": "ICCV",
        "iclr": "ICLR",
        "icml": "ICML",
        "icra": "ICRA",
        "ijcai": "IJCAI",
        "iros": "IROS",
        "kdd": "KDD",
        "naacl": "NAACL",
        "nips": "NeurIPS",
        "rss": "RSS",
        "siggraph": "SIGGRAPH",
        "siggraphasia": "SIGGRAPH Asia",
        "uai": "UAI",
        "wacv": "WACV",
        "www": "WWW",
    }
    return names.get(venue_key, venue_key.upper())


def normalize_authors(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        if ";" in value:
            return [part.strip() for part in value.split(";") if part.strip()]
        if "," in value:
            return [part.strip() for part in value.split(",") if part.strip()]
        return [value.strip()] if value.strip() else []
    return []


def normalize_keywords(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        parts = value.replace(";", ",").split(",")
        return [part.strip() for part in parts if part.strip()]
    return []
