from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


SCHEMA_VERSION = "resource-index.v1"
DEFAULT_IGNORED_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".idea",
    ".vscode",
    "__pycache__",
    "node_modules",
    ".next",
    "dist",
    "build",
}
DEFAULT_IGNORED_FILES = {
    ".DS_Store",
    "Thumbs.db",
    "desktop.ini",
}
RESOURCE_TYPES = {
    ".cpt": "finereport_cpt",
    ".frm": "finereport_form",
    ".sql": "sql",
    ".xml": "xml_dictionary",
    ".hwf": "apache_hop_workflow",
    ".hpl": "apache_hop_pipeline",
    ".md": "markdown",
    ".txt": "text",
    ".csv": "sample_data",
    ".json": "json",
    ".xlsx": "spreadsheet",
    ".xls": "spreadsheet",
}


@dataclass(frozen=True)
class ResourceRecord:
    id: str
    type: str
    name: str
    relative_path: str
    extension: str
    size_bytes: int
    modified_at: str
    sha256: str


@dataclass(frozen=True)
class ResourceIndex:
    schema_version: str
    generated_at: str
    root: str
    resource_count: int
    counts_by_type: dict[str, int]
    resources: list[ResourceRecord]

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "generated_at": self.generated_at,
            "root": self.root,
            "resource_count": self.resource_count,
            "counts_by_type": self.counts_by_type,
            "resources": [asdict(record) for record in self.resources],
        }


class ResourceIndexer:
    def __init__(
        self,
        root: Path,
        *,
        include_all: bool = False,
        ignored_dirs: Iterable[str] = DEFAULT_IGNORED_DIRS,
        ignored_files: Iterable[str] = DEFAULT_IGNORED_FILES,
    ) -> None:
        self.root = root.resolve()
        self.include_all = include_all
        self.ignored_dirs = set(ignored_dirs)
        self.ignored_files = set(ignored_files)

    def build(self) -> ResourceIndex:
        if not self.root.exists():
            raise FileNotFoundError(f"Resource library root does not exist: {self.root}")
        if not self.root.is_dir():
            raise NotADirectoryError(f"Resource library root is not a directory: {self.root}")

        records = [self._record_file(path) for path in self._iter_files()]
        records.sort(key=lambda record: record.relative_path.lower())
        counts_by_type: dict[str, int] = {}
        for record in records:
            counts_by_type[record.type] = counts_by_type.get(record.type, 0) + 1

        return ResourceIndex(
            schema_version=SCHEMA_VERSION,
            generated_at=datetime.now(timezone.utc).isoformat(),
            root=str(self.root),
            resource_count=len(records),
            counts_by_type=dict(sorted(counts_by_type.items())),
            resources=records,
        )

    def write(self, output_path: Path) -> ResourceIndex:
        index = self.build()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(index.to_json_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return index

    def _iter_files(self) -> Iterable[Path]:
        stack = [self.root]
        while stack:
            current = stack.pop()
            for child in current.iterdir():
                if child.is_dir():
                    if child.name not in self.ignored_dirs:
                        stack.append(child)
                    continue
                if not child.is_file() or child.name in self.ignored_files:
                    continue
                if self.include_all or child.suffix.lower() in RESOURCE_TYPES:
                    yield child

    def _record_file(self, path: Path) -> ResourceRecord:
        stat = path.stat()
        relative_path = path.relative_to(self.root).as_posix()
        extension = path.suffix.lower()
        resource_type = RESOURCE_TYPES.get(extension, "unknown")
        return ResourceRecord(
            id=_stable_id(relative_path),
            type=resource_type,
            name=path.name,
            relative_path=relative_path,
            extension=extension,
            size_bytes=stat.st_size,
            modified_at=datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
            sha256=_sha256(path),
        )


def _stable_id(relative_path: str) -> str:
    digest = hashlib.sha256(relative_path.encode("utf-8")).hexdigest()[:16]
    return f"res_{digest}"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Index the local Agentic GenBI resource library.")
    parser.add_argument("--root", required=True, help="Resource library root directory.")
    parser.add_argument(
        "--output",
        default=".resource-index/resources.json",
        help="Output JSON path. Defaults to .resource-index/resources.json.",
    )
    parser.add_argument(
        "--include-all",
        action="store_true",
        help="Index all file extensions except ignored noise files.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    index = ResourceIndexer(Path(args.root), include_all=args.include_all).write(Path(args.output))
    print(f"Wrote {index.resource_count} resources to {args.output}")
    for resource_type, count in index.counts_by_type.items():
        print(f"- {resource_type}: {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
