#!/usr/bin/env python3
"""Enrich ACL Anthology records from the official bulk BibTeX export."""

from __future__ import annotations

import argparse
import gzip
import html
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aicpl.util import USER_AGENT, now_utc, read_json, write_json  # noqa: E402


BULK_BIB_URL = "https://aclanthology.org/anthology+abstracts.bib.gz"
ACL_CONFERENCES = ("acl", "emnlp", "naacl", "coling")


def _paper_key(url: str) -> str:
    path = urlparse(url).path.strip("/")
    return path[:-4] if path.endswith(".pdf") else path


def _clean_latex(value: str) -> str:
    value = html.unescape(value or "")
    value = value.replace("\n", " ")
    replacements = {
        r"---": "-",
        r"--": "-",
        r"\&": "&",
        r"\%": "%",
        r"\$": "$",
        r"\#": "#",
        r"\_": "_",
        r"\{": "{",
        r"\}": "}",
        r"{\\'e}": "é",
        r"{\\'E}": "É",
        r"{\\`e}": "è",
        r"{\\\"u}": "ü",
        r"{\\\"a}": "ä",
        r"{\\\"o}": "ö",
    }
    for old, new in replacements.items():
        value = value.replace(old, new)
    value = re.sub(r"\\url\{([^{}]+)\}", r"\1", value)
    value = re.sub(r"\\href\{([^{}]+)\}\{([^{}]+)\}", r"\2", value)
    value = re.sub(r"\\[a-zA-Z]+\*?(?:\[[^\]]*\])?", "", value)
    value = value.replace("{", "").replace("}", "")
    return " ".join(value.split()).strip()


def _scan_value(text: str, start: int) -> tuple[str, int]:
    pos = start
    while pos < len(text) and text[pos].isspace():
        pos += 1
    if pos >= len(text):
        return "", pos

    delimiter = text[pos]
    if delimiter == '"':
        pos += 1
        value_start = pos
        brace_depth = 0
        escaped = False
        chunks: list[str] = []
        while pos < len(text):
            char = text[pos]
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == "{":
                brace_depth += 1
            elif char == "}":
                brace_depth = max(0, brace_depth - 1)
            elif char == '"' and brace_depth == 0:
                chunks.append(text[value_start:pos])
                return "".join(chunks), pos + 1
            pos += 1
        return text[value_start:pos], pos

    if delimiter == "{":
        pos += 1
        value_start = pos
        depth = 1
        while pos < len(text):
            char = text[pos]
            if char == "\\":
                pos += 2
                continue
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    return text[value_start:pos], pos + 1
            pos += 1
        return text[value_start:pos], pos

    value_start = pos
    while pos < len(text) and text[pos] not in ",\n\r":
        pos += 1
    return text[value_start:pos].strip(), pos


def _field(entry: str, name: str) -> str:
    match = re.search(rf"(?im)^\s*{re.escape(name)}\s*=\s*", entry)
    if not match:
        return ""
    value, _ = _scan_value(entry, match.end())
    return _clean_latex(value)


def _entry_depth_delta(line: str) -> int:
    delta = 0
    escaped = False
    for char in line:
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
        elif char == "{":
            delta += 1
        elif char == "}":
            delta -= 1
    return delta


def _iter_bib_entries(url: str, timeout: int) -> Any:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=timeout) as response:
        with gzip.GzipFile(fileobj=response) as gz:
            lines: list[str] = []
            depth = 0
            for raw_line in gz:
                line = raw_line.decode("utf-8", "replace")
                if not lines and not line.lstrip().startswith("@"):
                    continue
                if line.lstrip().startswith("@") and not lines:
                    lines = [line]
                    depth = _entry_depth_delta(line)
                    continue
                if lines:
                    lines.append(line)
                    depth += _entry_depth_delta(line)
                    if depth <= 0:
                        yield "".join(lines)
                        lines = []
                        depth = 0


