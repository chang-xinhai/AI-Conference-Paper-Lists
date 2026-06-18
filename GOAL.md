# Goal

请继续维护并完成 AI-Conference-Paper-Lists。先完整阅读 `AGENTS.md`，严格按 Efficient Continuation Workflow 执行，并从当前仓库状态开始，不依赖历史对话。

## Start

先运行：

```bash
git status -sb
python scripts/build_status_summary.py
python scripts/audit_normalized.py --no-fail
python scripts/audit_validation_reports.py
python scripts/audit_latest_source_availability.py
python scripts/build_source_gap_report.py
```

## Priorities

1. 先保证 core paper-list 完整：`title`、`authors`、`paper_url`、`pdf_url`、`count`、`source_url`、`fetched_at`、venue/year 等官方列表级数据。
2. 继续批量补 `abstract` 和 `arxiv_url`。
3. `arxiv_url` 只指向 arXiv abs 页面：`https://arxiv.org/abs/<id>`；不需要 arXiv PDF URL。
4. 已有或新匹配到 `arxiv_url` 时，可以顺手用 arXiv 元数据补缺失 `abstract`。
5. `affiliations` / `first_institute` 暂时不要求继续补；已有保留，缺失可空着。
6. `project_url` / `github_url` best-effort，不要求完整覆盖。

## arXiv Rules

- arXiv enrichment 必须使用 CLI 工具、本地批量脚本、MCP/CLI wrapper 或批量 API；不要一篇一篇人工 web search。
- 用 full title 批量查询，并用 title + authors + year 校验。
- 只写入高置信、无歧义匹配；标题冲突、候选歧义、作者明显不匹配时留空 / `null`。
- 使用缓存、限速、重试和 checkpoint；保存 raw/query cache，记录候选、匹配分数、拒绝原因或歧义状态。

## Validation

- Paper Copilot 只作为 baseline / cross-check / fallback，不作为唯一真相。
- 每完成一个有意义的 source/year batch，运行相关 validation/audit scripts。
- 使用 `scripts/rebuild_coverage.py` 同步 `data/reports/coverage.json`。
- 完成 batch 后 `git commit` 并 `git push`。

## Done When

- core paper-list 覆盖完整，audit 无 critical。
- 没有未处理的 available official source。
- `abstract` 和 `arxiv_url` 已通过官方/批量/CLI 工具尽可能补全。
- 歧义、无匹配、不可用的 arXiv 结果留空 / `null`，且可在 raw cache 或 report 中追踪。
