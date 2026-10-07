"""Model factory and agent tracing (Pydantic AI OpenTelemetry spans → Langfuse OTLP endpoint, EU cloud)."""

import base64

from pydantic_ai import Agent
from pydantic_ai.models import Model
from pydantic_ai.models.instrumented import InstrumentationSettings

from app.core.settings import Settings
from app.llm import fakes


def build_model(settings: Settings, agent_name: str) -> Model | str:
    """`fake` → deterministic offline model for this agent; anything else is a Pydantic AI model string."""
    if settings.llm_model == "fake":
        return fakes.model_for(agent_name)
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
