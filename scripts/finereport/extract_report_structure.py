import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


CELL_REF_RE = re.compile(r"\b([A-Z]{1,3}[1-9][0-9]*)\b")


def text_of(node):
    return "" if node is None else "".join(node.itertext()).strip()


def direct_child(node, tag):
    return next((child for child in list(node) if child.tag == tag), None)


def col_name(index):
    index += 1
    result = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        result = chr(65 + remainder) + result
    return result


def cell_address(cell):
    return f"{col_name(int(cell.attrib.get('c', 0)))}{int(cell.attrib.get('r', 0)) + 1}"


def formula_text(node):
    attributes = direct_child(node, "Attributes")
    return text_of(attributes)


def extract_cell(cell):
    item = {
        "cell": cell_address(cell),
        "row": int(cell.attrib.get("r", 0)) + 1,
        "column": col_name(int(cell.attrib.get("c", 0))),
    }
    colspan = int(cell.attrib.get("cs", 1))
    rowspan = int(cell.attrib.get("rs", 1))
    if colspan > 1:
        item["colspan"] = colspan
    if rowspan > 1:
        item["rowspan"] = rowspan

    value = direct_child(cell, "O")
    if value is None:
        return item
    if value.attrib.get("t") == "DSColumn":
        attributes = direct_child(value, "Attributes")
        item["binding"] = {
            "dataset": attributes.attrib.get("dsName") if attributes is not None else None,
            "field": attributes.attrib.get("columnName") if attributes is not None else None,
        }
        condition = text_of(direct_child(value, "Condition"))
        if condition:
            item["binding"]["condition"] = condition
    elif value.attrib.get("class") == "com.fr.base.Formula":
        formula = formula_text(value)
        item["formula"] = formula
        dependencies = sorted(set(CELL_REF_RE.findall(formula)))
        if dependencies:
            item["dependencies"] = dependencies
    else:
        literal = text_of(value)
        if literal:
            item["value"] = literal
    return item


def extract_one(source_path):
    root = ET.parse(source_path).getroot()
    source = Path(source_path)
    sheets = []
    for sheet in root.iter("Report"):
        cells = [extract_cell(cell) for cell in sheet.iter("C")]
        sheets.append({
            "name": sheet.attrib.get("name") or None,
            "cells": cells,
        })
    return {
        "report": {
            "name": source.stem,
            "source_cpt_path": str(source),
        },
        "sheets": sheets,
    }


def main():
    if len(sys.argv) != 3:
        raise SystemExit("usage: extract_report_structure.py <output.json> <input.cpt>")
    output = Path(sys.argv[1])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(extract_one(sys.argv[2]), ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
