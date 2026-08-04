"""End-to-end contract tests for the strict ReportArtifact saving
pipeline. The contract:

  * Validation is mandatory; an invalid artifact MUST produce
    ``genbi/artifact/failed`` and MUST NOT emit
    ``genbi/artifact/created``.
  * Persistence failure MUST surface as
    ``genbi/artifact/failed`` with a precise error code, not as
    ``created`` with a missing version.
  * The projection layer always injects source identity; agent
    supplied ``codex_*_pending`` or ``source.*`` is rejected.

These tests exercise ``_interactive_report_artifact_event`` directly
so we don't have to spin up a full Codex stream.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from backend.analysis.interactive_report_store import InteractiveReportStore, InteractiveReportVersionConflict
from backend.harness.codex_sdk_runner import CodexSdkAnalysisRuntime
from backend.harness.events import AgentEvent
from backend.analysis.asset_store import AnalysisAssetStore

import backend.api.analysis_api as analysis_api
from backend.tests.auth_test_client import build_test_app


def _valid_artifact() -> dict:
    return {
        "id": "report_strict",
        "title": "Channel sales",
        "subtitle": "Top channels",
        "artifactType": "interactive_report",
        "renderer": "puck",
        "ownerId": "user_strict",
        "document": {"root": {"props": {"title": "Channel sales"}}, "content": []},
        "filters": [],
        "queries": {"q1": {"datasetId": "d1", "filterBindings": []}},
        "datasets": {"d1": {"rows": [{"channel": "A", "sales": 1}]}},
        "chartSpecs": {
            "c1": {
                "id": "c1",
                "datasetId": "d1",
                "type": "bar",
                "xField": "channel",
                "title": "Sales by channel",
                "series": [{"field": "sales", "label": "Sales", "format": "currency"}],
            },
        },
        "gridSpecs": {
            "g1": {
                "id": "g1",
                "datasetId": "d1",
                "columns": [{"field": "channel", "label": "Channel"}],
                "pageSize": 10,
            },
        },
    }


def _mcp_item_event(artifact: dict | None, *, with_mcp_result: bool = True) -> AgentEvent:
    payload: dict = {
        "eventSource": "codex",
        "codex_item_type": "mcpToolCall",
        "codex_item_id": "codex_item_strict",
        "mcp_server": "GenBI_report",
        "mcp_tool": "create_interactive_report",
        "mcp_status": "completed",
    }
    if with_mcp_result:
        payload["mcp_result"] = {"interactive_report": artifact} if artifact is not None else {"interactive_report": None}
    else:
        payload["mcp_arguments"] = {"title": "fallback", "rows": []}
    return AgentEvent(type="item/completed", turn_id="turn_strict", payload=payload)


class ArtifactStrictSaveContractTest(unittest.TestCase):
    def test_valid_artifact_emits_created_with_injected_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            report_store = InteractiveReportStore(Path(temp_dir) / "reports.json")
            event = _mcp_item_event(_valid_artifact())
            artifact = analysis_api._interactive_report_artifact_event(
                event,
                thread_id="thread_strict",
                turn_id="turn_strict",
                interactive_report_store=report_store,
            )
            self.assertIsNotNone(artifact)
            assert artifact is not None
            self.assertEqual(artifact.type, "genbi/artifact/created")
            self.assertEqual(artifact.payload["source"]["threadId"], "thread_strict")
            self.assertEqual(artifact.payload["source"]["turnId"], "turn_strict")
            self.assertIn("version", artifact.payload)
            self.assertIsInstance(artifact.payload["version"], int)

    def test_invalid_artifact_emits_failed_not_created(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            report_store = InteractiveReportStore(Path(temp_dir) / "reports.json")
            bad = _valid_artifact()
            bad["chartSpecs"]["c1"]["series"] = [{"field": "missing", "label": "Sales"}]
            event = _mcp_item_event(bad)
            artifact = analysis_api._interactive_report_artifact_event(
                event,
                thread_id="thread_strict",
                turn_id="turn_strict",
                interactive_report_store=report_store,
            )
            self.assertIsNotNone(artifact)
            assert artifact is not None
            self.assertEqual(artifact.type, "genbi/artifact/failed")
            self.assertEqual(artifact.payload["status"], "validation_failed")
            self.assertEqual(artifact.payload["error"], "report_artifact_invalid")
            # No version is attached to a failed event.
            self.assertNotIn("version", artifact.payload)
            # The store MUST NOT have been touched.
            self.assertEqual(report_store.list_reports(limit=10), [])

    def test_missing_artifact_emits_failed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            report_store = InteractiveReportStore(Path(temp_dir) / "reports.json")
            event = _mcp_item_event(None)
            artifact = analysis_api._interactive_report_artifact_event(
                event,
                thread_id="thread_strict",
                turn_id="turn_strict",
                interactive_report_store=report_store,
            )
            self.assertIsNotNone(artifact)
            assert artifact is not None
            self.assertEqual(artifact.type, "genbi/artifact/failed")
            self.assertEqual(artifact.payload["status"], "missing_artifact")
            self.assertEqual(report_store.list_reports(limit=10), [])

    def test_save_failure_emits_failed_not_silent_silenced(self) -> None:
        # A store that always raises InteractiveReportVersionConflict
        # simulates the "version conflict on save" path. The
        # previous code swallowed the exception and emitted a
        # ``created`` event with a missing version number. The new
        # contract surfaces the failure explicitly.
        class _AlwaysConflictStore:
            def save_report(self, payload):  # type: ignore[no-untyped-def]
                raise InteractiveReportVersionConflict("interactive_report_version_conflict")

        event = _mcp_item_event(_valid_artifact())
        artifact = analysis_api._interactive_report_artifact_event(
            event,
            thread_id="thread_strict",
            turn_id="turn_strict",
            interactive_report_store=_AlwaysConflictStore(),
        )
        self.assertIsNotNone(artifact)
        assert artifact is not None
        self.assertEqual(artifact.type, "genbi/artifact/failed")
        self.assertEqual(artifact.payload["status"], "version_conflict")
        self.assertEqual(artifact.payload["error"], "interactive_report_version_conflict")

    def test_value_error_on_save_emits_failed(self) -> None:
        class _AlwaysValueErrorStore:
            def save_report(self, payload):  # type: ignore[no-untyped-def]
                raise ValueError("interactive_report_invalid_payload")

        event = _mcp_item_event(_valid_artifact())
        artifact = analysis_api._interactive_report_artifact_event(
            event,
            thread_id="thread_strict",
            turn_id="turn_strict",
            interactive_report_store=_AlwaysValueErrorStore(),
        )
        self.assertIsNotNone(artifact)
        assert artifact is not None
        self.assertEqual(artifact.type, "genbi/artifact/failed")
        self.assertEqual(artifact.payload["status"], "save_failed")
        self.assertEqual(artifact.payload["error"], "interactive_report_save_failed")
        self.assertIn("interactive_report_invalid_payload", artifact.payload["detail"])

    def test_missing_store_emits_failed_not_silent_silenced(self) -> None:
        # The "interactive_report_store is None" branch is a hard
        # configuration error; we refuse to project the artifact
        # at all and surface ``save_unavailable`` instead.
        event = _mcp_item_event(_valid_artifact())
        artifact = analysis_api._interactive_report_artifact_event(
            event,
            thread_id="thread_strict",
            turn_id="turn_strict",
            interactive_report_store=None,
        )
        self.assertIsNotNone(artifact)
        assert artifact is not None
        self.assertEqual(artifact.type, "genbi/artifact/failed")
        self.assertEqual(artifact.payload["status"], "save_unavailable")
        self.assertEqual(artifact.payload["error"], "interactive_report_store_unavailable")

    def test_normalize_no_longer_rewrites_fields(self) -> None:
        # Belt-and-suspenders: the previous "best fit" xField /
        # series-field / grid-column rewriting is gone, so feeding
        # the validator an artifact whose fields do not match the
        # dataset yields a clean ``missing_field`` error.
        from backend.analysis.report_artifact import validate_report_artifact

        bad = _valid_artifact()
        bad["chartSpecs"]["c1"]["xField"] = "channel"
        bad["chartSpecs"]["c1"]["series"] = [{"field": "sales_amt", "label": "Sales"}]
        bad["datasets"]["d1"]["rows"] = [{"vchannel_name": "A", "sales": 1}]
        issues = validate_report_artifact(bad)
        paths = {issue.path for issue in issues}
        # The literal ``channel`` / ``sales_amt`` / ``channel`` are all
        # reported as ``missing_field`` because the previous
        # auto-rewrite to ``vchannel_name`` / ``sales_amt`` /
        # ``vchannel_name`` is gone. The validator no longer
        # "guesses" the closest match.
        self.assertIn("chartSpecs.c1.series.0.field", paths)
        self.assertIn("chartSpecs.c1.xField", paths)
        self.assertIn("gridSpecs.g1.columns.0.field", paths)
        for issue in issues:
            self.assertEqual(issue.code, "missing_field")


if __name__ == "__main__":
    unittest.main()
