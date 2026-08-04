import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def text_of(node):
    return "" if node is None else "".join(node.itertext()).strip()


def direct_child(node, tag):
    return next((child for child in list(node) if child.tag == tag), None)


def formula_or_text(node):
    if node is None:
        return ""
    attributes = direct_child(node, "Attributes")
    return text_of(attributes) if node.attrib.get("class") == "com.fr.base.Formula" else text_of(node)


def extract_parameters(parameters):
    if parameters is None:
        return []
    result = []
    for parameter in list(parameters):
        if parameter.tag != "Parameter":
            continue
        attributes = direct_child(parameter, "Attributes")
        result.append(
            {
                "name": (attributes.attrib.get("name") if attributes is not None else "") or None,
                "default_or_expression": formula_or_text(direct_child(parameter, "O")) or None,
            }
        )
    return result


def extract_one(source_path):
    root = ET.parse(source_path).getroot()
    datasets = []
    for table in root.findall("./TableDataMap/TableData"):
        dataset_class = table.attrib.get("class", "")
        row_data = table.findall(".//RowData")
        datasets.append(
            {
                "name": table.attrib.get("name") or None,
                "type": "database_query" if "DBTableData" in dataset_class else "embedded_or_other",
                "fine_report_class": dataset_class or None,
                "connection_name": text_of(table.find("./Connection/DatabaseName")) or None,
                "raw_sql": text_of(direct_child(table, "Query")) or None,
                "parameters": extract_parameters(direct_child(table, "Parameters")),
                "embedded_row_count": len(row_data) if row_data else 0,
            }
        )

    source = Path(source_path)
    return {
        "report": {
            "name": source.stem,
            "source_cpt_path": str(source),
            "sheet_names": [sheet.attrib.get("name") for sheet in root.iter("Report") if sheet.attrib.get("name")],
        },
        "datasets": datasets,
    }


def main():
    if len(sys.argv) < 3:
        raise SystemExit("usage: extract_report_and_datasets.py <output.json> <input.cpt> [<input.cpt> ...]")
    output_path = Path(sys.argv[1])
    models = [extract_one(source) for source in sys.argv[2:]]
    result = {"reports": models}
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"report_count": len(models), "dataset_count": sum(len(model["datasets"]) for model in models)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
