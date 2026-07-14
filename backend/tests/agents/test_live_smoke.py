import os

import pytest

from app.agents.runner import MiniMaxAnalysisRunner
from app.config import get_settings


@pytest.mark.live_agent
def test_minimax_returns_a_valid_structured_narrative() -> None:
    if os.getenv("RUN_LIVE_AGENT_SMOKE_TEST") != "true":
        pytest.skip("Set RUN_LIVE_AGENT_SMOKE_TEST=true to run the MiniMax smoke test.")

    narrative = MiniMaxAnalysisRunner(get_settings()).run(
        "请根据可信数据给出一句简短中文销售趋势结论。",
        """{
          "columns": [
            {"name": "month_start", "data_type": "date"},
            {"name": "channel", "data_type": "varchar"},
            {"name": "sales_amount", "data_type": "decimal"}
          ],
          "rows": [
            {"month_start": "2026-01-01", "channel": "online", "sales_amount": 120000.0}
          ],
          "row_count": 1,
          "truncated": false
        }""",
    )

    assert narrative.title
    assert narrative.summary
