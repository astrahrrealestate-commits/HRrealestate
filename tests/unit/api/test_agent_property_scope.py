"""A question that names a street is answered for that street, or says there is no such property."""

from uuid import uuid4

from app.api.agent.property_scope import property_scope
from app.llm.agents.owner_qa import CaseBrief

UNITS = [
    ("Keizersgracht 42-A", "Keizersgracht 42-A, 1015 CS Amsterdam"),
    ("Prinsengracht 118-B", "Prinsengracht 118-B, 1015 EA Amsterdam"),
    ("Lijnbaansgracht 9-C", "Lijnbaansgracht 9-C, 1017 PN Amsterdam"),
]


def _brief(label: str) -> CaseBrief:
    return CaseBrief(uuid4(), label, "open", "high", "x")


BRIEFS = [
    _brief("Sanne de Vries · Keizersgracht 42-A, 1015 CS Amsterdam (other)"),
    _brief("Mohammed El Amrani · Prinsengracht 118-B, 1015 EA Amsterdam"),
    _brief("Pieter · Unassigned"),
]


def test_a_question_without_a_street_is_not_scoped() -> None:
    scope = property_scope("Show the open tickets", UNITS, BRIEFS)
    assert scope.kind == "none"


def test_a_known_street_keeps_only_that_streets_cases() -> None:
    scope = property_scope("Show tickets for Prinsengracht", UNITS, BRIEFS)
    assert scope.kind == "scoped"
    assert [b.label for b in scope.briefs] == [BRIEFS[1].label]


def test_a_street_with_no_cases_is_scoped_to_nothing_not_to_everything() -> None:
    scope = property_scope("tickets for Lijnbaansgracht 9-C", UNITS, BRIEFS)
    assert scope.kind == "scoped"
    assert scope.briefs == ()


def test_a_street_that_is_not_in_the_portfolio_is_unknown() -> None:
    scope = property_scope("Show tickets for Herengracht Historic", UNITS, BRIEFS)
    assert (scope.kind, scope.street) == ("unknown", "Herengracht")


def test_case_does_not_matter() -> None:
    assert property_scope("KEIZERSGRACHT overdue rent", UNITS, BRIEFS).kind == "scoped"


def test_a_full_unit_label_narrows_to_that_unit() -> None:
    units = [*UNITS, ("Prinsengracht 120-A", None)]
    briefs = [*BRIEFS, _brief("Eva · Prinsengracht 120-A")]
    scope = property_scope("tickets at Prinsengracht 120-A", units, briefs)
    assert [b.label for b in scope.briefs] == ["Eva · Prinsengracht 120-A"]


def test_one_known_and_one_unknown_street_is_scoped_to_the_known_one() -> None:
    scope = property_scope("Keizersgracht and Herengracht tickets", UNITS, BRIEFS)
    assert scope.kind == "scoped"
    assert [b.label for b in scope.briefs] == [BRIEFS[0].label]
