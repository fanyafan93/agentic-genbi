# Current Task

Updated: 2026-08-03 Asia/Shanghai

This page records the current verifiable state only. Historical process belongs in Git.

## Current State

- Branch: `feature/codex-item-stream-rendering`.
- Product mainline is a single Analysis Workspace.
- Codex owns `Thread / Turn / Item`, context, tool scheduling, streaming, interruption, retries, sandbox, and approval.
- GenBI owns users, tenants, data permissions, data sources, FineReport semantic cases, metrics and rules, Artifact versions, lineage, sharing, publishing, and governance.
- Analysis replies are rendered from real Codex Item events. The report pane only renders a real interactive-report Artifact or an empty state.

## Completed In This Round

- Deleted `ReadonlyDatabaseTools`, `ReportQueryService`, and the `resource_library` module, including their APIs, dependencies, and tests; retained knowledge records under business semantics.
- Deleted the `<interactive_report_draft>` prompt, parser, repair, context, and frontend event path.
- Deleted frontend report-query and local mock report/storage fallbacks.
- Removed synthetic report, SQL, chart, notebook, path, and skill Artifact events from the analysis service.
- An unconfigured analysis runner now fails explicitly instead of returning fabricated content.
- Preserved FineReport semantic cases, Artifact/version/lineage storage, Codex Thread/Turn/Item projection, and real Codex Artifact event mapping.

## Verification In This Round

- `python -m unittest discover backend\tests -v`: 60 tests passed.
- `npm.cmd test` in `frontend`: 52 tests passed.
- `npx.cmd tsc --noEmit --pretty false` in `frontend`: passed.
- `npm.cmd run build` in `frontend`: passed.
- Rebuilt and recreated backend/frontend containers; backend `/health` and frontend `/` returned HTTP 200.
- Browser interaction and a final live SSE submission were blocked by the environment approval layer, so live response content remains unverified in this round.

## Workspace State

- The worktree contains this deletion slice plus the earlier Codex Item streaming changes on the same feature branch.
- No unrelated user changes were reverted.

## Risks / Incomplete

- No report-generation tool is added in this slice. The report pane remains empty until a real registered Codex tool emits an interactive-report Artifact.
- Production data access, RLS, and complete Artifact governance remain incomplete.

## Next Steps

1. Register future GenBI business tools through Codex only when their contracts are ready.
2. Continue Artifact governance, sharing, publishing, permissions, and RLS.
