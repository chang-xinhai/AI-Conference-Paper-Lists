# AGENTS.md

## Mission

This repository maintains **AI-Conference-Paper-Lists**, an independently harvested paper list dataset aligned with the conference coverage of `papercopilot/paperlists`.

The goal is not to replace official proceedings. The goal is to provide a normalized, reproducible, and frequently updated data layer for downstream curated repositories such as Awesome-Training-Free-Papers.

## Scope

The conference list should match Paper Copilot's directory-level conference coverage whenever possible.

Target years:
- collect from 2020 through the current year by default
- keep older Paper Copilot years discoverable in `config/conferences.json`
- do not fabricate unavailable future proceedings

## Data Layers

Use three layers:

- `data/raw/`: immutable-ish snapshots from a source, grouped by source/conference/year
- `data/normalized/`: canonical records generated from raw snapshots
- `data/reports/`: validation and cross-check reports

Do not manually edit generated raw snapshots. Fix the harvester instead.

## Source Priority

Prefer official sources in this order:
1. OpenReview
2. CVF Open Access
3. ACL Anthology
4. PMLR
5. AAAI/OJS
6. RSS proceedings
7. ACM, IEEE, DBLP, OpenAlex, Semantic Scholar, or official program pages
8. Paper Copilot fallback

Paper Copilot is used for:
- conference/year index discovery
- fallback metadata where official sources are unavailable
- cross-checking counts and title overlap

## Validation Rule

Every harvested conference/year should be compared with Paper Copilot when a matching Paper Copilot JSON exists.

If our normalized count is lower than Paper Copilot by more than the configured tolerance, mark the report as `needs_attention`.

Do not mark a harvester as healthy merely because it produced some records.

## Normalized Record Rules

Each normalized record should include:
- stable `id`
- title
- abstract when available
- authors
- affiliations and first institution when available
- venue key, venue name, year
- status, track, presentation when available
- paper, PDF, DOI, arXiv, project, and GitHub links when available
- source name, source URL, fetched timestamp

Use empty strings or empty arrays for unavailable fields. Do not guess missing affiliations or links.

## Commit Workflow

Commit often. Recommended sequence:
1. repository/config changes
2. harvester implementation
3. validation reports
4. generated data batches

Use Conventional Commits:
- `docs:` README or governance
- `config:` conference/source routing
- `feat:` harvester or validator
- `data:` harvested or normalized data
- `fix:` source parsing or schema corrections
- `chore:` cleanup

## Quality Checklist

- Does the conference/year exist in Paper Copilot's index?
- Is the selected official source documented in `config/sources.json`?
- Does the raw snapshot include `fetched_at` and `source_url`?
- Does the normalized file parse as JSON?
- Does the validation report compare against Paper Copilot if available?
- If Paper Copilot has many more records, is the channel marked `needs_attention`?
