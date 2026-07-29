from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .inspector import DEFAULT_MAX_BYTES, _decode_text, _safe_join


DEFAULT_INDEX_PATH = Path(".resource-index/resources.json")
DEFAULT_SUMMARY_PATH = Path(".resource-index/resource-summaries.json")
DEFAULT_EXCERPT_MAX_BYTES = 64 * 1024
DEFAULT_EXCERPT_MAX_LINES = 240


@dataclass(frozen=True)
class SearchResult:
    resource_id: str
    name: str
    type: str
    relative_path: str
    score: int
    matched_fields: list[str]
    highlights: list[str]


@dataclass(frozen=True)
class ResourceDetail:
    resource_id: str
    name: str
    type: str
    relative_path: str
    size_bytes: int
    modified_at: str
    sha256: str
    status: str
    truncated_summary: bool
    signals: dict[str, Any]
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ResourceExcerpt:
    resource_id: str
    relative_path: str
    section: str
    start_line: int
    end_line: int
    truncated: bool
    encoding: str | None
    text: str


class ResourceLibrary:
    def __init__(
        self,
        *,
        index_path: Path = DEFAULT_INDEX_PATH,
        summary_path: Path = DEFAULT_SUMMARY_PATH,
    ) -> None:
        self.index_path = index_path
        self.summary_path = summary_path
        self.index = json.loads(index_path.read_text(encoding="utf-8"))
        self.summary_index = json.loads(summary_path.read_text(encoding="utf-8"))
        self.root = _resolve_resource_root(Path(self.index["root"]), index_path=index_path)
        self.resources_by_id = {item["id"]: item for item in self.index["resources"]}
        self.summaries_by_id = {item["id"]: item for item in self.summary_index["summaries"]}

    def search_resources(self, query: str, *, resource_type: str | None = None, limit: int = 10) -> list[SearchResult]:
        terms = _tokenize(query)
        if not terms:
            return []

        results = []
        for resource in self.index["resources"]:
            if resource_type and resource["type"] != resource_type:
                continue
            summary = self.summaries_by_id.get(resource["id"], {})
            score, matched_fields, highlights = _score_resource(resource, summary, terms)
            if score > 0:
                results.append(
                    SearchResult(
                        resource_id=resource["id"],
                        name=resource["name"],
                        type=resource["type"],
                        relative_path=resource["relative_path"],
                        score=score,
                        matched_fields=matched_fields,
                        highlights=highlights[:8],
                    )
                )

        results.sort(key=lambda result: (-result.score, result.relative_path.lower()))
        return results[:limit]

    def inspect_resource(self, resource_id: str) -> ResourceDetail:
        resource = self._get_resource(resource_id)
        summary = self.summaries_by_id.get(resource_id)
        if not summary:
            raise KeyError(f"Resource summary not found: {resource_id}")
        return ResourceDetail(
            resource_id=resource_id,
            name=resource["name"],
            type=resource["type"],
            relative_path=resource["relative_path"],
            size_bytes=resource["size_bytes"],
            modified_at=resource["modified_at"],
            sha256=resource["sha256"],
            status=summary["status"],
            truncated_summary=summary["truncated"],
            signals=summary.get("signals", {}),
            warnings=summary.get("warnings", []),
        )

    def read_resource_excerpt(
        self,
        resource_id: str,
        *,
        section: str = "head",
        query: str | None = None,
        max_bytes: int = DEFAULT_EXCERPT_MAX_BYTES,
        max_lines: int = DEFAULT_EXCERPT_MAX_LINES,
    ) -> ResourceExcerpt:
        resource = self._get_resource(resource_id)
        path = _safe_join(self.root, resource["relative_path"])
        raw = path.read_bytes()[:max_bytes]
        raw_truncated = path.stat().st_size > len(raw)
        text, encoding = _decode_text(raw)
        if text is None:
            return ResourceExcerpt(
                resource_id=resource_id,
                relative_path=resource["relative_path"],
                section=section,
                start_line=0,
                end_line=0,
                truncated=raw_truncated,
                encoding=None,
                text="",
            )

        lines = text.splitlines()
        start, end = _select_line_window(lines, section=section, query=query, max_lines=max_lines)
        selected = lines[start:end]
        line_truncated = end < len(lines)
        return ResourceExcerpt(
            resource_id=resource_id,
            relative_path=resource["relative_path"],
            section=section,
            start_line=start + 1 if selected else 0,
            end_line=end if selected else 0,
            truncated=raw_truncated or line_truncated,
            encoding=encoding,
            text="\n".join(selected),
        )

    def _get_resource(self, resource_id: str) -> dict[str, Any]:
        resource = self.resources_by_id.get(resource_id)
        if not resource:
            raise KeyError(f"Resource not found: {resource_id}")
        return resource


