import pytest

from app.llm.fakes import _fake_understanding


@pytest.mark.parametrize(
    ("text", "category", "urgency"),
    [
        ("De kraan lekt een beetje", "maintenance", "high"),
        ("Overstroming in de kelder, het water staat 10 cm hoog!", "maintenance", "emergency"),
        ("Ik ruik een gaslucht in de keuken", "maintenance", "emergency"),
        ("Brand in de meterkast", "maintenance", "emergency"),
        ("Ik wil mijn huurcontract opzeggen", "lease", "normal"),
        ("Wanneer moet ik de huur betalen?", "payment", "normal"),
        ("Hierbij de factuur voor het werk", "contractor_update", "normal"),
    ],
)
def test_fake_triage_is_plausible(text: str, category: str, urgency: str) -> None:
    out = _fake_understanding(f"<message>\n{text}\n</message>")
    assert (out["category"], out["urgency"]) == (category, urgency)
