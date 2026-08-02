from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any


PART_PATTERN = re.compile(r"^(?P<name>.+)\.(?P<part>0[123])_[^.]+\.json$")
MERGED_PATTERN = re.compile(r"^(?P<name>.+)\.原始解析\.json$")
SENSITIVE_SEMANTIC_TOKEN_PATTERN = re.compile(
    r"(?:password|passwd|secret|token|credential|username|user_name|user_id|phone|mobile|email|id_card|"
    r"密码|密钥|令牌|凭证|用户|账号|手机号|电话|邮箱|身份证)",
    re.IGNORECASE,
)


class FineReportReportRepository:
    def __init__(self, root: Path | None = None) -> None:
        configured_root = Path(os.getenv("GENBI_FINEREPORT_ROOT", "资源库/finereport/解析"))
        self.root = root or configured_root

    def list_reports(self) -> list[dict[str, Any]]:
        return [self._load_report(name, source)["report"] for name, source in self._report_sources().items()]

    def get_report(self, report_id: str) -> dict[str, Any] | None:
        for name, source in self._report_sources().items():
            if _report_id(name) == report_id:
                return self._load_report(name, source)
        return None

    def build_agent_semantic_context(
        self,
        *,
        max_reports: int = 3,
        max_datasets_per_report: int = 12,
        max_parameters_per_dataset: int = 12,
        max_bindings_per_report: int = 32,
        max_bytes: int = 16_000,
    ) -> dict[str, Any] | None:
        """Return a bounded report-semantic summary suitable for an authorized model prompt.

        The parsed source is richer than an LLM needs.  In particular, raw SQL,
        data-source connection names, CPT paths, parameter defaults and cell text
        are intentionally excluded from this export.
        """

        reports: list[dict[str, Any]] = []
        for name, source in self._report_sources().items():
            if len(reports) >= max_reports:
                break
            loaded = self._load_report(name, source)
            report = loaded["report"]
            if report.get("status") != "complete":
                continue
            reports.append(
                _safe_report_semantic_summary(
                    loaded,
                    max_datasets=max_datasets_per_report,
                    max_parameters=max_parameters_per_dataset,
                    max_bindings=max_bindings_per_report,
                )
            )

        if not reports:
            return None
        context = {"kind": "finereport_report_semantics", "reports": reports}
        encoded = json.dumps(context, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        return context if len(encoded) <= max_bytes else None

    def _report_sources(self) -> dict[str, dict[str, Path]]:
        sources = self._merged_files()
        for name, parts in self._group_files().items():
            sources.setdefault(name, parts)
        return dict(sorted(sources.items()))

    def _merged_files(self) -> dict[str, dict[str, Path]]:
        groups: dict[str, dict[str, Path]] = {}
        if not self.root.exists():
            return groups
        for path in sorted(self.root.rglob("*.json"), key=lambda item: str(item.relative_to(self.root))):
            match = MERGED_PATTERN.match(path.name)
            if not match:
                continue
            relative_stem = path.relative_to(self.root).with_suffix("")
            name = str(relative_stem).removesuffix(".原始解析").replace("\\", "/")
            groups[name] = {"merged": path}
        return groups

    def _group_files(self) -> dict[str, dict[str, Path]]:
        groups: dict[str, dict[str, Path]] = {}
        if not self.root.exists():
            return groups
        for path in sorted(self.root.glob("*.json"), key=lambda item: item.name):
            match = PART_PATTERN.match(path.name)
            if not match:
                continue
            groups.setdefault(match.group("name"), {})[match.group("part")] = path
        return dict(sorted(groups.items()))

    def _load_report(self, name: str, parts: dict[str, Path]) -> dict[str, Any]:
        if "merged" in parts:
            return self._load_merged_report(name, parts["merged"])

        parsed: dict[str, dict[str, Any]] = {}
        errors: list[str] = []
        for part, path in parts.items():
            try:
                parsed[part] = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                errors.append(f"{path.name}: {exc}")

        datasets_payload = _first_report(parsed.get("01"))
        interactions_payload = _first_report(parsed.get("02"))
        structure_payload = parsed.get("03", {})
        report_metadata = _first_mapping(
            datasets_payload.get("report"),
            interactions_payload.get("report"),
            structure_payload.get("report"),
        )
        datasets = _list(datasets_payload.get("datasets"))
        parameters = _list(interactions_payload.get("parameters"))
        parameter_widgets = _list(interactions_payload.get("parameter_widgets"))
        conditional_rules = _list(interactions_payload.get("conditional_rules"))
        sheets = [_normalize_sheet(sheet) for sheet in _list(structure_payload.get("sheets"))]
        available_parts = sorted(parsed)
        missing_parts = [part for part in ("01", "02", "03") if part not in parsed]
        status = "complete" if not errors and not missing_parts else "incomplete"
        sheet_names = report_metadata.get("sheet_names") or [sheet["name"] for sheet in sheets]
        counts = {
            "sheets": len(sheets),
            "datasets": len(datasets),
            "sqlDatasets": sum(1 for item in datasets if item.get("raw_sql")),
            "parameters": len(parameters),
            "parameterWidgets": len(parameter_widgets),
            "conditionalRules": len(conditional_rules),
            "cells": sum(len(sheet["cells"]) for sheet in sheets),
            "formulas": sum(1 for sheet in sheets for cell in sheet["cells"] if cell.get("formula")),
            "bindings": sum(1 for sheet in sheets for cell in sheet["cells"] if cell.get("binding")),
        }
        summary = {
            "id": _report_id(name),
            "name": report_metadata.get("name") or name,
            "sourceCptPath": report_metadata.get("source_cpt_path"),
            "sheetNames": sheet_names,
            "status": status,
            "availableParts": available_parts,
            "missingParts": missing_parts,
            "errors": errors,
            "counts": counts,
        }
        return {
            "report": summary,
            "datasets": datasets,
            "parameters": parameters,
            "parameterWidgets": parameter_widgets,
            "conditionalRules": conditional_rules,
            "sheets": sheets,
        }

    def _load_merged_report(self, name: str, path: Path) -> dict[str, Any]:
        errors: list[str] = []
        payload: dict[str, Any] = {}
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                payload = loaded
            else:
                errors.append(f"{path.name}: expected JSON object")
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"{path.name}: {exc}")

        report_metadata = _first_mapping(payload.get("report"))
        interactions = _first_mapping(payload.get("parameters_and_interactions"))
        structure = _first_mapping(payload.get("report_structure"))
        datasets = _list(payload.get("datasets"))
        parameters = _list(interactions.get("parameters"))
        parameter_widgets = _list(interactions.get("parameter_widgets"))
        conditional_rules = _list(interactions.get("conditional_rules"))
        sheets = [_normalize_sheet(sheet) for sheet in _list(structure.get("sheets"))]
        status = "complete" if not errors else "incomplete"
        sheet_names = report_metadata.get("sheet_names") or [sheet["name"] for sheet in sheets]
        counts = {
            "sheets": len(sheets),
            "datasets": len(datasets),
            "sqlDatasets": sum(1 for item in datasets if item.get("raw_sql")),
            "parameters": len(parameters),
            "parameterWidgets": len(parameter_widgets),
            "conditionalRules": len(conditional_rules),
            "cells": sum(len(sheet["cells"]) for sheet in sheets),
            "formulas": sum(1 for sheet in sheets for cell in sheet["cells"] if cell.get("formula")),
            "bindings": sum(1 for sheet in sheets for cell in sheet["cells"] if cell.get("binding")),
        }
        summary = {
            "id": _report_id(name),
            "name": report_metadata.get("name") or Path(name).name,
            "sourceCptPath": report_metadata.get("source_cpt_path"),
            "sheetNames": sheet_names,
            "status": status,
            "availableParts": ["merged"],
            "missingParts": [],
            "errors": errors,
            "counts": counts,
        }
        return {
            "report": summary,
            "datasets": datasets,
            "parameters": parameters,
            "parameterWidgets": parameter_widgets,
            "conditionalRules": conditional_rules,
            "sheets": sheets,
        }


