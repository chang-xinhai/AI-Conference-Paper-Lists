"""Small utility helpers shared by harvesters."""

from __future__ import annotations

import hashlib
import gzip
import json
import re
import time
import unicodedata
import zlib
from http.client import RemoteDisconnected
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
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


def fetch_text(url: str, *, timeout: int = 30, retries: int = 3) -> str:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(retries + 1):
        try:
            with urlopen(request, timeout=timeout) as response:
                data = response.read()
                encoding = response.headers.get("Content-Encoding", "").lower()
                if encoding == "gzip" or data.startswith(b"\x1f\x8b"):
                    data = gzip.decompress(data)
                elif encoding == "deflate":
                    data = zlib.decompress(data)
                return data.decode("utf-8", errors="replace")
        except HTTPError as error:
            retryable = error.code == 429 or 500 <= error.code < 600
            if not retryable or attempt == retries:
                raise
            retry_after = error.headers.get("Retry-After")
            delay = float(retry_after) if retry_after and retry_after.isdigit() else 2.0 * (attempt + 1)
            time.sleep(delay)
        except (ConnectionResetError, RemoteDisconnected, TimeoutError, URLError):
            if attempt == retries:
                raise
            time.sleep(2.0 * (attempt + 1))
    raise RuntimeError(f"failed to fetch {url}")


def fetch_json(url: str, *, timeout: int = 30, retries: int = 3) -> Any:
    return json.loads(fetch_text(url, timeout=timeout, retries=retries))
