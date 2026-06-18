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

Use `scripts/rebuild_coverage.py` after targeted harvests or validations so `data/reports/coverage.json` reflects the full matrix rather than only the latest subset.

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
- affiliations and first institution are optional; keep already collected values, but do not require collecting them for missing records
- venue key, venue name, year
- status, track, presentation when available
- paper URL, PDF URL, DOI, and arXiv abs URL when available
- project and GitHub links are best-effort only; many papers do not have them, and missing values should not block completion
- source name, source URL, fetched timestamp

Use empty strings, empty arrays, or `null` for unavailable fields, following the existing normalized schema. Do not guess missing affiliations, first institutions, or links.
`arxiv_url` should point to the arXiv abstract page (`https://arxiv.org/abs/<id>`). Do not add a separate arXiv PDF field as a completion requirement.

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

## Efficient Continuation Workflow

This repository is often maintained by a fresh Codex session without prior chat history. Start from the current repository state, not from memory.

First inspect:

```bash
git status -sb
python scripts/build_status_summary.py
python scripts/audit_normalized.py --no-fail
python scripts/audit_validation_reports.py
python scripts/audit_latest_source_availability.py
python scripts/build_source_gap_report.py
```

Separate the work into two layers:

1. **Core paper-list harvesting**: official title/authors/paper URL/PDF/count coverage for every configured conference/year.
2. **Metadata enrichment**: abstracts, TLDRs, DOI, arXiv abs links, and best-effort project/GitHub links.

Core paper-list harvesting is the first priority. Per-paper metadata enrichment is valuable for downstream training-free filtering, but it should not block finishing official list coverage. Affiliations and first institution are not required at this time; keep values already harvested, but leave missing values empty/null rather than spending dedicated collection time on them.

Do not use web search to find papers one by one. Use web browsing only to inspect a few representative official pages and confirm page/API structure. Then implement or update local harvesters/enrichment scripts under `src/aicpl/sources/` or `scripts/`, and run them in batches.

For large per-paper enrichment jobs:

- Prefer bulk APIs, official JSON/XML, Crossref/OpenReview/PMLR metadata, or event pages when available.
- arXiv enrichment is a current goal: use bulk APIs or batched title-based lookup, write `arxiv_url` only for high-confidence unambiguous matches, and leave ambiguous or missing matches empty/null.
- If detail-page requests are required, use batching, retries, and resumability. Avoid one huge run that writes only after thousands of pages.
- On a fast server, prefer async HTTP or high-throughput chunked workers with connection reuse and a persistent cache of fetched pages.
- Track failures separately and retry only failed/missing records.
- Commit by meaningful source/year groups, not after every tiny sample.
- Do not run dedicated affiliation/first-institution enrichment jobs unless this requirement is explicitly re-enabled.

Validation should be proportional:

- When Paper Copilot has a matching JSON, run `scripts/validate_against_papercopilot.py` and expect broad count/title agreement, while allowing known Paper Copilot drift.
- When Paper Copilot has no baseline, randomly sample several records and verify against the official source page/API.
- Always run the audit scripts before committing a completed batch.

Good next-source order after inspecting current gaps:

1. Finish easy official bulk/detail enrichment channels already implemented, such as ACL Anthology and PMLR.
2. Fill current-year official channels first, such as CVPR/ICML/AAAI/ICRA/RSS/IJCAI/AI4X when available.
3. Then handle harder or slower sources: CVF older detail pages, ACM/Crossref, IEEE/Papercept, SIGGRAPH/SIGGRAPH Asia, KDD/WWW/ACM MM.
4. Record any blocked, incomplete, or fallback source in `config/source_issues.json` and surface it in reports.

## Quality Checklist

- Does the conference/year exist in Paper Copilot's index?
- Is the selected official source documented in `config/sources.json`?
- Does the raw snapshot include `fetched_at` and `source_url`?
- Does the normalized file parse as JSON?
- Does the validation report compare against Paper Copilot if available?
- If Paper Copilot has many more records, is the channel marked `needs_attention`?
- If a preferred official source is blocked or incomplete, is the fallback rationale recorded in `config/source_issues.json`?
