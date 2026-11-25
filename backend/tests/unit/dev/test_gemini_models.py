"""`app.dev.gemini_models` (M13 T5): which Gemini models the key can call, and the strongest Pro among them."""

from app.dev.gemini_models import strongest_pro


def test_strongest_pro_picks_the_highest_stable_pro_version() -> None:
    names = [
        "models/gemini-2.5-pro",
        "models/gemini-3.5-pro-preview-06-05",
        "models/gemini-3.5-pro",
        "models/gemini-3.8-flash",
        "models/gemini-embedding-001",
    ]
    assert strongest_pro(names) == "google-gla:gemini-3.5-pro"


def test_strongest_pro_takes_a_preview_only_when_it_is_the_newest() -> None:
    assert strongest_pro(["models/gemini-2.5-pro", "models/gemini-4.0-pro-preview"]) == (
        "google-gla:gemini-4.0-pro-preview"
    )


def test_strongest_pro_is_none_without_a_pro_model() -> None:
    assert strongest_pro(["models/gemini-3.8-flash", "models/gemini-embedding-001"]) is None