def _score_resource(resource: dict[str, Any], summary: dict[str, Any], terms: list[str]) -> tuple[int, list[str], list[str]]:
    weighted_fields = _weighted_search_fields(resource, summary)
    score = 0
    matched_fields: list[str] = []
    highlights: list[str] = []
    for field_name, weight, values in weighted_fields:
        haystack = " ".join(str(value) for value in values if value).lower()
        if not haystack:
            continue
        field_hits = [term for term in terms if term in haystack]
        if not field_hits:
            continue
        score += weight * len(field_hits)
        matched_fields.append(field_name)
        highlights.extend(_highlight_values(values, field_hits))
    return score, _dedupe(matched_fields), _dedupe(highlights)


def _weighted_search_fields(resource: dict[str, Any], summary: dict[str, Any]) -> list[tuple[str, int, list[Any]]]:
    signals = summary.get("signals", {})
    fields: list[tuple[str, int, list[Any]]] = [
        ("name", 10, [resource.get("name")]),
        ("relative_path", 8, [resource.get("relative_path")]),
        ("type", 4, [resource.get("type"), resource.get("extension")]),
    ]
    fields.append(("xml.named_nodes", 5, _stringify_nodes(signals.get("named_nodes", []))))
    fields.append(("sql.table_refs", 7, signals.get("table_refs", [])))
    fields.append(("sql.read_table_refs", 7, signals.get("read_table_refs", [])))
    fields.append(("sql.write_table_refs", 8, signals.get("write_table_refs", [])))
    fields.append(("sql.field_candidates", 6, signals.get("field_candidates", [])))
    fields.append(("finereport.dataset_candidates", 7, signals.get("finereport", {}).get("dataset_candidates", [])))
    fields.append(("finereport.parameter_candidates", 6, signals.get("finereport", {}).get("parameter_candidates", [])))
    fields.append(("finereport.table_refs", 7, signals.get("finereport", {}).get("lineage_table_refs", [])))
    fields.append(("finereport.read_table_refs", 7, signals.get("finereport", {}).get("read_table_refs", [])))
    fields.append(("finereport.write_table_refs", 8, signals.get("finereport", {}).get("write_table_refs", [])))
    fields.append(("finereport.field_candidates", 6, signals.get("finereport", {}).get("field_candidates", [])))
    fields.append(("finereport.formula_candidates", 5, signals.get("finereport", {}).get("formula_candidates", [])))
    fields.append(("hop.action_or_transform_names", 6, signals.get("hop", {}).get("action_or_transform_names", [])))
    fields.append(("hop.table_refs", 7, signals.get("hop", {}).get("lineage_table_refs", [])))
    fields.append(("hop.read_table_refs", 7, signals.get("hop", {}).get("read_table_refs", [])))
    fields.append(("hop.write_table_refs", 8, signals.get("hop", {}).get("write_table_refs", [])))
    fields.append(("hop.field_candidates", 6, signals.get("hop", {}).get("field_candidates", [])))
    fields.append(("dictionary.field_candidates", 6, signals.get("dictionary", {}).get("field_candidates", [])))
    return fields


