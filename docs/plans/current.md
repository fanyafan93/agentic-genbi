# Current Task

Updated: 2026-08-02 Asia/Shanghai

This page records the current verifiable state only. Historical process belongs in Git.

## Current State

- Branch: `Agentic-GenBI`.
- Product mainline is a single Analysis Workspace.
- The main model is Codex `Thread / Turn / Item`.
- Analysis Task is a GenBI business record with `codexThreadId`; it is not an execution layer.
- GenBI Artifact lineage uses `assetId` as `artifactId`, a separate `artifactVersionId`, and optional Codex Thread / Turn / Item ids.

## Completed In This Round

- Added `backend/analysis/turn_service.py` with `AnalysisTurnService` / `AnalysisTurnRequest` as the analysis service entry.
- Added `backend/harness/events.py` with `AgentEvent`.
- Renamed the FastAPI entrypoint to `backend.api.analysis_api`.
- Switched analysis turn creation and SSE streaming to Thread / Turn endpoints.
- Updated `ThreadStore` file persistence to save threads, turns, items, and Codex item projections directly.
- Removed the old investigation frontend module and its tests.
- Removed the old execution backend module, legacy execution APIs, legacy stores, migration script, and static demo pages.
- Removed the old local event compatibility names from backend services, SDK runner mapping, frontend event mapping, and tests.
- Runtime events now use Codex `turn/*` and `item/*` plus GenBI `genbi/artifact/*`.
- Removed source fields from analysis assets and interactive reports that are not part of Codex Thread / Turn / Item lineage.
- Removed the knowledge-base source category that came from the deleted analysis path.
- Updated product and architecture docs to describe the current boundary only.

## Verified

- `python -m unittest discover backend\tests -v`: 91 tests passed.
- `npm.cmd test` in `frontend`: 50 tests passed.
- `npm.cmd run build` in `frontend`: passed.
- `docker compose config`: passed.
- `docker compose up -d --build`: rebuilt and restarted backend and frontend.
- `GET http://127.0.0.1:8000/health`: 200 with `{"status":"ok"}`.
- `GET http://127.0.0.1:3000/`: 200.
- Legacy object/path scan across backend, frontend, tests, docs, compose, and `.env`: no matches for the removed domain terms.
- Legacy event scan across backend and frontend: no matches for removed local compatibility event names.

## Current Limitations

- Codex tool / MCP / Skill integration is still incomplete.
- Complete business semantic persistence is still incomplete.
- Complete Artifact governance, sharing, publishing, team permissions, RLS, and production data source governance are still incomplete.

## Next Steps

1. Replace remaining mock-first semantic/tool behavior with real Codex tool items where the business tool contracts are ready.
2. Complete business semantic persistence.
3. Complete Artifact governance, sharing, publishing, team permissions, RLS, and production data source governance.
