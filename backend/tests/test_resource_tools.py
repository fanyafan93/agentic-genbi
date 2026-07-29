from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from resource_library.indexer import ResourceIndexer
from resource_library.inspector import inspect_index
from resource_library.tools import ResourceLibrary


class ResourceToolsTest(unittest.TestCase):
    def test_search_resources_returns_hits_without_full_text(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            index_path = root / "resources.json"
            summary_path = root / "summaries.json"
            (root / "consumer_rebuy_30d.sql").write_text(
                "select member_id from dm.dm_consr_shaver_rebuy_analysis_v2;",
                encoding="utf-8",
            )
            ResourceIndexer(root).write(index_path)
            inspect_index(index_path, summary_path)

            library = ResourceLibrary(index_path=index_path, summary_path=summary_path)
            results = library.search_resources("rebuy", limit=5)

            self.assertEqual(len(results), 1)
            self.assertEqual(results[0].name, "consumer_rebuy_30d.sql")
            self.assertIn("name", results[0].matched_fields)
            self.assertNotIn("select member_id", json.dumps(results[0].__dict__, ensure_ascii=False))

    def test_inspect_resource_returns_summary_signals(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            index_path = root / "resources.json"
            summary_path = root / "summaries.json"
            (root / "job.hpl").write_text("<pipeline><transform><name>Load Sales</name></transform></pipeline>", encoding="utf-8")
            index = ResourceIndexer(root).write(index_path)
            inspect_index(index_path, summary_path)

            library = ResourceLibrary(index_path=index_path, summary_path=summary_path)
            detail = library.inspect_resource(index.resources[0].id)

            self.assertEqual(detail.status, "ok")
            self.assertEqual(detail.signals["root_tag"], "pipeline")
            self.assertIn("tag_counts", detail.signals)

    def test_search_resources_uses_structural_field_signals(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            index_path = root / "resources.json"
            summary_path = root / "summaries.json"
            (root / "sales_overview.cpt").write_text(
                """
                <WorkBook>
                  <TableData name="basic_data">
                    <Parameters><Parameter><Attributes name="sBrand"/></Parameter></Parameters>
                    <sql><![CDATA[
                      select t.order_id, sum(t.gmv) as total_gmv
                      from dm.dm_sale_total t
                    ]]></sql>
                  </TableData>
                </WorkBook>
                """,
                encoding="utf-8",
            )
            ResourceIndexer(root).write(index_path)
            inspect_index(index_path, summary_path)

            library = ResourceLibrary(index_path=index_path, summary_path=summary_path)

            self.assertIn("finereport.parameter_candidates", library.search_resources("sBrand", limit=1)[0].matched_fields)
            self.assertIn("finereport.field_candidates", library.search_resources("total_gmv", limit=1)[0].matched_fields)
            self.assertIn("finereport.read_table_refs", library.search_resources("dm_sale_total", limit=1)[0].matched_fields)

    def test_read_resource_excerpt_is_bounded_and_supports_match(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            index_path = root / "resources.json"
            summary_path = root / "summaries.json"
            lines = [f"line {i}" for i in range(30)]
            lines[18] = "target metric line"
            (root / "notes.md").write_text("\n".join(lines), encoding="utf-8")
            index = ResourceIndexer(root).write(index_path)
            inspect_index(index_path, summary_path)

            library = ResourceLibrary(index_path=index_path, summary_path=summary_path)
            excerpt = library.read_resource_excerpt(index.resources[0].id, section="match", query="target", max_lines=5)

            self.assertIn("target metric line", excerpt.text)
            self.assertLessEqual(len(excerpt.text.splitlines()), 5)
            self.assertTrue(excerpt.truncated)

    def test_read_resource_excerpt_falls_back_to_runtime_resource_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            indexed_root = temp_root / "indexed"
            runtime_root = temp_root / "runtime"
            indexed_root.mkdir()
            runtime_root.mkdir()
            index_path = temp_root / "resources.json"
            summary_path = temp_root / "summaries.json"
            (indexed_root / "metric.sql").write_text("select 1 as metric;", encoding="utf-8")
            (runtime_root / "metric.sql").write_text("select 2 as metric;", encoding="utf-8")
            index = ResourceIndexer(indexed_root).write(index_path)
            inspect_index(index_path, summary_path)
            indexed_root.rename(temp_root / "indexed-moved")

            with patch.dict(os.environ, {"GENBI_RESOURCE_LIBRARY_ROOT": str(runtime_root)}):
                library = ResourceLibrary(index_path=index_path, summary_path=summary_path)
                excerpt = library.read_resource_excerpt(index.resources[0].id)

            self.assertEqual(library.root, runtime_root.resolve())
            self.assertIn("select 2 as metric", excerpt.text)


if __name__ == "__main__":
    unittest.main()
