from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from backend.exploration.run_service import ExplorationRunEvent


DEFAULT_RUN_EVENT_STORE_PATH = Path(".resource-index/run-events.jsonl")


class RunEventStore:
    def __init__(self, path: Path = DEFAULT_RUN_EVENT_STORE_PATH) -> None:
        self.path = path

    def save_events(self, *, run_id: str, events: list["ExplorationRunEvent"]) -> int:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        existing = [item for item in self._read_raw() if item.get("run_id") != run_id]
        records = [*existing, *[asdict(event) for event in events]]
        with self.path.open("w", encoding="utf-8", newline="\n") as file:
            for record in records:
                file.write(json.dumps(record, ensure_ascii=False, default=str))
                file.write("\n")
        return len(events)

    def list_events(self, run_id: str) -> list["ExplorationRunEvent"]:
        from backend.exploration.run_service import ExplorationRunEvent

        return [
            ExplorationRunEvent(
                type=str(record["type"]),
                run_id=str(record["run_id"]),
                payload=dict(record.get("payload") or {}),
                created_at=str(record["created_at"]),
            )
            for record in self._read_raw()
            if record.get("run_id") == run_id
        ]

    def delete_events(self, run_id: str) -> int:
        records = self._read_raw()
        remaining = [item for item in records if item.get("run_id") != run_id]
        deleted_count = len(records) - len(remaining)
        if deleted_count == 0:
            return 0
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8", newline="\n") as file:
            for record in remaining:
                file.write(json.dumps(record, ensure_ascii=False, default=str))
                file.write("\n")
        return deleted_count

    def clear_events(self) -> int:
        count = len(self._read_raw())
        if self.path.exists():
            self.path.unlink()
        return count

    def _read_raw(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        records = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                records.append(json.loads(line))
        return records


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Local exploration run event store.")
    parser.add_argument("--path", default=str(DEFAULT_RUN_EVENT_STORE_PATH))
    subparsers = parser.add_subparsers(dest="command", required=True)

    get_cmd = subparsers.add_parser("get", help="Get persisted events for one run.")
    get_cmd.add_argument("run_id")

    subparsers.add_parser("clear", help="Delete all persisted run events.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    store = RunEventStore(Path(args.path))
    if args.command == "get":
        print(json.dumps([asdict(item) for item in store.list_events(args.run_id)], ensure_ascii=False, indent=2))
    elif args.command == "clear":
        print(json.dumps({"deleted_count": store.clear_events()}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
