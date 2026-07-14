from agents import Agent, ModelSettings, OpenAIChatCompletionsModel
from openai import AsyncOpenAI

from app.agents.prompts import ANALYSIS_INSTRUCTIONS
from app.config import Settings


def build_minimax_analysis_agent(settings: Settings) -> Agent:
    """Create a structured-output Agent backed by MiniMax's OpenAI-compatible API."""

    api_key = settings.minimax_api_key
    if api_key is None:
        raise ValueError("MINIMAX_API_KEY is required before constructing the Agent")

    client = AsyncOpenAI(
        api_key=api_key.get_secret_value(),
        base_url=settings.minimax_base_url,
    )
    model = OpenAIChatCompletionsModel(settings.minimax_model, openai_client=client)
    return Agent(
        name="GenBI Analysis Agent",
        instructions=ANALYSIS_INSTRUCTIONS,
        model=model,
        # MiniMax M-series does not support OpenAI JSON-schema response_format.
        # The runner validates the prompted JSON with Pydantic after the SDK call.
        model_settings=ModelSettings(
            temperature=0.1,
            extra_body={"thinking": {"type": "disabled"}},
        ),
    )
