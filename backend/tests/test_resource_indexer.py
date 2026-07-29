from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from resource_library.indexer import ResourceIndexer


class ResourceIndexerTest(unittest.TestCase):
    def test_indexes_supported_resources_without_reading_ignored_noise(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "reports").mkdir()
            (root / "reports" / "sales.cpt").write_text("fake cpt", encoding="utf-8")
            (root / "etl.hwf").write_text("<workflow />", encoding="utf-8")
            (root / "debug.log").write_text("ignore me", encoding="utf-8")
            (root / ".DS_Store").write_text("ignore me", encoding="utf-8")

            index = ResourceIndexer(root).build()

            self.assertEqual(index.resource_count, 2)
            self.assertEqual(index.counts_by_type["finereport_cpt"], 1)
            self.assertEqual(index.counts_by_type["apache_hop_workflow"], 1)
            self.assertEqual([item.relative_path for item in index.resources], ["etl.hwf", "reports/sales.cpt"])
            self.assertTrue(all(item.sha256 for item in index.resources))

    def test_writes_json_index(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output = root / "out" / "resources.json"
            (root / "metric.sql").write_text("select 1", encoding="utf-8")

            ResourceIndexer(root).write(output)

            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(payload["schema_version"], "resource-index.v1")
            self.assertEqual(payload["resource_count"], 1)
            self.assertEqual(payload["resources"][0]["type"], "sql")


if __name__ == "__main__":
    unittest.main()
