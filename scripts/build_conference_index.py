#!/usr/bin/env python3
"""Build config/conferences.json from a Paper Copilot git checkout."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from collections import defaultdict
from pathlib import Path


def list_papercopilot_json_files(paperlists: Path) -> list[str]:
    output = subprocess.check_output(
        ["git", "ls-tree", "-r", "--name-only", "HEAD"],
        cwd=paperlists,
        text=True,
    )
    return [line for line in output.splitlines() if line.endswith(".json")]


def build_index(paperlists: Path, year_start: int) -> dict:
    by_conf: dict[str, list[int]] = defaultdict(list)
    all_files: dict[str, list[str]] = defaultdict(list)
    pattern = re.compile(r"^([^/]+)/[^/]*?(\d{4})\.json$")

    for path in list_papercopilot_json_files(paperlists):
        match = pattern.match(path)
        if not match:
            continue
        conf, year_text = match.groups()
        year = int(year_text)
        by_conf[conf].append(year)
        all_files[conf].append(path)

    conferences = []
    for conf in sorted(by_conf):
        years = sorted(set(by_conf[conf]))
        conferences.append(
            {
                "key": conf,
                "paper_copilot_dir": conf,
                "paper_copilot_years": years,
                "target_years": [year for year in years if year >= year_start],
                "paper_copilot_files": sorted(all_files[conf]),
            }
        )

    return {
        "schema_version": "0.1",
        "generated_from": "papercopilot/paperlists",
        "year_start": year_start,
        "conference_count": len(conferences),
        "conferences": conferences,
    }


def merge_existing_target_years(index: dict, existing_path: Path) -> dict:
    """Preserve manually added target years such as latest official proceedings."""
    if not existing_path.exists():
        return index

    existing = json.loads(existing_path.read_text(encoding="utf-8"))
    existing_targets = {
        conference["key"]: set(conference.get("target_years", []))
        for conference in existing.get("conferences", [])
    }
    for conference in index["conferences"]:
        target_years = set(conference.get("target_years", []))
        target_years.update(existing_targets.get(conference["key"], set()))
        conference["target_years"] = sorted(target_years)
    return index


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--paperlists",
        default="../.codex-tmp/paperlists",
        help="Path to a local papercopilot/paperlists git checkout.",
    )
    parser.add_argument("--year-start", type=int, default=2020)
    parser.add_argument("--output", default="config/conferences.json")
    parser.add_argument(
        "--merge-existing-targets",
        action="store_true",
        help="Preserve target_years already present in the output file.",
    )
    args = parser.parse_args()

    paperlists = Path(args.paperlists).resolve()
    output = Path(args.output)
    index = build_index(paperlists, args.year_start)
    if args.merge_existing_targets:
        index = merge_existing_target_years(index, output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(index, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {output} with {index['conference_count']} conferences")


if __name__ == "__main__":
    main()