def _report_id(name: str) -> str:
    digest = hashlib.sha1(name.encode("utf-8"), usedforsecurity=False).hexdigest()[:12]
    return f"finereport_{digest}"


def _first_report(payload: dict[str, Any] | None) -> dict[str, Any]:
    reports = _list((payload or {}).get("reports"))
    return reports[0] if reports and isinstance(reports[0], dict) else {}


def _first_mapping(*values: Any) -> dict[str, Any]:
    for value in values:
        if isinstance(value, dict) and value:
            return value
    return {}


def _list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _normalize_sheet(sheet: dict[str, Any]) -> dict[str, Any]:
    cells: list[dict[str, Any]] = []
    row_count = 0
    column_count = 0
    for raw_cell in _list(sheet.get("cells")):
        row = _positive_int(raw_cell.get("row"), 1)
        rowspan = _positive_int(raw_cell.get("rowspan"), 1)
        colspan = _positive_int(raw_cell.get("colspan"), 1)
        column = str(raw_cell.get("column") or "A").upper()
        column_index = _column_index(column)
        cell = dict(raw_cell)
        cell.update(
            {
                "row": row,
                "column": column,
                "columnIndex": column_index,
                "rowspan": rowspan,
                "colspan": colspan,
            }
        )
        cells.append(cell)
        row_count = max(row_count, row + rowspan - 1)
        column_count = max(column_count, column_index + colspan - 1)
    return {
        "name": sheet.get("name") or "Sheet",
        "rowCount": row_count,
        "columnCount": column_count,
        "cells": cells,
    }


