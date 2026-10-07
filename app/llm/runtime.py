"""Model factory and agent instrumentation."""

from pydantic_ai.models import Model

from app.core.settings import Settings
from app.llm import fakes


def build_model(settings: Settings, agent_name: str) -> Model | str:
    if settings.llm_model == "fake":
        return fakes.model_for(agent_name)
    return settings.llm_model


def instrument_agents(settings: Settings) -> None:
    """Configures OpenTelemetry instrumentation for Langfuse when keys are present."""
    if not (settings.langfuse_public_key and settings.langfuse_secret_key):
        return
    # Langfuse OTel setup can be initialized here
