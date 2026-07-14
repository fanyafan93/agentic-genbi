import json

import pytest

from app.config import Settings
from tests.agents.fakes import FakeSdkRunner


def settings_with_key(**overrides: object) -> Settings:
    return Settings(
        app_env="test",
        database_url="mysql+pymysql://readonly_user:readonly-password@localhost:3306/analytics",
        minimax_api_key="test-key",
        **overrides,
    )


def valid_narrative() -> dict[str, object]:
    return {
        "title": "Monthly sales trend",
        "summary": ["Online sales increased in the observed period."],
        "chart": {
            "type": "line",
            "title": "Monthly sales by channel",
            "x_field": "month_start",
            "y_fields": ["sales_amount"],
            "series_field": "channel",
        },
        "assumptions": ["The fixed query result represents the requested scope."],
        "warnings": [],
    }


def test_runner_requires_a_minimax_key_without_calling_the_provider() -> None:
    from app.agents.runner import AgentProviderNotConfigured, MiniMaxAnalysisRunner

    fake_sdk_runner = FakeSdkRunner(result=valid_narrative())
    runner = MiniMaxAnalysisRunner(
        Settings(
            app_env="test",
            database_url="mysql+pymysql://readonly_user:readonly-password@localhost:3306/analytics",
            _env_file=None,
        ),
        agent_factory=lambda _: object(),
        sdk_runner=fake_sdk_runner,
    )

    with pytest.raises(AgentProviderNotConfigured) as error:
        runner.run("How did sales change?", "trusted context")

    assert error.value.code == "PROVIDER_NOT_CONFIGURED"
    assert fake_sdk_runner.calls == []


def test_runner_validates_structured_output_from_the_sdk() -> None:
    from app.agents.runner import MiniMaxAnalysisRunner

    fake_sdk_runner = FakeSdkRunner(result=valid_narrative())
    runner = MiniMaxAnalysisRunner(
        settings_with_key(), agent_factory=lambda _: object(), sdk_runner=fake_sdk_runner
    )

    narrative = runner.run("How did sales change?", "trusted context")

    assert narrative.title == "Monthly sales trend"
    assert narrative.chart is not None
    assert len(fake_sdk_runner.calls) == 1
    assert "trusted context" in fake_sdk_runner.calls[0][1]


def test_runner_rejects_invalid_provider_output() -> None:
    from app.agents.runner import InvalidAgentReport, MiniMaxAnalysisRunner

    runner = MiniMaxAnalysisRunner(
        settings_with_key(),
        agent_factory=lambda _: object(),
        sdk_runner=FakeSdkRunner(result={"title": "Missing required fields"}),
    )

    with pytest.raises(InvalidAgentReport) as error:
        runner.run("How did sales change?", "trusted context")

    assert error.value.code == "INVALID_REPORT"


def test_runner_rejects_non_json_provider_output() -> None:
    from app.agents.runner import InvalidAgentReport, MiniMaxAnalysisRunner

    runner = MiniMaxAnalysisRunner(
        settings_with_key(),
        agent_factory=lambda _: object(),
        sdk_runner=FakeSdkRunner(result="I cannot produce a report right now."),
    )

    with pytest.raises(InvalidAgentReport) as error:
        runner.run("How did sales change?", "trusted context")

    assert error.value.code == "INVALID_REPORT"
    assert "Detail:" in str(error.value)
    assert "JSON" in str(error.value) or "Expecting" in str(error.value)


def test_runner_invalid_report_message_carries_pydantic_detail() -> None:
    from app.agents.runner import InvalidAgentReport, MiniMaxAnalysisRunner

    runner = MiniMaxAnalysisRunner(
        settings_with_key(),
        agent_factory=lambda _: object(),
        sdk_runner=FakeSdkRunner(result={"title": "x", "summary": "not a list"}),
    )

    with pytest.raises(InvalidAgentReport) as error:
        runner.run("How did sales change?", "trusted context")

    message = str(error.value)
    assert "title" in message or "summary" in message
    assert "Pydantic" in message or "Field required" in message or "validation" in message.lower()


def test_runner_validates_json_after_removing_minimax_thinking_content() -> None:
    from app.agents.runner import MiniMaxAnalysisRunner

    runner = MiniMaxAnalysisRunner(
        settings_with_key(),
        agent_factory=lambda _: object(),
        sdk_runner=FakeSdkRunner(
            result="<think>Reason about the data privately.</think>\n```json\n"
            + __import__("json").dumps(valid_narrative())
            + "\n```"
        ),
    )

    narrative = runner.run("How did sales change?", "trusted context")

    assert narrative.title == "Monthly sales trend"


def test_runner_normalizes_minimax_legacy_chart_fields() -> None:
    from app.agents.runner import MiniMaxAnalysisRunner

    runner = MiniMaxAnalysisRunner(
        settings_with_key(),
        agent_factory=lambda _: object(),
        sdk_runner=FakeSdkRunner(
            result=json.dumps(
                {
                    "title": "Monthly sales trend",
                    "summary": ["Sales changed across channels."],
                    "chart": {
                        "type": "line",
                        "x_axis": "month_start",
                        "y_axis": "sales_amount",
                        "series": ["channel"],
                        "data": [{"month_start": "2026-01-01", "sales_amount": 120000}],
                    },
                    "assumptions": [],
                    "warnings": [],
                }
            )
        ),
    )

    narrative = runner.run("How did sales change?", "trusted context")

    assert narrative.chart is not None
    assert narrative.chart.x_field == "month_start"
    assert narrative.chart.y_fields == ["sales_amount"]
    assert narrative.chart.series_field == "channel"


def test_runner_drops_an_unsupported_minimax_chart_variant() -> None:
    from app.agents.runner import MiniMaxAnalysisRunner

    runner = MiniMaxAnalysisRunner(
        settings_with_key(),
        agent_factory=lambda _: object(),
        sdk_runner=FakeSdkRunner(
            result=json.dumps(
                {
                    "title": "Monthly sales trend",
                    "summary": ["Sales changed across channels."],
                    "chart": {
                        "type": "line",
                        "x": "month_start",
                        "series": [{"name": "online", "values": [{"sales_amount": 120000}]}],
                    },
                    "assumptions": [],
                    "warnings": [],
                }
            )
        ),
    )

    narrative = runner.run("How did sales change?", "trusted context")

    assert narrative.chart is None


def test_runner_sanitizes_provider_errors() -> None:
    from app.agents.runner import AgentProviderError, MiniMaxAnalysisRunner

    runner = MiniMaxAnalysisRunner(
        settings_with_key(),
        agent_factory=lambda _: object(),
        sdk_runner=FakeSdkRunner(error=RuntimeError("credential=test-key")),
    )

    with pytest.raises(AgentProviderError) as error:
        runner.run("How did sales change?", "trusted context")

    assert error.value.code == "PROVIDER_ERROR"
    assert str(error.value) == "Analysis provider request failed."
