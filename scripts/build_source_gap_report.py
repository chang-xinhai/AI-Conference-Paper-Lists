#!/usr/bin/env python3
"""Build a machine-readable report of known latest-source gaps."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aicpl.util import now_utc, read_json, write_json  # noqa: E402


def next_action(status: str) -> str:
    if status == "partial":
        return "Wait for the complete official paper list before adding the year to the target matrix."
    if status == "incomplete":
        return "Keep the documented fallback and monitor the preferred official source for complete metadata."
    if status == "not_available":
        return "Monitor the official source; do not add an empty or partial year to the matrix."
    if status == "reachable":
        return "Inspect the reachable page and add a stricter availability parser before harvesting."
    return "No action needed."


def main() -> None:
    latest_path = ROOT / "data" / "reports" / "latest_source_probes.json"
    source_issues_path = ROOT / "config" / "source_issues.json"
    latest = read_json(latest_path)
    source_issues = read_json(source_issues_path)

    gaps = []
    for result in latest.get("results", []):
        status = result.get("status", "")
        if status == "available":
            continue
        gaps.append(
            {
                "id": result.get("id", ""),
                "venue_key": result.get("venue_key", ""),
                "year": result.get("year"),
                "status": status,
                "evidence": result.get("evidence", ""),
                "next_action": next_action(status),
            }
        )

    fallback_issues = []
    for target_id, issues in source_issues.get("issues", {}).items():
        for issue in issues:
            fallback_issues.append(
                {
                    "target_id": target_id,
                    "id": issue.get("id", ""),
                    "severity": issue.get("severity", ""),
                    "preferred_source": issue.get("preferred_source", ""),
                    "fallback_source": issue.get("fallback_source", ""),
                    "checked_at": issue.get("checked_at", ""),
                    "reason": issue.get("reason", ""),
                    "evidence": issue.get("evidence", []),
                }
            )

    summary = {
        "gap_count": len(gaps),
        "fallback_issue_count": len(fallback_issues),
        "by_status": {
            status: sum(1 for gap in gaps if gap["status"] == status)
            for status in sorted({gap["status"] for gap in gaps})
        },
    }
    report = {
        "schema_version": "0.1",
        "generated_at": now_utc(),
        "latest_source_probe": str(latest_path.relative_to(ROOT)),
        "source_issues": str(source_issues_path.relative_to(ROOT)),
        "summary": summary,
        "gaps": gaps,
        "fallback_issues": fallback_issues,
    }
    output = ROOT / "data" / "reports" / "source_gaps.json"
    write_json(output, report)
    print(f"source gaps: {summary}")
    print(f"report: {output}")


if __name__ == "__main__":
    main()
