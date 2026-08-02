from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from business_semantics.knowledge_store import KnowledgeStore


class KnowledgeStoreTest(unittest.TestCase):
    def test_save_and_list_verified_knowledge(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = KnowledgeStore(Path(temp_dir) / "knowledge.jsonl")

            record = store.save_verified_knowledge(
                title="首购后 30 天复购率",
                question="怎么计算首购后 30 天复购率？",
                conclusion="按会员首购日后 30 天内再次支付去重计算。",
                scope="剃须刀品类",
                verification="已核对历史报表和样例 SQL。",
                evidence_refs=["res_abc", "dm.rebuy_analysis"],
                turn_id="turn_1",
            )

            records = store.list_knowledge()
            self.assertEqual(records[0].id, record.id)
            self.assertEqual(records[0].title, "首购后 30 天复购率")
            self.assertEqual(records[0].evidence_refs, ["res_abc", "dm.rebuy_analysis"])

    def test_save_requires_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = KnowledgeStore(Path(temp_dir) / "knowledge.jsonl")

            with self.assertRaises(ValueError):
                store.save_verified_knowledge(
                    title="t",
                    question="q",
                    conclusion="c",
                    scope="s",
                    verification="v",
                    evidence_refs=[],
                )

    def test_delete_and_clear_knowledge(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = KnowledgeStore(Path(temp_dir) / "knowledge.jsonl")
            first = store.save_verified_knowledge(
                title="t1",
                question="q",
                conclusion="c",
                scope="s",
                verification="v",
                evidence_refs=["res_1"],
            )
            store.save_verified_knowledge(
                title="t2",
                question="q",
                conclusion="c",
                scope="s",
                verification="v",
                evidence_refs=["res_2"],
            )

            self.assertTrue(store.delete_knowledge(first.id))
            self.assertFalse(store.delete_knowledge("missing"))
            self.assertEqual(len(store.list_knowledge()), 1)
            self.assertEqual(store.clear_knowledge(), 1)
            self.assertEqual(store.list_knowledge(), [])

    def test_search_update_and_tags_for_knowledge_base(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = KnowledgeStore(Path(temp_dir) / "knowledge.jsonl")
            record = store.save_verified_knowledge(
                title="毛利率",
                question="毛利率怎么算？",
                conclusion="毛利额 / 收入净额。",
                scope="财务指标",
                verification="财务报表核验",
                evidence_refs=["dm.dm_fina_sales_profit_sum"],
                metadata={
                    "type": "metric_definition",
                    "status": "pending",
                    "owner": "财务 BI 组",
                    "tags": ["财务指标", "报表口径"],
                },
            )

            matched = store.search_knowledge(query="收入净额", item_type="metric_definition", tag="财务指标")
            updated = store.update_knowledge(
                record.id,
                metadata={"status": "approved", "approvals": [{"role": "财务", "status": "approved"}]},
            )
            tags = store.list_tags()

            self.assertEqual([item.id for item in matched], [record.id])
            self.assertIsNotNone(updated)
            self.assertEqual(updated.metadata["status"], "approved")
            self.assertEqual({tag["name"] for tag in tags}, {"财务指标", "报表口径"})


if __name__ == "__main__":
    unittest.main()
