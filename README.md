# AI-Conference-Paper-Lists

A source-backed conference paper list dataset for AI, ML, CV, NLP, graphics, and robotics venues.

This repository mirrors the conference coverage of [Paper Copilot paperlists](https://github.com/papercopilot/paperlists), but implements independent harvesting from official sources first. Paper Copilot is used as a fallback and cross-check source, not as the only source of truth.

## Goals

- Keep a timely paper list for major AI conferences from 2020 to the current year.
- Prefer official sources such as OpenReview, CVF Open Access, ACL Anthology, AAAI/OJS, PMLR, ACM, IEEE, RSS proceedings, and DBLP.
- Normalize records into a stable schema that downstream awesome lists can consume.
- Compare official harvests against Paper Copilot and flag suspicious gaps.
- Preserve raw snapshots, normalized data, and validation reports separately.

## Repository Layout

```text
config/
  conferences.json          # Paper Copilot-compatible conference/year index.
  sources.json              # Official source routing by conference.
data/
  raw/                      # Source snapshots, grouped by source/conference/year.
  normalized/               # Canonical normalized JSON records.
  reports/                  # Cross-check reports against Paper Copilot.
scripts/
  build_conference_index.py
  harvest.py
  validate_against_papercopilot.py
src/aicpl/
  schema.py
  sources/
```

## Data Model

Each normalized paper record uses the fields below when available:

```json
{
  "id": "cvpr2025:example-title",
  "title": "",
  "abstract": "",
  "authors": [],
  "affiliations": [],
  "first_institute": "",
  "venue": "CVPR",
  "venue_key": "cvpr",
  "year": 2025,
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
    "fetched_at": "",
    "license": ""
  }
}
```

## Source Policy

Official source priority:

1. OpenReview for OpenReview-hosted conferences.
2. CVF Open Access for CVPR, ICCV, ECCV, WACV, and 3DV when available.
3. ACL Anthology for ACL, EMNLP, NAACL, COLING.
4. PMLR for ICML, AISTATS, UAI, COLT, ACML, and related proceedings when available.
5. AAAI/OJS for AAAI.
6. RSS proceedings for RSS.
7. ACM, IEEE, DBLP, OpenAlex, Semantic Scholar, or official program pages for venues without a clean proceedings API.
8. Paper Copilot as fallback and validation baseline.

If our official harvest returns substantially fewer records than Paper Copilot for the same conference/year, the report must mark the channel as `needs_attention` rather than silently accepting the result.

When Paper Copilot appears to contain stale, truncated, or alternate titles, the strict validation status is preserved and the report may include `known_baseline_issues` from `config/baseline_issues.json`.

## Downstream Use

This repository is designed to support curated views such as [Awesome-Training-Free-Papers](https://github.com/chang-xinhai/Awesome-Training-Free-Papers).

## Status

Initial infrastructure is being built. Early commits prioritize reproducible source routing, validation reports, and a small set of reliable official harvesters before expanding to every venue/year.
