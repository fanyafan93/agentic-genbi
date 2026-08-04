import argparse
import json
from datetime import datetime
from pathlib import Path

from extract_parameters_and_interactions import extract_one as extract_interactions
from extract_report_and_datasets import extract_one as extract_datasets
from extract_report_structure import extract_one as extract_structure
from merge_usage_statistics import build_usage_index, read_usage, usage_for_report


def combine(source):
    datasets_part = extract_datasets(source)
    interactions_part = extract_interactions(source)
    structure_part = extract_structure(source)
    report = datasets_part["report"]
    names = {
        report.get("name"),
        interactions_part.get("report", {}).get("name"),
        structure_part.get("report", {}).get("name"),
    }
    if len(names) != 1:
        raise ValueError("report names do not match")
    return {
        "report": report,
        "datasets": datasets_part.get("datasets", []),
        "parameters_and_interactions": {
            "parameters": interactions_part.get("parameters", []),
            "parameter_widgets": interactions_part.get("parameter_widgets", []),
            "conditional_rules": interactions_part.get("conditional_rules", []),
        },
        "report_structure": {
            "sheets": structure_part.get("sheets", []),
        },
    }


def write_json(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source_lr_directory")
    parser.add_argument("output_directory")
    parser.add_argument("--usage-file", help="Excel/CSV usage statistics file to append as report_usage")
    args = parser.parse_args()

    source_root = Path(args.source_lr_directory).resolve()
    output_root = Path(args.output_directory).resolve()
    usage_index, total_index = None, None
    if args.usage_file:
        usage_records = read_usage(args.usage_file)
        usage_index, total_index = build_usage_index(usage_records)

    sources = sorted(source_root.rglob("*.cpt"))
    succeeded, failed = 0, []
    for index, source in enumerate(sources, start=1):
        relative = source.relative_to(source_root)
        output = output_root / relative.parent / f"{source.stem}.json"
        try:
            payload = combine(source)
            if usage_index is not None and total_index is not None:
                payload["report_usage"] = usage_for_report(output, payload, usage_index, total_index)
            output.parent.mkdir(parents=True, exist_ok=True)
            write_json(output, payload)
            succeeded += 1
        except Exception as error:
            failed.append({"source_cpt_path": str(source), "error": str(error)})
        print(f"[{index}/{len(sources)}] {source}", flush=True)
    if failed:
        for failure in failed:
            print(json.dumps(failure, ensure_ascii=False), file=sys.stderr)
        failure_file = Path.cwd() / "outputs" / f"报表画像失败_{datetime.now():%Y%m%d_%H%M%S}.json"
        write_json(failure_file, failed)
    print(json.dumps({"total": len(sources), "succeeded": succeeded, "failed": len(failed)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
