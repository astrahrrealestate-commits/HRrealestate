"""Model factory and agent tracing (Pydantic AI OpenTelemetry spans → Langfuse OTLP endpoint, EU cloud)."""

import base64

from pydantic_ai import Agent
from pydantic_ai.models import Model
from pydantic_ai.models.instrumented import InstrumentationSettings

from app.core.settings import Settings
from app.llm import fakes


def build_model(settings: Settings, agent_name: str) -> Model | str:
    """`fake` → deterministic offline model for this agent. OpenAI and Gemini models get their key from Settings
    (environment or .env), not only from the process environment; any other string is passed to Pydantic AI."""
    if settings.llm_model == "fake":
        return fakes.model_for(agent_name)
    provider, _, name = settings.llm_model.partition(":")
    if provider == "google-gla":
        from pydantic_ai.models.google import GoogleModel
        from pydantic_ai.providers.google import GoogleProvider

        key = settings.gemini_api_key.get_secret_value() if settings.gemini_api_key else None
        return GoogleModel(name, provider=GoogleProvider(api_key=key))
    if provider == "openai":
        from pydantic_ai.models.openai import OpenAIChatModel
        from pydantic_ai.providers.openai import OpenAIProvider

        key = settings.openai_api_key.get_secret_value() if settings.openai_api_key else None
        return OpenAIChatModel(name, provider=OpenAIProvider(api_key=key))
    if provider == "groq":
        from pydantic_ai.models.openai import OpenAIChatModel
        from pydantic_ai.providers.openai import OpenAIProvider

        key = settings.groq_api_key.get_secret_value() if settings.groq_api_key else None
        return OpenAIChatModel(name, provider=OpenAIProvider(base_url="https://api.groq.com/openai/v1", api_key=key))
    return settings.llm_model


def instrument_agents(settings: Settings) -> bool:
    """Send every agent run to Langfuse when its keys are configured (no-op otherwise). Returns whether it did."""
    if not (settings.langfuse_host and settings.langfuse_public_key and settings.langfuse_secret_key):
        return False
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    secret = settings.langfuse_secret_key.get_secret_value()
    token = base64.b64encode(f"{settings.langfuse_public_key}:{secret}".encode()).decode()
    exporter = OTLPSpanExporter(
        endpoint=f"{settings.langfuse_host.rstrip('/')}/api/public/otel/v1/traces",
        headers={"Authorization": f"Basic {token}"},
    )
    provider = TracerProvider()
    provider.add_span_processor(BatchSpanProcessor(exporter))
    Agent.instrument_all(InstrumentationSettings(tracer_provider=provider))
    return True
