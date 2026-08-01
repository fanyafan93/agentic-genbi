from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from resource_library.database_tools import DatabaseConfig, ReadonlyDatabaseTools
from resource_library.exploration_agent import (
    DATA_EXPLORATION_AGENT_INSTRUCTIONS,
    create_data_exploration_tool_functions,
)
from resource_library.indexer import ResourceIndexer
from resource_library.inspector import inspect_index
from resource_library.knowledge_store import KnowledgeStore
from resource_library.tools import ResourceLibrary


class FakeCursor:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.description = [(key,) for key in rows[0].keys()] if rows else []

    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> None:
        pass

    def fetchall(self) -> list[dict[str, Any]]:
        return self.rows

    def close(self) -> None:
        pass


class FakeConnection:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    def cursor(self) -> FakeCursor:
        return FakeCursor(self.rows)

    def close(self) -> None:
        pass


class ExplorationAgentTest(unittest.TestCase):
    def test_instructions_match_exploration_boundaries(self) -> None:
        self.assertIn("不是直接生成 Artifact", DATA_EXPLORATION_AGENT_INSTRUCTIONS)
        self.assertIn("不是直接生成 Artifact、数据报表、数据集或可复用 Agent", DATA_EXPLORATION_AGENT_INSTRUCTIONS)
        self.assertIn("你只探索知识", DATA_EXPLORATION_AGENT_INSTRUCTIONS)
        self.assertIn("你的固定身份名称是：Agentic GenBI 知识探索 Agent", DATA_EXPLORATION_AGENT_INSTRUCTIONS)
        self.assertIn("对外只能自称“知识探索 Agent”", DATA_EXPLORATION_AGENT_INSTRUCTIONS)
        self.assertIn("禁止自称“数据探索 Agent”", DATA_EXPLORATION_AGENT_INSTRUCTIONS)
        self.assertIn("不使用固定模板", DATA_EXPLORATION_AGENT_INSTRUCTIONS)
        self.assertIn("不是为了直接出统计结果", DATA_EXPLORATION_AGENT_INSTRUCTIONS)
        self.assertIn("不用于替用户产出业务统计结果", DATA_EXPLORATION_AGENT_INSTRUCTIONS)
        self.assertIn("先根据用户问题生成一个简短中文标题", DATA_EXPLORATION_AGENT_INSTRUCTIONS)
        self.assertIn("save_verified_knowledge", DATA_EXPLORATION_AGENT_INSTRUCTIONS)
        self.assertIn("最近 3-6 个月", DATA_EXPLORATION_AGENT_INSTRUCTIONS)
        self.assertIn("不能证明当前口径仍适用", DATA_EXPLORATION_AGENT_INSTRUCTIONS)

    def test_tool_functions_wrap_resource_database_and_knowledge_tools(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            index_path = root / "resources.json"
            summary_path = root / "summaries.json"
            knowledge_path = root / "knowledge.jsonl"
            (root / "首购复购.sql").write_text("select member_id from dm.rebuy_30d;", encoding="utf-8")
            ResourceIndexer(root).write(index_path)
            inspect_index(index_path, summary_path)

            tools = create_data_exploration_tool_functions(
                resource_library=ResourceLibrary(index_path=index_path, summary_path=summary_path),
                db_tools=ReadonlyDatabaseTools(
                    DatabaseConfig(host="x", port=3306, user="u", password="p"),
                    connection=FakeConnection([{"table_schema": "dm", "table_name": "rebuy_30d"}]),
                ),
                knowledge_store=KnowledgeStore(knowledge_path),
            )
            by_name = {tool.__name__: tool for tool in tools}

            search_result = by_name["search_resources"]("复购", limit=3)
            self.assertEqual(search_result["results"][0]["name"], "首购复购.sql")
            self.assertNotIn("select member_id", str(search_result))

            tables = by_name["search_db_tables"]("rebuy", limit=1)
            self.assertEqual(tables["rows"][0]["table_name"], "rebuy_30d")

            knowledge = by_name["save_verified_knowledge"](
                title="首购复购",
                question="首购后 30 天复购率怎么算？",
                conclusion="按会员首购后 30 天再次支付去重。",
                scope="当前测试",
                verification="测试证据",
                evidence_refs=["res_1"],
            )
            self.assertTrue(knowledge["id"].startswith("kn_"))
            self.assertTrue(knowledge_path.exists())

if __name__ == "__main__":
    unittest.main()
