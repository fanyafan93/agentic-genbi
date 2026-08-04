import argparse
import re
import urllib.parse
import urllib.request
from pathlib import Path


DEFAULT_OUTPUT_DIR = Path(r"E:\my_repo\agentic genbi\资源库\finereport")
DEFAULT_REPORT_NAME = "finereport近90天执行记录汇总"


def safe_filename(value):
    text = urllib.parse.unquote(urllib.parse.unquote(value or "")).replace("\\", "/")
    name = Path(text).stem or "finereport_export"
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .")
    return name or "finereport_export"


def report_name_from_url(url):
    query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    viewlet = query.get("viewlet", [""])[0]
    return safe_filename(viewlet)


def extension_from_response(url, content_type):
    lower = (content_type or "").lower()
    if "csv" in lower:
        return ".csv"
    if "spreadsheetml" in lower or "excel" in lower or "xlsx" in lower:
        return ".xlsx"
    path = urllib.parse.urlparse(url).path.lower()
    if path.endswith(".csv"):
        return ".csv"
    if path.endswith(".xls"):
        return ".xls"
    if path.endswith(".xlsx"):
        return ".xlsx"
    return ".xlsx"


def build_output_path(url, output_dir, report_name=None, date_text=None, extension=".xlsx"):
    name = safe_filename(report_name) if report_name else DEFAULT_REPORT_NAME
    suffix = f"_{date_text}" if date_text else ""
    return Path(output_dir) / f"{name}{suffix}{extension}"


def download(url, output_dir=DEFAULT_OUTPUT_DIR, report_name=None, date_text=None):
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=120) as response:
        data = response.read()
        extension = extension_from_response(url, response.headers.get("Content-Type", ""))
        output = build_output_path(url, output_dir, report_name, date_text, extension)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(data)
        return {
            "saved_path": str(output),
            "bytes": len(data),
            "content_type": response.headers.get("Content-Type", ""),
            "content_disposition": response.headers.get("Content-Disposition", ""),
        }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("url", help="FineReport excel export URL")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--name", help=f"output report name; defaults to {DEFAULT_REPORT_NAME}")
    parser.add_argument("--date", help="optional date suffix such as 20260804")
    args = parser.parse_args()
    result = download(args.url, args.output_dir, args.name, args.date)
    for key, value in result.items():
        print(f"{key}={value}")


if __name__ == "__main__":
    main()
