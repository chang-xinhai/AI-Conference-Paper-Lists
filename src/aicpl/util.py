"""Small utility helpers shared by harvesters."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen


USER_AGENT = "AI-Conference-Paper-Lists/0.1 (+https://github.com/chang-xinhai/AI-Conference-Paper-Lists)"


def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def slugify(text: str, *, max_length: int = 96) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_text.lower()).strip("-")
    slug = re.sub(r"-+", "-", slug)
    return slug[:max_length].strip("-") or "untitled"


def normalize_title(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip()).lower()


def stable_id(venue_key: str, year: int, title: str) -> str:
    digest = hashlib.sha1(normalize_title(title).encode("utf-8")).hexdigest()[:10]
    return f"{venue_key}{year}:{slugify(title, max_length=72)}:{digest}"


def read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2, sort_keys=False)
        file.write("\n")


def fetch_text(url: str, *, timeout: int = 30) -> str:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def fetch_json(url: str, *, timeout: int = 30) -> Any:
    return json.loads(fetch_text(url, timeout=timeout))
