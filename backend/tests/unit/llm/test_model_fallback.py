"""One provider failing (a key Google refuses from an EU region, an unfunded account) must not take every agent down,
and the log must say what the provider answered — not just `ModelHTTPError`."""

from pydantic_ai.exceptions import FallbackExceptionGroup, ModelHTTPError
from pydantic_ai.models.fallback import FallbackModel
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.models.openai import OpenAIChatModel

from app.core.settings import Settings
from app.llm.calls import is_transient
from app.llm.runtime import build_model, describe_model_error


def _s(**kw: object) -> Settings:
    return Settings(database_url="postgresql+psycopg://u:p@h/db", _env_file=None, **kw)  # type: ignore[arg-type]


GEMINI = {"llm_model": "google-gla:gemini-2.5-flash", "gemini_api_key": "g-test"}


def test_fallback_models_are_parsed_from_a_comma_separated_env_value() -> None:
    assert _s(llm_fallback_models=" openai:gpt-4.1-mini , groq:llama-3.3-70b-versatile ,").llm_fallback_models == [
        "openai:gpt-4.1-mini",
        "groq:llama-3.3-70b-versatile",
    ]
    assert _s(llm_fallback_models="").llm_fallback_models == []


def test_no_fallbacks_keeps_the_single_model() -> None:
    assert isinstance(build_model(_s(**GEMINI), "concierge"), GoogleModel)


def test_fallbacks_wrap_the_primary_in_a_fallback_model() -> None:
    model = build_model(_s(**GEMINI, llm_fallback_models="openai:gpt-4.1-mini", openai_api_key="sk-test"), "concierge")
    assert isinstance(model, FallbackModel)
    assert [type(m) for m in model.models] == [GoogleModel, OpenAIChatModel]


def test_a_fallback_without_its_key_is_left_out() -> None:
    settings = _s(
        **GEMINI,
        llm_fallback_models="openai:gpt-4.1-mini,groq:llama-3.3-70b-versatile",
        openai_api_key=None,  # independent of a key exported in the developer's shell
        groq_api_key=None,
    )
    model = build_model(settings, "x")
    assert isinstance(model, GoogleModel)


def test_the_fake_model_never_gets_fallbacks() -> None:
    model = build_model(_s(llm_fallback_models="openai:gpt-4.1-mini", openai_api_key="sk-test"), "understanding")
    assert not isinstance(model, FallbackModel)


def test_a_group_is_transient_when_any_provider_failure_is() -> None:
    rate_limited = ModelHTTPError(429, "gemini-2.5-flash")
    refused = ModelHTTPError(401, "gpt-4.1-mini")
    assert is_transient(FallbackExceptionGroup("all failed", [refused, rate_limited])) is True
    assert is_transient(FallbackExceptionGroup("all failed", [refused])) is False


def test_the_description_names_status_and_provider_message_without_keys() -> None:
    gemini = ModelHTTPError(
        400,
        "gemini-2.5-flash",
        {"error": {"code": 400, "message": "User location is not supported for the API use.", "status": "x"}},
    )
    openai = ModelHTTPError(401, "gpt-4.1-mini", {"message": "Incorrect API key provided: sk-proj-abc***wxyz."})
    text = describe_model_error(FallbackExceptionGroup("all failed", [gemini, openai]))
    assert "400 gemini-2.5-flash" in text
    assert "User location is not supported" in text
    assert "401 gpt-4.1-mini" in text
    assert "sk-proj" not in text
    assert describe_model_error(ValueError("boom")) == "ValueError"


def test_a_body_without_a_plain_message_logs_the_status_only() -> None:
    """A Groq `tool_use_failed` body carries `failed_generation` (model output restating tenant text): never log it."""
    groq = ModelHTTPError(400, "llama", {"error": {"code": "tool_use_failed", "failed_generation": "tenant text"}})
    listed = ModelHTTPError(400, "gemini", [{"error": {"message": "x"}}])
    assert describe_model_error(groq) == "ModelHTTPError 400 llama"
    assert describe_model_error(listed) == "ModelHTTPError 400 gemini"


def test_gemini_calls_use_the_v1beta_api(monkeypatch: object) -> None:
    """google-genai 3.x defaults the Developer API to v1, which refuses system instructions and function calling
    (every agent call 400s); agents and embeddings pin v1beta whatever GOOGLE_GENAI_API_VERSION says."""
    from app.llm.embeddings import build_embedder

    model = build_model(_s(**GEMINI), "concierge")
    assert isinstance(model, GoogleModel)
    assert model.client._api_client._http_options.api_version == "v1beta"

    embedder = build_embedder(_s(embedding_model="google-gla:gemini-embedding-001", gemini_api_key="g-test"))
    provider = embedder._embedder.model._provider  # type: ignore[attr-defined]
    assert provider.client._api_client._http_options.api_version == "v1beta"
