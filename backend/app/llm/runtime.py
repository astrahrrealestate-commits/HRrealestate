"""Model factory and agent tracing (Pydantic AI OpenTelemetry spans → Langfuse OTLP endpoint, EU cloud)."""

import base64
import re
from typing import Any

from pydantic_ai import Agent, PromptedOutput
from pydantic_ai.models import Model
from pydantic_ai.models.instrumented import InstrumentationSettings

from app.core.settings import Settings
from app.llm import fakes

_KEY_FIELDS = {"google-gla": "gemini_api_key", "openai": "openai_api_key", "groq": "groq_api_key"}
# Providers echo part of a rejected key ("Incorrect API key provided: sk-proj-abc***wxyz"); never log even that.
_KEY_SHAPES = re.compile(r"(sk-[\w*.-]+|AIza[\w-]+|gsk_[\w*-]+)")


def gemini_provider(api_key: str | None) -> Any:
    """A Gemini Developer API provider pinned to API v1beta. google-genai 3.x defaults to v1, which refuses system
    instructions ("Developer instruction is not enabled") and function calling, so every agent call answered 400."""
    from pydantic_ai.providers.google import GoogleProvider

    class _V1BetaGoogleProvider(GoogleProvider):
        def _build_http_options(self, **kwargs: Any) -> Any:  # the documented hook for subclasses
            return super()._build_http_options(**kwargs).model_copy(update={"api_version": "v1beta"})

    return _V1BetaGoogleProvider(api_key=api_key)


def _key(settings: Settings, provider: str) -> str | None:
    field = _KEY_FIELDS.get(provider)
    secret = getattr(settings, field) if field else None
    return secret.get_secret_value() if secret else None


def _provider_model(settings: Settings, model: str) -> Model | str:
    """One `provider:name` string as a model that takes its key from Settings (environment or .env), not only from
    the process environment; a provider without a key mapping is passed to Pydantic AI as the string."""
    provider, _, name = model.partition(":")
    key = _key(settings, provider)
    if provider == "google-gla":
        from pydantic_ai.models.google import GoogleModel

        return GoogleModel(name, provider=gemini_provider(key))
    if provider in ("openai", "groq"):
        from pydantic_ai.models.openai import OpenAIChatModel
        from pydantic_ai.providers.openai import OpenAIProvider

        base_url = "https://api.groq.com/openai/v1" if provider == "groq" else None
        return OpenAIChatModel(name, provider=OpenAIProvider(base_url=base_url, api_key=key))
    return model


def model_name_for(settings: Settings, agent_name: str) -> str:
    """The model string an agent runs on: `concierge_model` for the concierge when set, else `llm_model`."""
    if agent_name == "concierge" and settings.concierge_model:
        return settings.concierge_model
    return settings.llm_model


def build_model(settings: Settings, agent_name: str) -> Model | str:
    """`fake` → deterministic offline model for this agent. Otherwise the agent's model (`model_name_for`), wrapped in
    a FallbackModel when `llm_fallback_models` names any model whose provider key is set."""
    name = model_name_for(settings, agent_name)
    if name == "fake":
        return fakes.model_for(agent_name)
    primary = _provider_model(settings, name)
    fallbacks = [
        _provider_model(settings, model)
        for model in settings.llm_fallback_models
        if model != name and _key(settings, model.partition(":")[0])
    ]
    if not fallbacks:
        return primary
    from pydantic_ai.models.fallback import FallbackModel

    return FallbackModel(primary, *fallbacks)


def describe_model_error(exc: BaseException) -> str:
    """What a failed model call says, safe for logs: HTTP status, model and the provider's own message (key-shaped
    text scrubbed), for each provider a FallbackModel tried; any other error is its class name only."""
    from pydantic_ai.exceptions import FallbackExceptionGroup, ModelHTTPError

    if isinstance(exc, FallbackExceptionGroup):
        return " | ".join(describe_model_error(inner) for inner in exc.exceptions)
    if isinstance(exc, ModelHTTPError):
        head = f"ModelHTTPError {exc.status_code} {exc.model_name}"
        message = _provider_message(exc.body)
        return f"{head}: {_KEY_SHAPES.sub('[key]', message)[:300]}" if message else head
    return type(exc).__name__


def _provider_message(body: object) -> str | None:
    """Only a plain string `error.message` / `message`: any other body shape can carry model output (Groq's
    `failed_generation` restates tenant text), so it is never logged."""
    if not isinstance(body, dict):
        return None
    inner = body.get("error", body)
    message = inner.get("message") if isinstance(inner, dict) else None
    return message if isinstance(message, str) and message else None


def output_for[T](settings: Settings, output_type: type[T], *, gemini_prompted: bool = False) -> Any:
    """The agent's `output_type`. Gemini rejects a deeply nested schema as a tool ("too many states for serving"); an
    agent flagged `gemini_prompted` gets the schema in its prompt and the JSON validated afterwards instead. Every
    other provider keeps the strict tool schema."""
    if gemini_prompted and settings.llm_model.startswith("google-gla:"):
        return PromptedOutput(output_type)
    return output_type


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
