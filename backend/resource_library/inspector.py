from __future__ import annotations

import argparse
import json
import re
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SUMMARY_SCHEMA_VERSION = "resource-summary.v1"
DEFAULT_MAX_BYTES = 512 * 1024
MAX_ITEMS = 40


@dataclass(frozen=True)
class ResourceSummary:
    id: str
    type: str
    relative_path: str
    status: str
    bytes_read: int
    truncated: bool
    signals: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def inspect_resource(root: Path, resource: dict[str, Any], *, max_bytes: int = DEFAULT_MAX_BYTES) -> ResourceSummary:
    root = root.resolve()
    relative_path = str(resource["relative_path"])
    path = _safe_join(root, relative_path)
    if not path.exists() or not path.is_file():
        return _summary(resource, status="missing", warnings=["file_not_found"])

    raw = path.read_bytes()[:max_bytes]
    truncated = path.stat().st_size > len(raw)
    text, encoding = _decode_text(raw)
    if text is None:
        return _summary(
            resource,
            status="binary_or_unsupported",
            bytes_read=len(raw),
            truncated=truncated,
            warnings=["could_not_decode_as_text"],
        )

    resource_type = str(resource["type"])
    if resource_type == "sql":
        signals = inspect_sql_text(text)
    elif resource_type in {"xml_dictionary", "finereport_cpt", "finereport_form", "apache_hop_workflow", "apache_hop_pipeline"}:
        signals = inspect_xml_like_text(text, resource_type)
    elif resource_type in {"markdown", "text", "json"}:
        signals = inspect_document_text(text, resource_type)
    else:
        signals = {"kind": resource_type}

    signals["encoding"] = encoding
    return _summary(
        resource,
        status="ok",
        bytes_read=len(raw),
        truncated=truncated,
        signals=signals,
    )


def inspect_sql_text(text: str) -> dict[str, Any]:
    compact = _strip_sql_comments(text)
    table_refs = sorted(set(_find_sql_table_refs(compact)))
    table_refs_by_role = _find_sql_table_refs_by_role(compact)
    field_candidates = _extract_sql_field_candidates(compact)
    return {
        "kind": "sql",
        "statement_count": _count_sql_statements(compact),
        "table_refs": table_refs[:MAX_ITEMS],
        "table_ref_count": len(table_refs),
        "read_table_refs": table_refs_by_role["read"][:MAX_ITEMS],
        "write_table_refs": table_refs_by_role["write"][:MAX_ITEMS],
        "field_candidates": field_candidates[:MAX_ITEMS],
        "has_select": bool(re.search(r"\bselect\b", compact, re.IGNORECASE)),
        "has_insert_or_write": bool(re.search(r"\b(insert|update|delete|merge|drop|alter|truncate|create)\b", compact, re.IGNORECASE)),
    }


def inspect_xml_like_text(text: str, resource_type: str) -> dict[str, Any]:
    tag_counts = _count_xml_tags(text)
    named_nodes = _extract_named_xml_nodes(text)
    sql_like_count = len(re.findall(r"\bselect\b.+?\bfrom\b", text, re.IGNORECASE | re.DOTALL))
    signals: dict[str, Any] = {
        "kind": resource_type,
        "root_tag": _safe_xml_root_tag(text),
        "tag_counts": dict(tag_counts.most_common(MAX_ITEMS)),
        "named_nodes": named_nodes[:MAX_ITEMS],
        "sql_like_count": sql_like_count,
    }

    if resource_type in {"apache_hop_workflow", "apache_hop_pipeline"}:
        table_refs_by_role = _find_sql_table_refs_by_role(text)
        signals["hop"] = {
            "action_or_transform_names": _extract_by_tag_names(text, {"name", "type"})[:MAX_ITEMS],
            "lineage_table_refs": sorted(set(_find_sql_table_refs(text)))[:MAX_ITEMS],
            "read_table_refs": table_refs_by_role["read"][:MAX_ITEMS],
            "write_table_refs": table_refs_by_role["write"][:MAX_ITEMS],
            "field_candidates": _extract_sql_field_candidates(text)[:MAX_ITEMS],
        }
    if resource_type in {"finereport_cpt", "finereport_form"}:
        table_refs_by_role = _find_sql_table_refs_by_role(text)
        signals["finereport"] = {
            "dataset_candidates": _extract_dataset_candidates(text)[:MAX_ITEMS],
            "parameter_candidates": _extract_parameter_candidates(text)[:MAX_ITEMS],
            "lineage_table_refs": sorted(set(_find_sql_table_refs(text)))[:MAX_ITEMS],
            "read_table_refs": table_refs_by_role["read"][:MAX_ITEMS],
            "write_table_refs": table_refs_by_role["write"][:MAX_ITEMS],
            "field_candidates": _extract_finereport_field_candidates(text)[:MAX_ITEMS],
            "formula_candidates": _extract_formula_candidates(text)[:MAX_ITEMS],
        }
    if resource_type == "xml_dictionary":
        signals["dictionary"] = {
            "field_candidates": _extract_dictionary_field_candidates(text)[:MAX_ITEMS],
        }
    return signals


