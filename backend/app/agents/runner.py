from collections.abc import Callable
import json
import re
from typing import Any

from agents import RunConfig, Runner
from pydantic import ValidationError

from app.agents.analysis_agent import build_minimax_analysis_agent
from app.agents.prompts import build_analysis_prompt
from app.config import Settings
from app.schemas.analysis import ReportNarrative


class AgentRunError(Exception):
    code: str


class AgentProviderNotConfigured(AgentRunError):
    code = "PROVIDER_NOT_CONFIGURED"

    def __init__(self) -> None:
        super().__init__("Analysis provider is not configured.")


class AgentProviderError(AgentRunError):
    code = "PROVIDER_ERROR"

    def __init__(self) -> None:
        super().__init__("Analysis provider request failed.")


class InvalidAgentReport(AgentRunError):
    code = "INVALID_REPORT"

    def __init__(self) -> None:
        super().__init__("Analysis provider returned an invalid report.")


SdkRunner = Callable[[object, str], Any]
AgentFactory = Callable[[Settings], object]


class MiniMaxAnalysisRunner:
    """Validate MiniMax output without exposing provider details to task consumers."""

    def __init__(
        self,
        settings: Settings,
        agent_factory: AgentFactory = build_minimax_analysis_agent,
        sdk_runner: SdkRunner | None = None,
    ) -> None:
        self._settings = settings
        self._agent_factory = agent_factory
        self._sdk_runner = sdk_runner or _run_with_agents_sdk

    def run(self, question: str, trusted_context: str) -> ReportNarrative:
        if self._settings.minimax_api_key is None:
            raise AgentProviderNotConfigured

        try:
            agent = self._agent_factory(self._settings)
            output = self._sdk_runner(agent, build_analysis_prompt(question, trusted_context))
        except AgentRunError:
            raise
        except Exception as error:
            raise AgentProviderError from error

        try:
            return validate_narrative_output(output)
        except ValidationError as error:
            raise InvalidAgentReport from error


def _run_with_agents_sdk(agent: object, prompt: str) -> Any:
    result = Runner.run_sync(
        agent,  # type: ignore[arg-type]
        prompt,
        run_config=RunConfig(tracing_disabled=True),
    )
    return result.final_output


def validate_narrative_output(output: Any) -> ReportNarrative:
    if isinstance(output, str):
        output = json.loads(_extract_json(output))
    return ReportNarrative.model_validate(_normalize_legacy_chart(output))


def _normalize_legacy_chart(output: Any) -> Any:
    """Adapt MiniMax's common chart variant to the server-owned report contract."""

    if not isinstance(output, dict) or not isinstance(output.get("chart"), dict):
        return output

    chart = output["chart"]
    if "x_axis" not in chart or "y_axis" not in chart:
        required_fields = {"type", "title", "x_field", "y_fields"}
        return output if required_fields.issubset(chart) else {**output, "chart": None}

    y_axis = chart["y_axis"]
    y_fields = y_axis if isinstance(y_axis, list) else [y_axis]
    series = chart.get("series")
    series_field = series[0] if isinstance(series, list) and len(series) == 1 else series
    normalized_chart = {
        "type": chart.get("type"),
        "title": chart.get("title", output.get("title")),
        "x_field": chart["x_axis"],
        "y_fields": y_fields,
        "series_field": series_field,
    }
    return {**output, "chart": normalized_chart}


def _extract_json(output: str) -> str:
    without_thinking = re.sub(r"<think>.*?</think>", "", output, flags=re.DOTALL).strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", without_thinking, flags=re.DOTALL)
    return fenced.group(1) if fenced else without_thinking
