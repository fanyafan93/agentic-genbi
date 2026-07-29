from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from backend.config import load_project_env
from backend.exploration.run_event_store import DEFAULT_RUN_EVENT_STORE_PATH, RunEventStore
from backend.exploration.run_trace_store import DEFAULT_RUN_TRACE_STORE_PATH, RunCost, RunTrace, RunTraceStore, TokenUsage
from backend.persistence.postgres_stores import build_postgres_stores
from backend.resource_library.knowledge_store import DEFAULT_KNOWLEDGE_STORE_PATH, KnowledgeRecord, KnowledgeStore


def migrate(
    *,
    trace_path: Path = DEFAULT_RUN_TRACE_STORE_PATH,
    event_path: Path = DEFAULT_RUN_EVENT_STORE_PATH,
    knowledge_path: Path = DEFAULT_KNOWLEDGE_STORE_PATH,
) -> dict[str, int]:
    load_project_env()
    trace_store, event_store, knowledge_store = build_postgres_stores()

    trace_count = 0
    for trace in _read_traces(trace_path):
        trace_store.upsert_trace(trace)
        trace_count += 1

    event_count = 0
    events_by_run: dict[str, list[Any]] = {}
    for event in RunEventStore(event_path)._read_raw():
        run_id = str(event.get("run_id") or "")
        if run_id:
            events_by_run.setdefault(run_id, []).append(event)
    for run_id, events in events_by_run.items():
        event_count += event_store.upsert_events(run_id=run_id, events=events)

    knowledge_count = 0
    for record in KnowledgeStore(knowledge_path)._read_all():
        knowledge_store.upsert_knowledge(record)
        knowledge_count += 1

    return {
        "run_traces": trace_count,
        "run_events": event_count,
        "knowledge_records": knowledge_count,
    }


def _read_traces(path: Path) -> list[RunTrace]:
    records = []
    for trace in RunTraceStore(path)._read_all():
        records.append(trace)
    return records


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Migrate local JSONL exploration stores to Postgres.")
    parser.add_argument("--trace-path", type=Path, default=DEFAULT_RUN_TRACE_STORE_PATH)
    parser.add_argument("--event-path", type=Path, default=DEFAULT_RUN_EVENT_STORE_PATH)
    parser.add_argument("--knowledge-path", type=Path, default=DEFAULT_KNOWLEDGE_STORE_PATH)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    result = migrate(trace_path=args.trace_path, event_path=args.event_path, knowledge_path=args.knowledge_path)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