def inspect_document_text(text: str, resource_type: str) -> dict[str, Any]:
    table_refs = sorted(set(_find_sql_table_refs(text)))
    return {
        "kind": resource_type,
        "line_count": text.count("\n") + 1 if text else 0,
        "sql_like_count": len(re.findall(r"\bselect\b.+?\bfrom\b", text, re.IGNORECASE | re.DOTALL)),
        "table_refs": table_refs[:MAX_ITEMS],
        "table_ref_count": len(table_refs),
    }


def inspect_index(index_path: Path, output_path: Path, *, max_bytes: int = DEFAULT_MAX_BYTES, limit: int | None = None) -> dict[str, Any]:
    index = json.loads(index_path.read_text(encoding="utf-8"))
    root = Path(index["root"])
    resources = index["resources"][:limit]
    summaries = [inspect_resource(root, resource, max_bytes=max_bytes) for resource in resources]
    payload = {
        "schema_version": SUMMARY_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_index": str(index_path),
        "root": str(root),
        "summary_count": len(summaries),
        "counts_by_status": dict(Counter(summary.status for summary in summaries)),
        "summaries": [asdict(summary) for summary in summaries],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def _summary(
    resource: dict[str, Any],
    *,
    status: str,
    bytes_read: int = 0,
    truncated: bool = False,
    signals: dict[str, Any] | None = None,
    warnings: list[str] | None = None,
) -> ResourceSummary:
    return ResourceSummary(
        id=str(resource["id"]),
        type=str(resource["type"]),
        relative_path=str(resource["relative_path"]),
        status=status,
        bytes_read=bytes_read,
        truncated=truncated,
        signals=signals or {},
        warnings=warnings or [],
    )


def _safe_join(root: Path, relative_path: str) -> Path:
    candidate = (root / relative_path).resolve()
    if root != candidate and root not in candidate.parents:
        raise ValueError(f"Resource path escapes root: {relative_path}")
    return candidate


def _decode_text(raw: bytes) -> tuple[str | None, str | None]:
    if b"\x00" in raw[:4096]:
        return None, None
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return raw.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="ignore"), "utf-8-ignore"


def _strip_sql_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.DOTALL)
    return re.sub(r"--[^\n\r]*", " ", text)


def _find_sql_table_refs(text: str) -> list[str]:
    pattern = re.compile(
        r"\b(?:from|join|into|update)\s+([`\"\[]?[A-Za-z_][\w$]*(?:[`\"\]]?\s*\.\s*[`\"\[]?[A-Za-z_][\w$]*){0,2})",
        re.IGNORECASE,
    )
    cte_names = _extract_cte_names(text)
    refs = []
    for match in pattern.finditer(text):
        ref = re.sub(r"[`\"\[\]\s]", "", match.group(1))
        if _looks_like_physical_table_ref(ref, cte_names=cte_names):
            refs.append(ref)
    return refs


def _find_sql_table_refs_by_role(text: str) -> dict[str, list[str]]:
    pattern = re.compile(
        r"\b(from|join|into|update)\s+([`\"\[]?[A-Za-z_][\w$]*(?:[`\"\]]?\s*\.\s*[`\"\[]?[A-Za-z_][\w$]*){0,2})",
        re.IGNORECASE,
    )
    grouped = {"read": [], "write": []}
    seen = {"read": set(), "write": set()}
    cte_names = _extract_cte_names(text)
    for clause, raw_ref in pattern.findall(text):
        ref = re.sub(r"[`\"\[\]\s]", "", raw_ref)
        if not _looks_like_physical_table_ref(ref, cte_names=cte_names):
            continue
        role = "write" if clause.lower() in {"into", "update"} else "read"
        if ref not in seen[role]:
            seen[role].add(ref)
            grouped[role].append(ref)
    return grouped


def _extract_cte_names(text: str) -> set[str]:
    names = set()
    for match in re.finditer(r"(?:\bwith|,)\s+([`\"\[]?[A-Za-z_][\w$]*[`\"\]]?)\s+as\s*\(", text, re.IGNORECASE):
        names.add(re.sub(r"[`\"\[\]]", "", match.group(1)).lower())
    return names


