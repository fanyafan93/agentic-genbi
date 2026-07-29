from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from resource_library.indexer import ResourceIndexer
from resource_library.inspector import inspect_index, inspect_resource, inspect_sql_text, inspect_xml_like_text


class ResourceInspectorTest(unittest.TestCase):
    def test_extracts_sql_table_refs_without_returning_sql_text(self) -> None:
        signals = inspect_sql_text(
            """
            -- current metric
            select a.order_id, b.member_id
            from dm.order_fact a
            join dim.member b on a.member_id = b.member_id;
            """
        )

        self.assertEqual(signals["statement_count"], 1)
        self.assertEqual(signals["table_refs"], ["dim.member", "dm.order_fact"])
        self.assertEqual(signals["read_table_refs"], ["dm.order_fact", "dim.member"])
        self.assertEqual(signals["field_candidates"], ["order_id", "member_id"])
        self.assertNotIn("select a.order_id", json.dumps(signals))

    def test_splits_sql_read_write_refs_and_output_fields(self) -> None:
        signals = inspect_sql_text(
            """
            insert into ads.sales_summary
            select a.order_id, sum(a.pay_amount) as pay_amount, b.region_name region
            from dm.order_fact a
            join dim.region b on a.region_id = b.region_id
            group by a.order_id, b.region_name;
            """
        )

        self.assertEqual(signals["read_table_refs"], ["dm.order_fact", "dim.region"])
        self.assertEqual(signals["write_table_refs"], ["ads.sales_summary"])
        self.assertEqual(signals["field_candidates"], ["order_id", "pay_amount", "region"])

    def test_ignores_cte_names_in_table_refs(self) -> None:
        signals = inspect_sql_text(
            """
            with total as (
              select order_id from dm.order_fact
            ), buyer_show as (
              select order_id from total
            )
            select order_id from buyer_show;
            """
        )

        self.assertEqual(signals["read_table_refs"], ["dm.order_fact"])
        self.assertEqual(signals["table_refs"], ["dm.order_fact"])

    def test_inspects_xml_like_resource(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            file_path = root / "job.hwf"
            file_path.write_text(
                """
                <workflow>
                  <action><name>Load Sales</name><type>TRANS</type></action>
                  <sql>select * from dm.sales_fact</sql>
                </workflow>
                """,
                encoding="utf-8",
            )
            record = ResourceIndexer(root).build().resources[0]

            summary = inspect_resource(root, record.__dict__)

            self.assertEqual(summary.status, "ok")
            self.assertEqual(summary.signals["root_tag"], "workflow")
            self.assertIn("workflow", summary.signals["tag_counts"])
            self.assertIn("dm.sales_fact", summary.signals["hop"]["lineage_table_refs"])
            self.assertEqual(summary.signals["hop"]["read_table_refs"], ["dm.sales_fact"])

    def test_extracts_finereport_business_signals(self) -> None:
        signals = inspect_xml_like_text(
            """
            <WorkBook>
              <TableData name="basic_data" class="com.fr.data.impl.DBTableData">
                <Parameters>
                  <Parameter><Attributes name="sBrand"/></Parameter>
                  <Parameter><Attributes name="sStart_date"/></Parameter>
                </Parameters>
                <sql><![CDATA[
                  select t.order_id, sum(t.gmv) as total_gmv
                  from dm.dm_sale_total t
                  join dim.store s on t.store_id = s.store_id
                ]]></sql>
              </TableData>
              <CellElement value="${sBrand}"/>
            </WorkBook>
            """,
            "finereport_cpt",
        )

        self.assertEqual(signals["finereport"]["dataset_candidates"], ["basic_data"])
        self.assertEqual(signals["finereport"]["parameter_candidates"], ["sBrand", "sStart_date"])
        self.assertEqual(signals["finereport"]["read_table_refs"], ["dm.dm_sale_total", "dim.store"])
        self.assertEqual(signals["finereport"]["field_candidates"], ["order_id", "total_gmv"])
        self.assertIn("sBrand", signals["finereport"]["formula_candidates"])

    def test_writes_summary_file_from_index(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            index_path = root / "resources.json"
            output_path = root / "summaries.json"
            (root / "metric.sql").write_text("select count(*) from mart.sales;", encoding="utf-8")
            ResourceIndexer(root).write(index_path)

            payload = inspect_index(index_path, output_path)

            self.assertEqual(payload["summary_count"], 1)
            saved = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["schema_version"], "resource-summary.v1")
            self.assertEqual(saved["summaries"][0]["signals"]["table_refs"], ["mart.sales"])


if __name__ == "__main__":
    unittest.main()
