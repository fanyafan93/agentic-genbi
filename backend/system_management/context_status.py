from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any


_FRONTMATTER_FIELD = re.compile(r"^(name|description):\s*(.*)$")


def list_installed_skills(
    codex_home: str | Path | None = None,
) -> list[dict[str, Any]]:
    root = Path(
        codex_home
        or os.getenv("GENBI_CODEX_HOME", "").strip()
        or Path.home() / ".codex"
    )
    skills_root = root / "skills"
    if not skills_root.is_dir():
        return []

    skills: list[dict[str, Any]] = []
    for skill_file in sorted(skills_root.rglob("SKILL.md")):
        metadata = _read_frontmatter(skill_file)
        name = metadata.get("name") or skill_file.parent.name
        skills.append(
            {
                "name": name,
                "description": metadata.get("description", ""),
                "scope": (
                    "system"
                    if ".system" in skill_file.relative_to(skills_root).parts
                    else "user"
                ),
            }
        )
    return skills


def _read_frontmatter(skill_file: Path) -> dict[str, str]:
    try:
        lines = skill_file.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        return {}
    if not lines or lines[0].strip() != "---":
        return {}

    metadata: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        match = _FRONTMATTER_FIELD.match(line.strip())
        if not match:
            continue
        key, value = match.groups()
        metadata[key] = value.strip().strip("\"'")
    return metadata
