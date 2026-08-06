from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from backend.system_management.context_status import list_installed_skills


class ContextStatusTest(unittest.TestCase):
    def test_lists_skill_metadata_without_returning_instruction_bodies(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            skill_dir = root / "skills" / ".system" / "openai-docs"
            skill_dir.mkdir(parents=True)
            (skill_dir / "SKILL.md").write_text(
                "---\n"
                'name: "openai-docs"\n'
                'description: "Read current OpenAI documentation."\n'
                "---\n\n"
                "SECRET INSTRUCTION BODY\n",
                encoding="utf-8",
            )

            skills = list_installed_skills(root)

        self.assertEqual(
            skills,
            [
                {
                    "name": "openai-docs",
                    "description": "Read current OpenAI documentation.",
                    "scope": "system",
                }
            ],
        )
        self.assertNotIn("SECRET", str(skills))
