"""Encoding contract: every read must return text verbatim. The
previous implementation ran latin1 / mojibake / question-mark
heuristics on every read. That hid upstream encoding bugs and
let corrupted records look ``fine``. The contract now is: every
text field round-trips as UTF-8 bytes; corruption is a data
migration concern, not something the API silently rewrites.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from backend.analysis.interactive_report_store import InteractiveReportStore
from backend.api.principal import Principal
from backend.harness.codex_sdk_runner import CodexSdkAnalysisRuntime
from backend.harness.thread_store import ThreadStore
from backend.tests.auth_test_client import build_test_app
from backend.tests.auth_test_client import auth_client


class TextEncodingContractTest(unittest.TestCase):
    def test_thread_question_round_trips_verbatim(self) -> None:
        # A question containing a single ``?`` is preserved; the
        # previous "three-or-more ``?`` -> drop" heuristic is gone.
        with tempfile.TemporaryDirectory() as temp_dir:
            thread_store = ThreadStore(Path(temp_dir) / "thread.jsonl")
            app = build_test_app(
                analysis_runtime=CodexSdkAnalysisRuntime.disabled(),
                thread_store=thread_store,
            )

            with auth_client(app) as client:
                # ``?`` is a single replacement char, not a mojibake marker.
                # The previous heuristic dropped strings with three or
                # more ``?``; we now round-trip the bytes verbatim.
                response = client.post(
                    "/api/analysis/threads/turns",
                    json={"question": "?? GMV ???????????????"},
                )
                self.assertEqual(response.status_code, 200)
                thread_id = response.json()["thread_id"]
                detail = client.get(f"/api/analysis/threads/{thread_id}")
                self.assertEqual(
                    detail.json()["turns"][0]["question"],
                    "?? GMV ???????????????",
                )
                listed = client.get("/api/analysis/threads")
                self.assertEqual(
                    listed.json()["threads"][0]["latestQuestion"],
                    "?? GMV ???????????????",
                )

    def test_thread_question_round_trips_mojibake(self) -> None:
        # The thread API must NOT latin1-redecode the question; if
        # the question is mojibake in storage, the operator sees
        # the mojibake and migrates it. The previous behavior
        # silently turned ``Ã©Ã©Ã©`` into ``ééé``.
        with tempfile.TemporaryDirectory() as temp_dir:
            thread_store = ThreadStore(Path(temp_dir) / "thread.jsonl")
            app = build_test_app(
                analysis_runtime=CodexSdkAnalysisRuntime.disabled(),
                thread_store=thread_store,
            )

            with auth_client(app) as client:
                mangled = "Ã©Ã©Ã©"  # the kind of bytes that used to be silently re-decoded
                response = client.post(
                    "/api/analysis/threads/turns",
                    json={"question": mangled},
                )
                self.assertEqual(response.status_code, 200)
                thread_id = response.json()["thread_id"]
                detail = client.get(f"/api/analysis/threads/{thread_id}")
                self.assertEqual(
                    detail.json()["turns"][0]["question"],
                    mangled,
                )


if __name__ == "__main__":
    unittest.main()