def _stringify_nodes(nodes: list[dict[str, Any]]) -> list[str]:
    return [f"{node.get('tag', '')} {node.get('attribute', '')} {node.get('value', '')}" for node in nodes]


def _highlight_values(values: list[Any], terms: list[str]) -> list[str]:
    highlights = []
    for value in values:
        text = str(value)
        lower = text.lower()
        if any(term in lower for term in terms):
            highlights.append(text[:160])
    return highlights


def _tokenize(query: str) -> list[str]:
    normalized = query.strip().lower()
    if not normalized:
        return []
    tokens = re.findall(r"[\w\u4e00-\u9fff$.-]+", normalized)
    if normalized not in tokens:
        tokens.append(normalized)
    return _dedupe([token for token in tokens if token])


def _dedupe(values: list[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _resolve_resource_root(indexed_root: Path, *, index_path: Path) -> Path:
    candidates = [indexed_root]
    env_root = os.getenv("GENBI_RESOURCE_LIBRARY_ROOT")
    if env_root:
        candidates.append(Path(env_root))
    candidates.extend(
        [
            Path("资源库"),
            index_path.resolve().parent.parent / "资源库",
            Path(__file__).resolve().parents[2] / "资源库",
        ]
    )
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved.exists() and resolved.is_dir():
            return resolved
    return indexed_root.resolve()


def _select_line_window(lines: list[str], *, section: str, query: str | None, max_lines: int) -> tuple[int, int]:
    if not lines:
        return 0, 0
    if section == "tail":
        start = max(0, len(lines) - max_lines)
        return start, len(lines)
    if section == "match" and query:
        terms = _tokenize(query)
        for index, line in enumerate(lines):
            lower = line.lower()
            if any(term in lower for term in terms):
                half = max_lines // 2
                start = max(0, index - half)
                end = min(len(lines), start + max_lines)
                return start, end
    return 0, min(len(lines), max_lines)


def _to_json(value: Any) -> str:
    if hasattr(value, "__dataclass_fields__"):
        value = asdict(value)
    elif isinstance(value, list):
        value = [asdict(item) if hasattr(item, "__dataclass_fields__") else item for item in value]
    return json.dumps(value, ensure_ascii=False, indent=2)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Search and inspect the local resource library summaries.")
    parser.add_argument("--index", default=str(DEFAULT_INDEX_PATH), help="Input resource index JSON.")
    parser.add_argument("--summaries", default=str(DEFAULT_SUMMARY_PATH), help="Input resource summary JSON.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    search = subparsers.add_parser("search", help="Search indexed resources.")
    search.add_argument("query")
    search.add_argument("--type", dest="resource_type", default=None)
    search.add_argument("--limit", type=int, default=10)

    inspect = subparsers.add_parser("inspect", help="Return one resource summary.")
    inspect.add_argument("resource_id")

    excerpt = subparsers.add_parser("excerpt", help="Read a bounded resource excerpt.")
    excerpt.add_argument("resource_id")
    excerpt.add_argument("--section", choices=["head", "tail", "match"], default="head")
    excerpt.add_argument("--query", default=None)
    excerpt.add_argument("--max-bytes", type=int, default=DEFAULT_EXCERPT_MAX_BYTES)
    excerpt.add_argument("--max-lines", type=int, default=DEFAULT_EXCERPT_MAX_LINES)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    library = ResourceLibrary(index_path=Path(args.index), summary_path=Path(args.summaries))
    if args.command == "search":
        print(_to_json(library.search_resources(args.query, resource_type=args.resource_type, limit=args.limit)))
    elif args.command == "inspect":
        print(_to_json(library.inspect_resource(args.resource_id)))
    elif args.command == "excerpt":
        print(
            _to_json(
                library.read_resource_excerpt(
                    args.resource_id,
                    section=args.section,
                    query=args.query,
                    max_bytes=args.max_bytes,
                    max_lines=args.max_lines,
                )
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
