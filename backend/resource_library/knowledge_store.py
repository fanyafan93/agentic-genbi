from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4


DEFAULT_KNOWLEDGE_STORE_PATH = Path(".resource-index/knowledge.jsonl")


@dataclass(frozen=True)
class KnowledgeRecord:
    id: str
    title: str
    question: str
    conclusion: str
    scope: str
    verification: str
    evidence_refs: list[str]
    run_id: str | None
    created_at: str
    metadata: dict[str, Any] = field(default_factory=dict)


class KnowledgeStore:
    def __init__(self, path: Path = DEFAULT_KNOWLEDGE_STORE_PATH) -> None:
        self.path = path

    def save_verified_knowledge(
        self,
        *,
        title: str,
        question: str,
        conclusion: str,
        scope: str,
        verification: str,
        evidence_refs: list[str],
        run_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> KnowledgeRecord:
        _require_text("title", title)
        _require_text("question", question)
        _require_text("conclusion", conclusion)
        _require_text("scope", scope)
        _require_text("verification", verification)
        if not evidence_refs:
            raise ValueError("save_verified_knowledge requires at least one evidence reference.")

        record = KnowledgeRecord(
            id=f"kn_{uuid4().hex[:12]}",
            title=title.strip(),
            question=question.strip(),
            conclusion=conclusion.strip(),
            scope=scope.strip(),
            verification=verification.strip(),
            evidence_refs=[ref.strip() for ref in evidence_refs if ref.strip()],
            run_id=run_id.strip() if run_id else None,
            created_at=datetime.now(UTC).isoformat(),
            metadata=metadata or {},
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8", newline="\n") as file:
            file.write(json.dumps(asdict(record), ensure_ascii=False))
            file.write("\n")
        return record

    def list_knowledge(self, *, limit: int = 50) -> list[KnowledgeRecord]:
        records = self._read_all()
        records.sort(key=lambda item: item.created_at, reverse=True)
        return records[:limit]

    def search_knowledge(
        self,
        *,
        query: str = "",
        item_type: str | None = None,
        status: str | None = None,
        tag: str | None = None,
        owner: str | None = None,
        limit: int = 50,
    ) -> list[KnowledgeRecord]:
        normalized_query = query.strip().lower()
        normalized_tag = (tag or "").strip().lower()
        records = self._read_all()
        matched = []
        for record in records:
            metadata = record.metadata or {}
            if item_type and metadata.get("type") != item_type:
                continue
            if status and metadata.get("status") != status:
                continue
            if owner and metadata.get("owner") != owner:
                continue
            tags = [str(item).lower() for item in metadata.get("tags", []) if str(item).strip()]
            if normalized_tag and normalized_tag not in tags:
                continue
            haystack = " ".join(
                [
                    record.title,
                    record.question,
                    record.conclusion,
                    record.scope,
                    record.verification,
                    json.dumps(metadata, ensure_ascii=False, default=str),
                ]
            ).lower()
            if normalized_query and normalized_query not in haystack:
                continue
            matched.append(record)
        matched.sort(key=lambda item: item.created_at, reverse=True)
        return matched[:limit]

    def update_knowledge(
        self,
        record_id: str,
        *,
        title: str | None = None,
        question: str | None = None,
        conclusion: str | None = None,
        scope: str | None = None,
        verification: str | None = None,
        evidence_refs: list[str] | None = None,
        run_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> KnowledgeRecord | None:
        records = self._read_all()
        updated: KnowledgeRecord | None = None
        next_records = []
        for record in records:
            if record.id != record_id:
                next_records.append(record)
                continue
            merged_metadata = dict(record.metadata or {})
            if metadata:
                merged_metadata.update(metadata)
            updated = replace(
                record,
                title=title.strip() if title is not None else record.title,
                question=question.strip() if question is not None else record.question,
                conclusion=conclusion.strip() if conclusion is not None else record.conclusion,
                scope=scope.strip() if scope is not None else record.scope,
                verification=verification.strip() if verification is not None else record.verification,
                evidence_refs=[ref.strip() for ref in evidence_refs if ref.strip()] if evidence_refs is not None else record.evidence_refs,
                run_id=run_id.strip() if run_id else record.run_id,
                metadata=merged_metadata,
            )
            next_records.append(updated)
        if not updated:
            return None
        self._write_all(next_records)
        return updated

    def list_tags(self) -> list[dict[str, Any]]:
        counts: dict[str, int] = {}
        groups: dict[str, str] = {}
        for record in self._read_all():
            metadata = record.metadata or {}
            tag_groups = metadata.get("tag_groups", {})
            for tag in metadata.get("tags", []) or []:
                name = str(tag).strip()
                if not name:
                    continue
                counts[name] = counts.get(name, 0) + 1
                if isinstance(tag_groups, dict) and name in tag_groups:
                    groups[name] = str(tag_groups[name])
        return [
            {"name": name, "count": count, "group": groups.get(name, "未分组")}
            for name, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
        ]

    def delete_knowledge(self, record_id: str) -> bool:
        records = self._read_all()
        remaining = [record for record in records if record.id != record_id]
        if len(remaining) == len(records):
            return False
        self._write_all(remaining)
        return True

    def clear_knowledge(self) -> int:
        count = len(self._read_all())
        if self.path.exists():
            self.path.unlink()
        return count

    def _read_all(self) -> list[KnowledgeRecord]:
        if not self.path.exists():
            return []
        records = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                records.append(KnowledgeRecord(**json.loads(line)))
        return records

    def _write_all(self, records: list[KnowledgeRecord]) -> None:
        if not records:
            if self.path.exists():
                self.path.unlink()
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8", newline="\n") as file:
            for record in records:
                file.write(json.dumps(asdict(record), ensure_ascii=False))
                file.write("\n")


def _require_text(field: str, value: str) -> None:
    if not value.strip():
        raise ValueError(f"{field} is required.")


def _to_json(value: Any) -> str:
    if hasattr(value, "__dataclass_fields__"):
        value = asdict(value)
    elif isinstance(value, list):
        value = [asdict(item) if hasattr(item, "__dataclass_fields__") else item for item in value]
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Local verified knowledge store.")
    parser.add_argument("--path", default=str(DEFAULT_KNOWLEDGE_STORE_PATH))
    subparsers = parser.add_subparsers(dest="command", required=True)

    save = subparsers.add_parser("save", help="Save one verified knowledge record.")
    save.add_argument("--title", required=True)
    save.add_argument("--question", required=True)
    save.add_argument("--conclusion", required=True)
    save.add_argument("--scope", required=True)
    save.add_argument("--verification", required=True)
    save.add_argument("--evidence", action="append", required=True)
    save.add_argument("--run-id", default=None)

    list_cmd = subparsers.add_parser("list", help="List recent knowledge records.")
    list_cmd.add_argument("--limit", type=int, default=50)

    delete = subparsers.add_parser("delete", help="Delete one knowledge record.")
    delete.add_argument("record_id")

    subparsers.add_parser("clear", help="Delete all knowledge records.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    store = KnowledgeStore(Path(args.path))
    if args.command == "save":
        print(
            _to_json(
                store.save_verified_knowledge(
                    title=args.title,
                    question=args.question,
                    conclusion=args.conclusion,
                    scope=args.scope,
                    verification=args.verification,
                    evidence_refs=args.evidence,
                    run_id=args.run_id,
                )
            )
        )
    elif args.command == "list":
        print(_to_json(store.list_knowledge(limit=args.limit)))
    elif args.command == "delete":
        print(_to_json({"deleted": store.delete_knowledge(args.record_id)}))
    elif args.command == "clear":
        print(_to_json({"deleted_count": store.clear_knowledge()}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