def _looks_like_physical_table_ref(ref: str, *, cte_names: set[str] | None = None) -> bool:
    lowered = ref.lower()
    if lowered in {"select", "values", "dual"}:
        return False
    if cte_names and lowered in cte_names:
        return False
    if len(ref) <= 2 and "." not in ref:
        return False
    return True


def _extract_sql_field_candidates(text: str) -> list[str]:
    values = []
    seen = set()
    for match in re.finditer(r"\bselect\s+(.*?)\bfrom\b", text, re.IGNORECASE | re.DOTALL):
        select_part = match.group(1)
        for expression in _split_sql_select_list(select_part):
            field = _normalize_sql_field_expression(expression)
            if field and field not in seen:
                seen.add(field)
                values.append(field)
            if len(values) >= MAX_ITEMS:
                return values
    return values


def _split_sql_select_list(select_part: str) -> list[str]:
    items = []
    current = []
    depth = 0
    quote: str | None = None
    for char in select_part:
        if quote:
            current.append(char)
            if char == quote:
                quote = None
            continue
        if char in {"'", '"', "`"}:
            quote = char
            current.append(char)
            continue
        if char == "(":
            depth += 1
        elif char == ")" and depth > 0:
            depth -= 1
        if char == "," and depth == 0:
            items.append("".join(current).strip())
            current = []
        else:
            current.append(char)
    if current:
        items.append("".join(current).strip())
    return items


def _normalize_sql_field_expression(expression: str) -> str | None:
    expression = re.sub(r"\s+", " ", expression.strip())
    if not expression or expression == "*":
        return None
    alias_match = re.search(r"\bas\s+([`\"\[]?[A-Za-z_][\w$]*[`\"\]]?)$", expression, re.IGNORECASE)
    if alias_match:
        return re.sub(r"[`\"\[\]]", "", alias_match.group(1))
    trailing_alias = re.search(r"\s+([`\"\[]?[A-Za-z_][\w$]*[`\"\]]?)$", expression)
    if trailing_alias and not expression.lower().endswith((" end", " then", " else")):
        prefix = expression[: trailing_alias.start()].strip()
        if prefix and not re.fullmatch(r"[`\"\[]?[A-Za-z_][\w$]*(?:[`\"\]]?\.[`\"\[]?[A-Za-z_][\w$]*)?", prefix):
            return re.sub(r"[`\"\[\]]", "", trailing_alias.group(1))
    column_match = re.search(r"([`\"\[]?[A-Za-z_][\w$]*[`\"\]]?\.)?([`\"\[]?[A-Za-z_][\w$]*[`\"\]]?)$", expression)
    if column_match:
        return re.sub(r"[`\"\[\]]", "", column_match.group(2))
    return expression[:80]


def _count_sql_statements(text: str) -> int:
    statements = [part.strip() for part in text.split(";") if part.strip()]
    if statements:
        return len(statements)
    return 1 if text.strip() else 0


def _count_xml_tags(text: str) -> Counter[str]:
    return Counter(match.group(1).split("}")[-1] for match in re.finditer(r"</?([A-Za-z_][\w:.-]*)", text))


def _safe_xml_root_tag(text: str) -> str | None:
    try:
        root = ET.fromstring(text)
        return root.tag.split("}")[-1]
    except ET.ParseError:
        match = re.search(r"<([A-Za-z_][\w:.-]*)", text)
        return match.group(1) if match else None


def _extract_named_xml_nodes(text: str) -> list[dict[str, str]]:
    pattern = re.compile(r"<([A-Za-z_][\w:.-]*)([^>]*)>")
    attr_pattern = re.compile(r"\b(name|id|type|class|field|table)\s*=\s*['\"]([^'\"]{1,120})['\"]", re.IGNORECASE)
    nodes = []
    seen = set()
    for tag, attrs in pattern.findall(text):
        for attr, value in attr_pattern.findall(attrs):
            key = (tag, attr.lower(), value)
            if key not in seen:
                seen.add(key)
                nodes.append({"tag": tag, "attribute": attr.lower(), "value": value})
    return nodes


def _extract_by_tag_names(text: str, tag_names: set[str]) -> list[str]:
    values = []
    seen = set()
    for tag in tag_names:
        for match in re.finditer(rf"<{tag}>\s*([^<]{{1,160}})\s*</{tag}>", text, re.IGNORECASE):
            value = match.group(1).strip()
            if value and value not in seen:
                seen.add(value)
                values.append(value)
    return values


