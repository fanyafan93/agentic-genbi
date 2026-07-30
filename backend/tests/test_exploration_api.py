from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from backend.api.exploration_api import create_app
from backend.exploration.run_event_store import RunEventStore
from backend.exploration.run_service import ExplorationRunService
from backend.exploration.run_trace_store import RunTraceStore
from backend.resource_library.indexer import ResourceIndexer
from backend.resource_library.inspector import inspect_index
from backend.resource_library.tools import ResourceLibrary


class ExplorationApiTest(unittest.TestCase):
    def test_resource_search_and_inspect_api(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            index_path = root / "resources.json"
            summary_path = root / "summaries.json"
            (root / "复购分析.sql").write_text("select member_id from dm.rebuy_30d;", encoding="utf-8")
            index = ResourceIndexer(root).write(index_path)
            inspect_index(index_path, summary_path)
            app = create_app(
                ExplorationRunService(resource_library=ResourceLibrary(index_path=index_path, summary_path=summary_path))
            )
            client = TestClient(app)

            search = client.get("/api/resources/search", params={"q": "复购"})
            status = client.get("/api/resources/status")
            detail = client.get(f"/api/resources/{index.resources[0].id}")
            excerpt = client.get(
                f"/api/resources/{index.resources[0].id}/excerpt",
                params={"section": "match", "q": "dm.rebuy", "max_lines": 5},
            )

            self.assertEqual(search.status_code, 200)
            self.assertEqual(search.json()["results"][0]["name"], "复购分析.sql")
            self.assertEqual(status.status_code, 200)
            self.assertEqual(status.json()["resource_count"], 1)
            self.assertEqual(detail.status_code, 200)
            self.assertEqual(detail.json()["resource_id"], index.resources[0].id)
            self.assertEqual(excerpt.status_code, 200)
            self.assertIn("dm.rebuy_30d", excerpt.json()["text"])
            self.assertLessEqual(excerpt.json()["end_line"] - excerpt.json()["start_line"] + 1, 5)

    def test_reindex_api_refreshes_service_resource_library(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "库存周转.sql").write_text("select sku_id from dm.inventory_turnover;", encoding="utf-8")
            cwd = Path.cwd()
            try:
                import os

                os.chdir(temp_dir)
                app = create_app(ExplorationRunService())
                client = TestClient(app)

                response = client.post("/api/resources/reindex", json={"root": str(root)})
                search = client.get("/api/resources/search", params={"q": "库存"})
            finally:
                os.chdir(cwd)

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["resource_count"], 1)
            self.assertEqual(search.json()["results"][0]["name"], "库存周转.sql")

    def test_knowledge_list_and_save_api(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cwd = Path.cwd()
            try:
                import os

                os.chdir(temp_dir)
                app = create_app(ExplorationRunService())
                client = TestClient(app)

                saved = client.post(
                    "/api/knowledge",
                    json={
                        "title": "首购复购",
                        "question": "首购后 30 天复购率怎么算？",
                        "conclusion": "按会员去重。",
                        "scope": "测试范围",
                        "verification": "测试验证",
                        "evidence_refs": ["res_1"],
                    },
                )
                record_id = saved.json()["id"]
                listed = client.get("/api/knowledge")
                deleted = client.delete(f"/api/knowledge/{record_id}")
                empty = client.get("/api/knowledge")
            finally:
                os.chdir(cwd)

            self.assertEqual(saved.status_code, 200)
            self.assertEqual(listed.json()["records"][0]["title"], "首购复购")
            self.assertEqual(deleted.status_code, 200)
            self.assertEqual(empty.json()["records"], [])

    def test_clear_knowledge_api(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cwd = Path.cwd()
            try:
                import os

                os.chdir(temp_dir)
                app = create_app(ExplorationRunService())
                client = TestClient(app)
                client.post(
                    "/api/knowledge",
                    json={
                        "title": "清理测试",
                        "question": "q",
                        "conclusion": "c",
                        "scope": "s",
                        "verification": "v",
                        "evidence_refs": ["res_1"],
                    },
                )
                cleared = client.delete("/api/knowledge")
            finally:
                os.chdir(cwd)

            self.assertEqual(cleared.status_code, 200)
            self.assertEqual(cleared.json()["deleted_count"], 1)

    def test_knowledge_base_metadata_search_update_and_tags_api(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cwd = Path.cwd()
            try:
                import os

                os.chdir(temp_dir)
                app = create_app(ExplorationRunService())
                client = TestClient(app)

                saved = client.post(
                    "/api/knowledge",
                    json={
                        "title": "毛利率",
                        "question": "毛利率怎么算？",
                        "conclusion": "毛利额 / 收入净额。",
                        "scope": "财务指标",
                        "verification": "财务报表核验",
                        "evidence_refs": ["dm.dm_fina_sales_profit_sum"],
                        "type": "metric_definition",
                        "status": "pending",
                        "owner": "财务 BI 组",
                        "tags": ["财务指标", "报表口径"],
                        "related_tables": ["dm.dm_fina_sales_profit_sum"],
                        "agent_visible": True,
                    },
                )
                record_id = saved.json()["id"]
                searched = client.get("/api/knowledge", params={"q": "收入净额", "type": "metric_definition", "tag": "财务指标"})
                updated = client.patch(
                    f"/api/knowledge/{record_id}",
                    json={"status": "approved", "approvals": [{"role": "财务", "status": "approved", "approver": "财务负责人"}]},
                )
                tags = client.get("/api/knowledge/tags")
            finally:
                os.chdir(cwd)

            self.assertEqual(saved.status_code, 200)
            self.assertEqual(saved.json()["metadata"]["type"], "metric_definition")
            self.assertEqual(searched.status_code, 200)
            self.assertEqual(searched.json()["records"][0]["id"], record_id)
            self.assertEqual(updated.status_code, 200)
            self.assertEqual(updated.json()["metadata"]["status"], "approved")
            self.assertEqual({item["name"] for item in tags.json()["tags"]}, {"财务指标", "报表口径"})

    def test_run_trace_api_lists_created_run_trace(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            trace_store = RunTraceStore(Path(temp_dir) / "run-traces.jsonl")
            app = create_app(ExplorationRunService(trace_store=trace_store))
            client = TestClient(app)

            created = client.post("/api/explorations/runs", json={"question": "首购后 30 天复购率"})
            traces = client.get("/api/explorations/run-traces")
            detail = client.get(f"/api/explorations/run-traces/{created.json()['run_id']}")

            self.assertEqual(created.status_code, 200)
            self.assertEqual(traces.status_code, 200)
            self.assertEqual(traces.json()["traces"][0]["run_id"], created.json()["run_id"])
            self.assertEqual(detail.status_code, 200)
            self.assertEqual(detail.json()["status"], "failed")
            self.assertEqual(detail.json()["error"], "真实 Agent Runtime 未配置，已停止探索。")

    def test_exploration_runs_api_lists_and_restores_persisted_events(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            trace_store = RunTraceStore(Path(temp_dir) / "run-traces.jsonl")
            event_store = RunEventStore(Path(temp_dir) / "run-events.jsonl")
            app = create_app(ExplorationRunService(trace_store=trace_store, event_store=event_store))
            client = TestClient(app)

            created = client.post("/api/explorations/runs", json={"question": "渠道销售占比"})
            listed = client.get("/api/explorations/runs")
            detail = client.get(f"/api/explorations/runs/{created.json()['run_id']}")
            events = client.get(f"/api/explorations/runs/{created.json()['run_id']}/events")

            self.assertEqual(created.status_code, 200)
            self.assertEqual(listed.status_code, 200)
            self.assertEqual(listed.json()["runs"][0]["run_id"], created.json()["run_id"])
            self.assertEqual(detail.status_code, 200)
            self.assertEqual(detail.json()["events"][0]["type"], "run.created")
            self.assertIn("data:", events.text)
            self.assertIn("run.created", events.text)

    def test_exploration_runs_api_hides_continuation_runs_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            trace_store = RunTraceStore(Path(temp_dir) / "run-traces.jsonl")
            event_store = RunEventStore(Path(temp_dir) / "run-events.jsonl")
            app = create_app(ExplorationRunService(trace_store=trace_store, event_store=event_store))
            client = TestClient(app)

            root = client.post("/api/explorations/runs", json={"question": "毛利率怎么算"})
            child = client.post(
                "/api/explorations/runs",
                json={
                    "question": "收入净额呢",
                    "conversation_id": root.json()["run_id"],
                    "metadata": {"continuation_of": root.json()["run_id"]},
                },
            )
            listed = client.get("/api/explorations/runs")
            listed_all = client.get("/api/explorations/runs", params={"include_continuations": "true"})

            self.assertEqual(child.status_code, 200)
            self.assertEqual([item["run_id"] for item in listed.json()["runs"]], [root.json()["run_id"]])
            self.assertIn(child.json()["run_id"], [item["run_id"] for item in listed_all.json()["runs"]])

    def test_exploration_conversation_api_groups_turn_runs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            trace_store = RunTraceStore(Path(temp_dir) / "run-traces.jsonl")
            event_store = RunEventStore(Path(temp_dir) / "run-events.jsonl")
            app = create_app(ExplorationRunService(trace_store=trace_store, event_store=event_store))
            client = TestClient(app)

            root = client.post("/api/explorations/conversations", json={"question": "库存是怎么取数的"})
            child = client.post(
                "/api/explorations/conversations",
                json={
                    "question": "那仓库范围呢",
                    "conversation_id": root.json()["conversation_id"],
                    "metadata": {"continuation_of": root.json()["conversation_id"]},
                },
            )
            listed = client.get("/api/explorations/conversations")
            detail = client.get(f"/api/explorations/conversations/{root.json()['conversation_id']}")
            run_created_questions = [
                event["payload"]["question"]
                for event in detail.json()["events"]
                if event["type"] == "run.created"
            ]

            self.assertEqual(root.status_code, 200)
            self.assertEqual(child.status_code, 200)
            self.assertTrue(root.json()["conversation_id"].startswith("conv_"))
            self.assertTrue(root.json()["latest_run_id"].startswith("run_"))
            self.assertNotEqual(root.json()["conversation_id"], root.json()["latest_run_id"])
            self.assertEqual(child.json()["conversation_id"], root.json()["conversation_id"])
            self.assertEqual(listed.json()["conversations"][0]["conversation_id"], root.json()["conversation_id"])
            self.assertEqual(listed.json()["conversations"][0]["run_id"], root.json()["latest_run_id"])
            self.assertEqual(run_created_questions, ["库存是怎么取数的", "那仓库范围呢"])

    def test_delete_exploration_run_removes_trace_and_events(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            trace_store = RunTraceStore(Path(temp_dir) / "run-traces.jsonl")
            event_store = RunEventStore(Path(temp_dir) / "run-events.jsonl")
            app = create_app(ExplorationRunService(trace_store=trace_store, event_store=event_store))
            client = TestClient(app)

            created = client.post("/api/explorations/runs", json={"question": "删除测试"})
            run_id = created.json()["run_id"]
            deleted = client.delete(f"/api/explorations/runs/{run_id}")
            listed = client.get("/api/explorations/runs")
            detail = client.get(f"/api/explorations/runs/{run_id}")

            self.assertEqual(deleted.status_code, 200)
            self.assertEqual(deleted.json()["run_id"], run_id)
            self.assertEqual(listed.json()["runs"], [])
            self.assertEqual(detail.status_code, 404)

    def test_exploration_runs_api_filters_by_user_id(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            trace_store = RunTraceStore(Path(temp_dir) / "run-traces.jsonl")
            event_store = RunEventStore(Path(temp_dir) / "run-events.jsonl")
            app = create_app(ExplorationRunService(trace_store=trace_store, event_store=event_store))
            client = TestClient(app)

            user_a = client.post("/api/explorations/runs", json={"question": "A 的探索", "user_id": "user_a"})
            client.post("/api/explorations/runs", json={"question": "B 的探索", "user_id": "user_b"})
            listed = client.get("/api/explorations/runs", params={"user_id": "user_a"})

            self.assertEqual([item["run_id"] for item in listed.json()["runs"]], [user_a.json()["run_id"]])

    def test_runtime_status_api_reports_env_readiness(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "资源库"
            root.mkdir()
            with patch.dict(
                "os.environ",
                {
                    "GENBI_RESOURCE_LIBRARY_ROOT": str(root),
                    "GENBI_DB_HOST": "127.0.0.1",
                    "GENBI_DB_USER": "readonly",
                    "GENBI_DB_PASSWORD": "secret",
                },
                clear=True,
            ):
                app = create_app(ExplorationRunService())
                client = TestClient(app)
                response = client.get("/api/runtime/status")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ready"])
        self.assertEqual({item["name"] for item in payload["checks"]}, {"llm", "mysql", "resource_library", "frontend_api_base", "cost_config"})


if __name__ == "__main__":
    unittest.main()
