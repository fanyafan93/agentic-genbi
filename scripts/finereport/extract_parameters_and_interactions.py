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
        return None
    attributes = direct_child(node, "Attributes")
    value = text_of(attributes) if node.attrib.get("class") == "com.fr.base.Formula" else text_of(node)
    return value or None


def col_name(index):
    index += 1
    result = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        result = chr(65 + remainder) + result
    return result


def cell_address(cell):
    return f"{col_name(int(cell.attrib.get('c', 0)))}{int(cell.attrib.get('r', 0)) + 1}"


def extract_parameters(root):
    parameters = []
    parameter_root = root.find("./Parameters")
    if parameter_root is None:
        return parameters
    for parameter in parameter_root.findall("./Parameter"):
        attributes = direct_child(parameter, "Attributes")
        parameters.append(
            {
                "name": (attributes.attrib.get("name") if attributes is not None else "") or None,
                "default_or_expression": formula_or_text(direct_child(parameter, "O")),
            }
        )
    return parameters


def extract_parameter_widgets(root):
    widgets = []
    parameter_ui = root.find(".//ParameterUI")
    if parameter_ui is None:
        return widgets
    for widget in parameter_ui.iter("InnerWidget"):
        name_node = direct_child(widget, "WidgetName")
        name = name_node.attrib.get("name", "") if name_node is not None else ""
        if not name:
            continue
        label_node = direct_child(widget, "LabelName")
        dictionary = direct_child(widget, "Dictionary")
        custom_values = []
        table_data_name = None
        if dictionary is not None:
            custom_values = [
                {"key": item.attrib.get("key") or None, "value": item.attrib.get("value") or None}
                for item in dictionary.findall(".//Dict")
            ]
            table_data_name = text_of(dictionary.find(".//TableData/Name")) or None
        widgets.append(
            {
                "parameter": name,
                "widget_class": widget.attrib.get("class") or None,
                "label": label_node.attrib.get("name") if label_node is not None else None,
                "default_value": text_of(direct_child(widget, "widgetValue")) or None,
                "dictionary": {
                    "class": dictionary.attrib.get("class") if dictionary is not None else None,
                    "table_data": table_data_name,
                    "custom_values": custom_values,
                },
            }
        )
    return widgets


def extract_conditional_rules(root):
    rules = []
    for cell in root.iter("C"):
        for highlight in cell.findall("./HighlightList/Highlight"):
            action = direct_child(highlight, "HighlightAction")
            rules.append(
                {
                    "cell": cell_address(cell),
                    "condition": text_of(direct_child(highlight, "Condition")) or None,
                    "action_class": action.attrib.get("class") if action is not None else None,
                    "action": text_of(action) or None,
                }
            )
    return rules


def extract_one(source_path):
    root = ET.parse(source_path).getroot()
    source = Path(source_path)
    return {
        "report": {
            "name": source.stem,
            "source_cpt_path": str(source),
            "sheet_names": [sheet.attrib.get("name") for sheet in root.iter("Report") if sheet.attrib.get("name")],
        },
        "parameters": extract_parameters(root),
        "parameter_widgets": extract_parameter_widgets(root),
        "conditional_rules": extract_conditional_rules(root),
    }


def main():
    if len(sys.argv) < 3:
        raise SystemExit("usage: extract_parameters_and_interactions.py <output.json> <input.cpt> [<input.cpt> ...]")
    output = Path(sys.argv[1])
    result = {"reports": [extract_one(source) for source in sys.argv[2:]]}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"report_count": len(result["reports"])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
