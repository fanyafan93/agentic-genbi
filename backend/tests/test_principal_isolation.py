"""Multi-user isolation regression tests for the GenBI analysis API.

These tests lock down the security contract described in
``docs/plans/current.md``:

*   No session / no principal header ⇒ ``401 authentication_required``.
*   A user cannot read, list, delete, rename, share, or reopen another
    user's Thread / Turn / Asset / Interactive Report.
*   Frontend-supplied ``ownerId``, ``userId``, ``owner_id`` query
    parameters are ignored; the backend derives identity from the
    authenticated principal.
*   ``isAdmin`` cannot be claimed from the client.

The tests deliberately do not depend on a real Auth.js session because
unit tests run without Postgres. The ``auth_test_client`` helper plus the
``X-Genbi-Test-Principal`` dev-bypass header replace the session lookup
so we can pin the boundary layer in isolation.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from backend.analysis.asset_store import AnalysisAssetStore
from backend.analysis.interactive_report_store import InteractiveReportStore
from backend.api.principal import enable_dev_principal_bypass
from backend.harness.codex_sdk_runner import CodexSdkAnalysisRuntime
from backend.harness.thread_store import ThreadStore
from backend.tests.auth_test_client import anonymous_client, auth_client, build_test_app


def _runtime() -> CodexSdkAnalysisRuntime:
    return CodexSdkAnalysisRuntime.disabled()


def _set_up_bypass(test: unittest.TestCase) -> None:
    enable_dev_principal_bypass(True)
    os.environ["GENBI_AUTH_DEV_BYPASS"] = "1"
    test.addCleanup(_tear_down_bypass)


def _tear_down_bypass() -> None:
    enable_dev_principal_bypass(False)
    os.environ.pop("GENBI_AUTH_DEV_BYPASS", None)


def _report_payload(report_id: str = "report_isolation_1") -> dict:
    return {
        "id": report_id,
        "title": "Isolation Report",
        "subtitle": "Tenant isolation check",
        "artifactType": "interactive_report",
        "renderer": "puck",
        "source": {"threadId": "thread_isolation", "turnId": "turn_isolation"},
        "document": {"content": [], "root": {"props": {}}},
        "filters": [],
        "queries": {},
        "chartSpecs": {},
        "gridSpecs": {},
        "datasets": {"channel_sales": {"rows": [{"channel": "Direct", "sales": 1}]}},
        "dataUpdatedAt": "2026-08-04T09:00:00+08:00",
    }


class PrincipalIsolationTest(unittest.TestCase):
    def test_anonymous_request_is_rejected_with_401(self) -> None:
        _set_up_bypass(self)
        with tempfile.TemporaryDirectory() as temp_dir:
            app = build_test_app(
                analysis_runtime=_runtime(),
                interactive_report_store=InteractiveReportStore(Path(temp_dir) / "interactive-reports.json"),
                thread_store=ThreadStore(Path(temp_dir) / "thread-store.jsonl"),
                analysis_asset_store=AnalysisAssetStore(Path(temp_dir) / "analysis-assets.jsonl"),
            )
            anon = anonymous_client(app)
            self.assertEqual(anon.get("/api/analysis/threads").status_code, 401)
            self.assertEqual(anon.post("/api/analysis/threads", json={"title": "x"}).status_code, 401)
            self.assertEqual(anon.get("/api/analysis/reports").status_code, 401)
            self.assertEqual(anon.post("/api/analysis/reports", json=_report_payload()).status_code, 401)
            self.assertEqual(anon.get("/api/analysis/report-center").status_code, 401)
            self.assertEqual(anon.get("/api/analysis/assets").status_code, 401)

    def test_list_threads_returns_only_current_users_threads(self) -> None:
        _set_up_bypass(self)
        with tempfile.TemporaryDirectory() as temp_dir:
            thread_store = ThreadStore(Path(temp_dir) / "thread-store.jsonl")
            app = build_test_app(analysis_runtime=_runtime(), thread_store=thread_store)

            with auth_client(app, user_id="alice") as alice:
                created = alice.post("/api/analysis/threads", json={"title": "Alice Analysis"})
                self.assertEqual(created.status_code, 200)
                thread_id = created.json()["thread"]["id"]
                listed = alice.get("/api/analysis/threads")
                ids_alice = [item["id"] for item in listed.json()["threads"]]
                self.assertIn(thread_id, ids_alice)

            with auth_client(app, user_id="bob") as bob:
                # Bob's listing must not include Alice's thread, even though he
                # is talking to the same backend with the same ThreadStore.
                self.assertNotIn(thread_id, [item["id"] for item in bob.get("/api/analysis/threads").json()["threads"]])

                # Bob cannot fetch Alice's thread detail.
                self.assertEqual(bob.get(f"/api/analysis/threads/{thread_id}").status_code, 404)

                # Bob cannot delete Alice's thread; the API reports "not found"
                # instead of leaking that the thread exists.
                self.assertEqual(bob.delete(f"/api/analysis/threads/{thread_id}").status_code, 404)

    def test_report_center_and_reports_are_scoped_to_owner(self) -> None:
        _set_up_bypass(self)
        with tempfile.TemporaryDirectory() as temp_dir:
            report_store = InteractiveReportStore(Path(temp_dir) / "interactive-reports.json")
            app = build_test_app(analysis_runtime=_runtime(), interactive_report_store=report_store)

            with auth_client(app, user_id="alice") as alice:
                alice.post("/api/analysis/reports", json=_report_payload("report_alice"))
                # Even if Alice tries to send someone else's ownerId in the
                # body, the server must overwrite it with the principal.
                alice.post(
                    "/api/analysis/reports",
                    json={**_report_payload("report_alice_with_attacker_owner"), "ownerId": "mallory"},
                )

            with auth_client(app, user_id="bob") as bob:
                bob_center = bob.get("/api/analysis/report-center").json()
                self.assertEqual(bob_center["mine"], [])
                self.assertEqual(bob_center["sharedWithMe"], [])

                # Bob cannot read Alice's report by id.
                self.assertEqual(bob.get("/api/analysis/reports/report_alice").status_code, 404)
                # Bob cannot delete, rename, or share Alice's report either.
                self.assertEqual(bob.delete("/api/analysis/reports/report_alice").status_code, 404)
                self.assertEqual(
                    bob.patch("/api/analysis/reports/report_alice", json={"title": "stolen"}).status_code,
                    404,
                )
                self.assertEqual(
                    bob.post(
                        "/api/analysis/reports/report_alice/shares",
                        json={"recipientUserId": "bob", "permission": "view_and_reuse"},
                    ).status_code,
                    404,
                )

            with auth_client(app, user_id="alice") as alice:
                owner_center = alice.get("/api/analysis/report-center").json()
                self.assertEqual(len(owner_center["mine"]), 2)
                # All reports saved by Alice must carry her user id, regardless
                # of what the request body claimed.
                self.assertTrue(
                    all(item["report"]["ownerId"] == "alice" for item in owner_center["mine"]),
                )

    def test_query_owner_id_does_not_bypass_session_filter(self) -> None:
        _set_up_bypass(self)
        with tempfile.TemporaryDirectory() as temp_dir:
            report_store = InteractiveReportStore(Path(temp_dir) / "interactive-reports.json")
            app = build_test_app(analysis_runtime=_runtime(), interactive_report_store=report_store)

            with auth_client(app, user_id="alice") as alice:
                alice.post("/api/analysis/reports", json=_report_payload("report_alice"))

            with auth_client(app, user_id="bob") as bob:
                # Even supplying ``owner_id=alice`` in the query string must
                # not let Bob read Alice's report. The server uses the principal
                # as the source of truth, never the query string.
                response = bob.get("/api/analysis/reports", params={"owner_id": "alice"})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["reports"], [])

    def test_assets_endpoint_requires_authenticated_principal(self) -> None:
        _set_up_bypass(self)
        with tempfile.TemporaryDirectory() as temp_dir:
            asset_store = AnalysisAssetStore(Path(temp_dir) / "analysis-assets.jsonl")
            app = build_test_app(
                analysis_runtime=_runtime(),
                analysis_asset_store=asset_store,
            )

            with auth_client(app, user_id="alice") as alice:
                save = alice.post(
                    "/api/analysis/assets",
                    json={
                        "assetId": "asset_alice",
                        "artifactVersionId": "av_alice_v1",
                        "sourceTaskId": "task_alice",
                        "sourceTaskTitle": "Alice task",
                        "sourceConversationId": "conv_alice",
                        "assetType": "report",
                        "title": "alice.html",
                        "description": "alice asset",
                        "visibility": "team",
                        "status": "saved",
                        "latestVersion": "v1-draft",
                        "reopenContext": {
                            "sourceTaskId": "task_alice",
                            "sourceConversationId": "conv_alice",
                            "continuationPrompt": "continue",
                        },
                    },
                )
                self.assertEqual(save.status_code, 200)
                self.assertEqual(
                    save.json()["asset"]["metadata"].get("owner_user_id"),
                    "alice",
                )

            with auth_client(app, user_id="bob") as bob:
                self.assertEqual(bob.get("/api/analysis/assets/asset_alice").status_code, 404)
                self.assertEqual(
                    bob.post("/api/analysis/assets/asset_alice/reopen").status_code, 404
                )

    def test_admin_role_cannot_be_claimed_from_client(self) -> None:
        _set_up_bypass(self)
        with tempfile.TemporaryDirectory() as temp_dir:
            report_store = InteractiveReportStore(Path(temp_dir) / "interactive-reports.json")
            app = build_test_app(analysis_runtime=_runtime(), interactive_report_store=report_store)

            # The principal payload carries a role that is NOT "admin".
            with auth_client(app, user_id="eve", role="user") as eve:
                created = eve.post("/api/analysis/reports", json=_report_payload("report_eve"))
                self.assertEqual(created.status_code, 200)

            # Even if Mallory forges an "admin" role, the bypass is dev-only
            # and never grants admin privileges — every cross-user action must
            # still get a 404.
            with auth_client(app, user_id="mallory", role="admin") as mallory:
                cross = mallory.get("/api/analysis/reports/report_eve")
                self.assertEqual(cross.status_code, 404)
                cross_list = mallory.get("/api/analysis/reports")
                self.assertEqual(cross_list.status_code, 200)
                self.assertEqual(cross_list.json()["reports"], [])


if __name__ == "__main__":
    unittest.main()