def _load_target_files(conference: str | None, year: int | None) -> list[tuple[Path, Path]]:
    pairs = []
    conferences = [conference] if conference else list(ACL_CONFERENCES)
    for conf in conferences:
        normalized_dir = ROOT / "data" / "normalized" / conf
        for normalized_path in sorted(normalized_dir.glob(f"{conf}*.json")):
            match = re.fullmatch(rf"{re.escape(conf)}(\d{{4}})\.json", normalized_path.name)
            if not match:
                continue
            file_year = int(match.group(1))
            if year and file_year != year:
                continue
            raw_path = ROOT / "data" / "raw" / "acl_anthology" / conf / normalized_path.name
            if raw_path.exists():
                pairs.append((normalized_path, raw_path))
    return pairs


def _index_records(datasets: list[dict[str, Any]], only_missing: bool) -> dict[str, list[dict[str, Any]]]:
    targets: dict[str, list[dict[str, Any]]] = {}
    for dataset in datasets:
        for record in dataset.get("records", []):
            if not record.get("paper_url"):
                continue
            if only_missing and record.get("doi") and record.get("abstract") and record.get("pdf_url"):
                continue
            targets.setdefault(_paper_key(str(record["paper_url"])), []).append(record)
    return targets


def _update_record(record: dict[str, Any], metadata: dict[str, str], fetched_at: str) -> bool:
    before = (record.get("doi", ""), record.get("abstract", ""), record.get("pdf_url", ""))
    if metadata.get("doi") and not record.get("doi"):
        record["doi"] = metadata["doi"]
    if metadata.get("abstract") and not record.get("abstract"):
        record["abstract"] = metadata["abstract"]
    if metadata.get("pdf_url") and not record.get("pdf_url"):
        record["pdf_url"] = metadata["pdf_url"]
    after = (record.get("doi", ""), record.get("abstract", ""), record.get("pdf_url", ""))
    if before == after:
        return False
    record.setdefault("source", {})["fetched_at"] = fetched_at
    record.setdefault("source", {})["metadata_url"] = BULK_BIB_URL
    return True


def _dataset_updated(dataset: dict[str, Any], fetched_at: str) -> bool:
    return any(
        record.get("source", {}).get("fetched_at") == fetched_at
        for record in dataset.get("records", [])
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--conference", choices=ACL_CONFERENCES)
    parser.add_argument("--year", type=int)
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--all-records", action="store_true", help="Match all records instead of only missing metadata.")
    args = parser.parse_args()

    pairs = _load_target_files(args.conference, args.year)
    if not pairs:
        raise SystemExit("no ACL Anthology normalized/raw pairs matched")

    normalized_by_path: dict[Path, dict[str, Any]] = {}
    raw_by_path: dict[Path, dict[str, Any]] = {}
    for normalized_path, raw_path in pairs:
        normalized_by_path[normalized_path] = read_json(normalized_path)
        raw_by_path[raw_path] = read_json(raw_path)

    targets = _index_records(list(normalized_by_path.values()) + list(raw_by_path.values()), not args.all_records)
    print(f"target_files={len(pairs)} target_records={len(targets)} source={BULK_BIB_URL}", flush=True)
    if not targets:
        return

    fetched_at = now_utc()
    matched = 0
    for index, entry in enumerate(_iter_bib_entries(BULK_BIB_URL, args.timeout), start=1):
        url = _field(entry, "url")
        if not url:
            continue
        key = _paper_key(url)
        records = targets.get(key)
        if not records:
            continue
        metadata = {
            "doi": _field(entry, "doi"),
            "abstract": _field(entry, "abstract"),
            "pdf_url": f"https://aclanthology.org/{key}.pdf",
        }
        updated = False
        for record in records:
            updated = _update_record(record, metadata, fetched_at) or updated
        if updated:
            matched += 1
        if matched and matched % 1000 == 0:
            print(f"scanned_entries={index} updated_keys={matched}/{len(targets)}", flush=True)

    written = 0
    for path, dataset in {**normalized_by_path, **raw_by_path}.items():
        if not _dataset_updated(dataset, fetched_at):
            continue
        before = path.read_text(encoding="utf-8")
        dataset["fetched_at"] = fetched_at
        write_json(path, dataset)
        after = path.read_text(encoding="utf-8")
        if before != after:
            written += 1

    print(f"updated_keys={matched} written_files={written}", flush=True)


if __name__ == "__main__":
    main()