def _safe_report_semantic_summary(
    loaded: dict[str, Any],
    *,
    max_datasets: int,
    max_parameters: int,
    max_bindings: int,
) -> dict[str, Any]:
    report = loaded["report"]
    datasets = [
        {
            "name": str(dataset.get("name") or "dataset"),
            "type": str(dataset.get("type") or "unknown"),
            "parameterNames": [
                str(parameter.get("name"))
                for parameter in _list(dataset.get("parameters"))[:max_parameters]
                if parameter.get("name") and _is_safe_semantic_identifier(str(parameter["name"]))
            ],
        }
        for dataset in loaded["datasets"][:max_datasets]
    ]
    bindings: list[dict[str, str]] = []
    for sheet in loaded["sheets"]:
        for cell in sheet["cells"]:
            binding = cell.get("binding")
            if not isinstance(binding, dict):
                continue
            dataset = binding.get("dataset")
            field = binding.get("field")
            if not dataset or not field or not _is_safe_semantic_identifier(str(field)):
                continue
            bindings.append({"sheet": str(sheet["name"]), "dataset": str(dataset), "field": str(field)})
            if len(bindings) >= max_bindings:
                break
        if len(bindings) >= max_bindings:
            break
    counts = report["counts"]
    return {
        "id": report["id"],
        "name": report["name"],
        "sheetNames": list(report["sheetNames"]),
        "counts": {
            key: counts[key]
            for key in ("sheets", "datasets", "parameters", "cells", "formulas", "bindings")
        },
        "datasets": datasets,
        "bindings": bindings,
    }


def _is_safe_semantic_identifier(value: str) -> bool:
    return bool(value.strip()) and not SENSITIVE_SEMANTIC_TOKEN_PATTERN.search(value)


def _positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _column_index(column: str) -> int:
    result = 0
    for character in column:
        if not "A" <= character <= "Z":
            continue
        result = result * 26 + ord(character) - ord("A") + 1
    return result or 1