def _extract_dataset_candidates(text: str) -> list[str]:
    values = []
    seen = set()
    for value in _extract_xml_attr_values(text, tag_names={"TableData"}, attr_names={"name"}):
        if value not in seen:
            seen.add(value)
            values.append(value)
    for node in _extract_named_xml_nodes(text):
        value = node["value"]
        tag = node["tag"].lower()
        attr = node["attribute"]
        if attr in {"class", "type"}:
            continue
        if "data" in tag or "table" in tag or "dataset" in value.lower() or value.lower().startswith(("ds_", "dt_")):
            if value not in seen:
                seen.add(value)
                values.append(value)
    return values


def _extract_parameter_candidates(text: str) -> list[str]:
    values = []
    seen = set()
    for value in _extract_xml_attr_values_inside(text, parent_tag="Parameter", child_tag="Attributes", attr_name="name"):
        if value not in seen:
            seen.add(value)
            values.append(value)
    for node in _extract_named_xml_nodes(text):
        value = node["value"]
        tag = node["tag"].lower()
        attr = node["attribute"]
        if attr in {"class", "type"}:
            continue
        if "param" in tag or "parameter" in value.lower():
            if value not in seen:
                seen.add(value)
                values.append(value)
    return values


def _extract_finereport_field_candidates(text: str) -> list[str]:
    values = []
    seen = set()
    for value in _extract_sql_field_candidates(text):
        if value not in seen:
            seen.add(value)
            values.append(value)
    return values


def _extract_formula_candidates(text: str) -> list[str]:
    values = []
    seen = set()
    patterns = [
        r"<!\[CDATA\[\s*(=.{1,180}?)\s*\]\]>",
        r"\$\{([^}]{1,160})\}",
        r"\b(?:sum|avg|count|max|min|if|case)\s*\(([^)]{1,160})\)",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE | re.DOTALL):
            value = re.sub(r"\s+", " ", match.group(1).strip())
            if value and value not in seen:
                seen.add(value)
                values.append(value[:180])
            if len(values) >= MAX_ITEMS:
                return values
    return values


def _extract_dictionary_field_candidates(text: str) -> list[str]:
    values = []
    seen = set()
    for node in _extract_named_xml_nodes(text):
        value = node["value"]
        attr = node["attribute"]
        if attr in {"name", "field"} and value not in seen:
            seen.add(value)
            values.append(value)
    return values


def _extract_xml_attr_values(text: str, *, tag_names: set[str], attr_names: set[str]) -> list[str]:
    values = []
    seen = set()
    tag_pattern = "|".join(re.escape(tag) for tag in tag_names)
    attr_pattern = "|".join(re.escape(attr) for attr in attr_names)
    pattern = re.compile(rf"<({tag_pattern})\b([^>]*)>", re.IGNORECASE)
    value_pattern = re.compile(rf"\b({attr_pattern})\s*=\s*['\"]([^'\"]{{1,160}})['\"]", re.IGNORECASE)
    for _, attrs in pattern.findall(text):
        for _, value in value_pattern.findall(attrs):
            if value not in seen:
                seen.add(value)
                values.append(value)
    return values


def _extract_xml_attr_values_inside(text: str, *, parent_tag: str, child_tag: str, attr_name: str) -> list[str]:
    values = []
    seen = set()
    parent_pattern = re.compile(rf"<{parent_tag}\b[^>]*>(.*?)</{parent_tag}>", re.IGNORECASE | re.DOTALL)
    child_pattern = re.compile(rf"<{child_tag}\b([^>]*)/?>", re.IGNORECASE)
    value_pattern = re.compile(rf"\b{attr_name}\s*=\s*['\"]([^'\"]{{1,160}})['\"]", re.IGNORECASE)
    for parent_body in parent_pattern.findall(text):
        for attrs in child_pattern.findall(parent_body):
            match = value_pattern.search(attrs)
            if match:
                value = match.group(1)
                if value not in seen:
                    seen.add(value)
                    values.append(value)
    return values


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create structural summaries for indexed resources.")
    parser.add_argument("--index", default=".resource-index/resources.json", help="Input resource index JSON.")
    parser.add_argument(
        "--output",
        default=".resource-index/resource-summaries.json",
        help="Output summary JSON path.",
    )
    parser.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES, help="Maximum bytes to read from each file.")
    parser.add_argument("--limit", type=int, default=None, help="Optional maximum number of resources to inspect.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    payload = inspect_index(Path(args.index), Path(args.output), max_bytes=args.max_bytes, limit=args.limit)
    print(f"Wrote {payload['summary_count']} summaries to {args.output}")
    for status, count in payload["counts_by_status"].items():
        print(f"- {status}: {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
