from collections.abc import Callable
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
            return _validate_narrative_output(output)
        except ValidationError as error:
            raise InvalidAgentReport from error


def _run_with_agents_sdk(agent: object, prompt: str) -> Any:
    result = Runner.run_sync(
        agent,  # type: ignore[arg-type]
        prompt,
        run_config=RunConfig(tracing_disabled=True),
    )
    return result.final_output


def _validate_narrative_output(output: Any) -> ReportNarrative:
    if isinstance(output, str):
        return ReportNarrative.model_validate_json(_extract_json(output))
    return ReportNarrative.model_validate(output)


def _extract_json(output: str) -> str:
    without_thinking = re.sub(r"<think>.*?</think>", "", output, flags=re.DOTALL).strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", without_thinking, flags=re.DOTALL)
    return fenced.group(1) if fenced else without_thinking
