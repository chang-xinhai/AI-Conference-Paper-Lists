#!/usr/bin/env python3
"""Probe latest-year official sources that are not yet harvested."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlencode


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aicpl.util import fetch_json, fetch_text, now_utc, write_json  # noqa: E402


OPENREVIEW_API2 = "https://api2.openreview.net/notes"
CROSSREF_API = "https://api.crossref.org/works"
PMLR_HOME = "https://proceedings.mlr.press/"


def http_probe(probe: dict[str, Any]) -> dict[str, Any]:
    result = {**probe, "status": "not_available", "evidence": ""}
    try:
        text = fetch_text(probe["url"], timeout=20, retries=1)
    except Exception as exc:  # noqa: BLE001 - probes should report and continue.
        result["evidence"] = f"{type(exc).__name__}: {exc}"
        return result

    result["http_ok"] = True
    result["response_chars"] = len(text)
    available_regex = probe.get("available_regex")
    unavailable_regex = probe.get("unavailable_regex")
    if unavailable_regex and re.search(unavailable_regex, text, re.I | re.S):
        result["status"] = "not_available"
        result["evidence"] = f"Matched unavailable_regex: {unavailable_regex}"
    elif available_regex and re.search(available_regex, text, re.I | re.S):
        result["status"] = "available"
        result["evidence"] = f"Matched available_regex: {available_regex}"
    elif available_regex:
        result["status"] = "not_available"
        result["evidence"] = f"Did not match available_regex: {available_regex}"
    else:
        result["status"] = "reachable"
        result["evidence"] = "URL is reachable, but no availability regex was configured."
    return result


def openreview_probe(probe: dict[str, Any]) -> dict[str, Any]:
    venue_ids = probe["venue_ids"]
    counts = {}
    for venue_id in venue_ids:
        url = f"{OPENREVIEW_API2}?{urlencode({'content.venueid': venue_id, 'limit': 1})}"
        try:
            payload = fetch_json(url, timeout=20, retries=1)
        except Exception as exc:  # noqa: BLE001
            counts[venue_id] = {"error": f"{type(exc).__name__}: {exc}", "count": 0}
            continue
        counts[venue_id] = {"count": len(payload.get("notes", [])), "url": url}
    total = sum(item.get("count", 0) for item in counts.values())
    status = "not_available"
    if total:
        status = "partial" if probe.get("partial") else "available"
    evidence = "OpenReview returned zero notes."
    if total:
        evidence = (
            "OpenReview returned notes for a partial track only."
            if probe.get("partial")
            else "OpenReview returned at least one note."
        )
    return {
        **probe,
        "status": status,
        "note_count_sample": total,
        "venue_counts": counts,
        "evidence": evidence,
    }


def pmlr_home_probe(probe: dict[str, Any], home_text: str) -> dict[str, Any]:
    terms = probe["terms"]
    matches = []
    lower = home_text.lower()
    for term in terms:
        index = lower.find(term.lower())
        if index >= 0:
            matches.append({"term": term, "snippet": home_text[index : index + 240]})
    return {
        **probe,
        "status": "available" if matches else "not_available",
        "matches": matches,
        "evidence": "Matched PMLR homepage terms." if matches else "No configured PMLR terms found on homepage.",
    }


def crossref_event_probe(probe: dict[str, Any]) -> dict[str, Any]:
    event_name = probe["event_name"]
    params = {
        "filter": f"prefix:{probe.get('prefix', '10.1145')},type:proceedings-article,from-pub-date:{probe['year']}-01-01,until-pub-date:{probe['year']}-12-31",
        probe.get("query_field", "query.event-name"): probe["query_value"],
        "rows": 1000,
        "cursor": "*",
        "select": "DOI,title,event,type",
    }
    relevant = 0
    pages = 0
    cursor = "*"
    samples = []
    try:
        while pages < 3:
            params["cursor"] = cursor
            url = f"{CROSSREF_API}?{urlencode(params)}"
            payload = fetch_json(url, timeout=30, retries=1)
            items = payload.get("message", {}).get("items", [])
            pages += 1
            for item in items:
                event = item.get("event") or {}
                if str(event.get("name") or "").lower() == event_name.lower():
                    relevant += 1
                    if len(samples) < 5:
                        samples.append({"doi": item.get("DOI", ""), "title": item.get("title", [""])[0]})
            next_cursor = payload.get("message", {}).get("next-cursor")
            if not items or not next_cursor or next_cursor == cursor:
                break
            cursor = next_cursor
    except Exception as exc:  # noqa: BLE001
        return {**probe, "status": "not_available", "evidence": f"{type(exc).__name__}: {exc}"}

    min_expected = probe.get("min_expected_count", 200)
    if relevant == 0:
        status = "not_available"
    elif relevant < min_expected:
        status = "incomplete"
    else:
        status = "available"
    return {
        **probe,
        "status": status,
        "relevant_count": relevant,
        "min_expected_count": min_expected,
        "sample_records": samples,
        "evidence": f"Crossref exact event records: {relevant}; expected at least {min_expected}.",
    }


PROBES: list[dict[str, Any]] = [
    {"id": "acl2026-official-accepted-page", "venue_key": "acl", "year": 2026, "kind": "http", "url": "https://2026.aclweb.org/program/accepted_papers/", "available_regex": "class=\"paper|accepted paper|paper-title", "unavailable_regex": "coming soon"},
    {"id": "acl2026-acl-anthology", "venue_key": "acl", "year": 2026, "kind": "http", "url": "https://aclanthology.org/events/acl-2026/", "available_regex": "class=\"acl-paper-title\""},
    {"id": "acl2026-openreview-industry-partial", "venue_key": "acl", "year": 2026, "kind": "openreview", "venue_ids": ["aclweb.org/ACL/2026/Industry_Track"], "partial": True, "reason": "ACL 2026 Industry Track is visible on OpenReview, but the official accepted-papers page and ACL Anthology event page do not yet expose the complete ACL 2026 paper list."},
    {"id": "naacl2026-acl-anthology", "venue_key": "naacl", "year": 2026, "kind": "http", "url": "https://aclanthology.org/events/naacl-2026/", "available_regex": "class=\"acl-paper-title\""},
    {"id": "emnlp2026-acl-anthology", "venue_key": "emnlp", "year": 2026, "kind": "http", "url": "https://aclanthology.org/events/emnlp-2026/", "available_regex": "class=\"acl-paper-title\""},
    {"id": "coling2026-acl-anthology", "venue_key": "coling", "year": 2026, "kind": "http", "url": "https://aclanthology.org/events/coling-2026/", "available_regex": "class=\"acl-paper-title\""},
    {"id": "eccv2026-openreview", "venue_key": "eccv", "year": 2026, "kind": "openreview", "venue_ids": ["ECCV/2026/Conference", "ECCV.cc/2026/Conference", "eccv.ecva.net/2026/Conference", "thecvf.com/ECCV/2026/Conference"]},
    {"id": "neurips2026-openreview", "venue_key": "nips", "year": 2026, "kind": "openreview", "venue_ids": ["NeurIPS.cc/2026/Conference", "NeurIPS.cc/2026/Datasets_and_Benchmarks_Track"]},
    {"id": "uai2026-openreview", "venue_key": "uai", "year": 2026, "kind": "openreview", "venue_ids": ["auai.org/UAI/2026/Conference"]},
    {"id": "corl2026-openreview", "venue_key": "corl", "year": 2026, "kind": "openreview", "venue_ids": ["robot-learning.org/CoRL/2026/Conference"]},
    {"id": "colm2026-openreview", "venue_key": "colm", "year": 2026, "kind": "openreview", "venue_ids": ["colmweb.org/COLM/2026/Conference"]},
    {"id": "automl2026-openreview", "venue_key": "automl", "year": 2026, "kind": "openreview", "venue_ids": ["automl.cc/AutoML/2026/Conference"]},
    {"id": "acml2026-openreview", "venue_key": "acml", "year": 2026, "kind": "openreview", "venue_ids": ["ACML.org/2026/Conference", "ACML.org/2026/Journal_Track"]},
    {"id": "iros2026-papercept", "venue_key": "iros", "year": 2026, "kind": "http", "url": "https://ras.papercept.net/conferences/conferences/IROS26/program/IROS26_ContentListWeb_1.html", "available_regex": "class=\"pTtl\""},
    {"id": "acmmm2026-accepted", "venue_key": "acmmm", "year": 2026, "kind": "http", "url": "https://2026.acmmm.org/accepted-papers/", "available_regex": "accepted|paper"},
    {"id": "acmmm2026-crossref-acm", "venue_key": "acmmm", "year": 2026, "kind": "crossref_event", "query_value": "The 34th ACM International Conference on Multimedia", "event_name": "MM '26: The 34th ACM International Conference on Multimedia", "min_expected_count": 500},
    {"id": "siggraph2026-technical-papers", "venue_key": "siggraph", "year": 2026, "kind": "http", "url": "https://s2026.siggraph.org/program/technical-papers/", "available_regex": "program-item|paper-title", "unavailable_regex": "publication date of accepted papers is 3 July 2026|publication date for both"},
    {"id": "siggraphasia2026-technical-papers", "venue_key": "siggraphasia", "year": 2026, "kind": "http", "url": "https://asia.siggraph.org/2026/submissions/technical-papers/", "available_regex": "program-item|paper-title", "unavailable_regex": "publication date of accepted papers.*9 November 2026"},
    {"id": "kdd2026-crossref-acm", "venue_key": "kdd", "year": 2026, "kind": "crossref_event", "query_value": "The 32nd ACM SIGKDD Conference on Knowledge Discovery and Data Mining", "event_name": "KDD '26: The 32nd ACM SIGKDD Conference on Knowledge Discovery and Data Mining", "min_expected_count": 200},
    {"id": "aistats2026-pmlr", "venue_key": "aistats", "year": 2026, "kind": "pmlr_home", "terms": ["AISTATS 2026", "Artificial Intelligence and Statistics 2026", "29th International Conference on Artificial Intelligence and Statistics"]},
    {"id": "acml2026-pmlr", "venue_key": "acml", "year": 2026, "kind": "pmlr_home", "terms": ["ACML 2026", "Asian Conference on Machine Learning 2026"]},
    {"id": "corl2026-pmlr", "venue_key": "corl", "year": 2026, "kind": "pmlr_home", "terms": ["CoRL 2026", "Conference on Robot Learning 2026"]},
    {"id": "uai2026-pmlr", "venue_key": "uai", "year": 2026, "kind": "pmlr_home", "terms": ["UAI 2026", "Uncertainty in Artificial Intelligence 2026", "Forty-second Conference on Uncertainty in Artificial Intelligence"]},
    {"id": "automl2026-pmlr", "venue_key": "automl", "year": 2026, "kind": "pmlr_home", "terms": ["AutoML 2026", "Automated Machine Learning 2026"]},
]


def main() -> None:
    pmlr_home_text = ""
    results = []
    for probe in PROBES:
        kind = probe["kind"]
        if kind == "http":
            results.append(http_probe(probe))
        elif kind == "openreview":
            results.append(openreview_probe(probe))
        elif kind == "pmlr_home":
            if not pmlr_home_text:
                pmlr_home_text = re.sub(r"\s+", " ", fetch_text(PMLR_HOME, timeout=30, retries=1))
            results.append(pmlr_home_probe(probe, pmlr_home_text))
        elif kind == "crossref_event":
            results.append(crossref_event_probe(probe))
        else:
            results.append({**probe, "status": "not_available", "evidence": f"Unknown probe kind: {kind}"})

    summary = {
        "available": sum(1 for result in results if result["status"] == "available"),
        "incomplete": sum(1 for result in results if result["status"] == "incomplete"),
        "not_available": sum(1 for result in results if result["status"] == "not_available"),
        "partial": sum(1 for result in results if result["status"] == "partial"),
        "reachable": sum(1 for result in results if result["status"] == "reachable"),
    }
    report = {
        "schema_version": "0.1",
        "generated_at": now_utc(),
        "summary": summary,
        "results": results,
    }
    output = ROOT / "data" / "reports" / "latest_source_probes.json"
    write_json(output, report)
    print(f"latest source probes: {summary}")
    print(f"report: {output}")


if __name__ == "__main__":
    main()
