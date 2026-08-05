import argparse
import json
import re
from pathlib import Path


EXCLUDED_KEYS = {
    "cell",
    "row",
    "column",
    "colspan",
    "rowspan",
    "formula",
    "dependencies",
    "raw_sql",
    "sql",
    "condition",
    "expand",
    "definition",
}


def clean_text(value):
    if value is None:
        return ""
    text = str(value).strip()
    text = re.sub(r"\s+", " ", text)
    return text


def is_exact_string(value):
    text = clean_text(value)
    if not text:
        return False
    if text.startswith("="):
        return False
    if "${" in text or "$$$" in text:
        return False
    if re.search(r"\b(select|from|where|join|union|group\s+by|order\s+by)\b", text, re.I):
        return False
    if re.fullmatch(r"[A-Z]{1,3}\d+", text):
        return False
    return True


def unique(values, limit=None):
    seen = set()
    result = []
    for value in values:
        text = clean_text(value)
        if text and text not in seen:
            seen.add(text)
            result.append(text)
            if limit and len(result) >= limit:
                break
    return result


def compact_dataset(dataset):
    output = {
        "name": clean_text(dataset.get("name")),
        "type": clean_text(dataset.get("type")),
        "connection_name": clean_text(dataset.get("connection_name")),
    }
    parameters = dataset.get("parameters")
    if isinstance(parameters, list):
        output["parameters"] = unique(
            item.get("name") if isinstance(item, dict) else item
            for item in parameters
            if is_exact_string(item.get("name") if isinstance(item, dict) else item)
        )
    return {key: value for key, value in output.items() if value}


def compact_widget(widget):
    dictionary = widget.get("dictionary") if isinstance(widget.get("dictionary"), dict) else {}
    parameter = widget.get("parameter")
    label = widget.get("label")
    widget_class = widget.get("widget_class")
    default_value = widget.get("default_value")
    output = {
        "parameter": clean_text(parameter) if is_exact_string(parameter) else "",
        "label": clean_text(label) if is_exact_string(label) else "",
        "widget_class": clean_text(widget_class) if is_exact_string(widget_class) else "",
        "default_value": clean_text(default_value) if is_exact_string(default_value) else "",
        "dictionary_table_data": clean_text(dictionary.get("table_data")),
        "custom_values": unique(
            value for value in dictionary.get("custom_values", []) if is_exact_string(value)
        ),
    }
    return {key: value for key, value in output.items() if value not in ("", [])}


def walk_exact_strings(value, parent_key=""):
    if parent_key in EXCLUDED_KEYS:
        return
    if isinstance(value, dict):
        for key, child in value.items():
            yield from walk_exact_strings(child, key)
    elif isinstance(value, list):
        for child in value:
            yield from walk_exact_strings(child, parent_key)
    elif isinstance(value, str) and is_exact_string(value):
        yield value


def collect_structure_strings(report_structure):
    labels = []
    binding_datasets = []
    binding_fields = []
    sheets = report_structure.get("sheets", []) if isinstance(report_structure, dict) else []
    for sheet in sheets:
        for cell in sheet.get("cells", []):
            if not isinstance(cell, dict):
                continue
            value = cell.get("value")
            if is_exact_string(value):
                labels.append(value)
            binding = cell.get("binding")
            if isinstance(binding, dict):
                dataset = binding.get("dataset")
                field = binding.get("field") or binding.get("column")
                if is_exact_string(dataset):
                    binding_datasets.append(dataset)
                if is_exact_string(field):
                    binding_fields.append(field)
    return {
        "visible_text": unique(labels, limit=300),
        "binding_datasets": unique(binding_datasets, limit=200),
        "binding_fields": unique(binding_fields, limit=300),
    }


def compact_usage(report_usage):
    if not isinstance(report_usage, dict):
        return {}
    users = report_usage.get("users", [])
    return {
        "total_usage_count": report_usage.get("total_usage_count", 0),
        "user_count": len(users) if isinstance(users, list) else 0,
        "top_users": [
            {
                "user_name": clean_text(user.get("user_name")),
                "department": clean_text(user.get("department")),
                "position": clean_text(user.get("position")),
                "usage_count": user.get("usage_count", 0),
            }
            for user in (users[:10] if isinstance(users, list) else [])
        ],
    }


def build_report_index(json_path, payload, profiles_root):
    report = payload.get("report", {}) if isinstance(payload.get("report"), dict) else {}
    params = payload.get("parameters_and_interactions", {})
    widgets = params.get("parameter_widgets", []) if isinstance(params, dict) else []
    structure_strings = collect_structure_strings(payload.get("report_structure", {}))
    all_strings = unique(
        [
            report.get("name"),
            *report.get("sheet_names", []),
            *walk_exact_strings(params),
            *structure_strings["visible_text"],
            *structure_strings["binding_datasets"],
            *structure_strings["binding_fields"],
        ],
        limit=600,
    )
    return {
        "report_name": clean_text(report.get("name") or json_path.stem),
        "source_cpt_path": clean_text(report.get("source_cpt_path")),
        "profile_json_path": str(json_path.relative_to(profiles_root)).replace("\\", "/"),
        "sheet_names": unique(report.get("sheet_names", [])),
        "datasets": [
            compact_dataset(dataset)
            for dataset in payload.get("datasets", [])
            if isinstance(dataset, dict)
        ],
        "parameters": [
            compact_widget(widget)
            for widget in widgets
            if isinstance(widget, dict)
        ],
        "report_strings": structure_strings,
        "usage": compact_usage(payload.get("report_usage", {})),
        "search_text": " | ".join(all_strings),
    }


def build_index(profiles_dir):
    profiles_root = Path(profiles_dir)
    reports = []
    for json_path in sorted(profiles_root.rglob("*.json")):
        payload = json.loads(json_path.read_text(encoding="utf-8"))
        reports.append(build_report_index(json_path, payload, profiles_root))
    reports.sort(key=lambda item: item["profile_json_path"])
    return {
        "index_type": "finereport_profile_index",
        "source_profiles_dir": str(profiles_root),
        "rules": [
            "不包含 raw_sql/sql",
            "不包含公式",
            "不包含单元格坐标、行号、列号",
            "只保留画像中已经存在的确定字符串，不做指标/维度推断",
        ],
        "report_count": len(reports),
        "reports": reports,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("profiles_dir")
    parser.add_argument("output_file")
    args = parser.parse_args()
    index = build_index(args.profiles_dir)
    output = Path(args.output_file)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(output), "report_count": index["report_count"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
