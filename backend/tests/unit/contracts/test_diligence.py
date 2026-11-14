"""Due Diligence Lite contracts: what the dd_reader agent returns, and the vocabularies the report uses."""

from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.contracts.diligence import FIELD_KIND, DDClaim, DDDocKind, DDDocRead, DDField, DDFlag
from tests.unit.contracts.test_llm_schema import _walk


def _claim(**over: object) -> dict[str, object]:
    base: dict[str, object] = {
        "field": "living_area_m2", "number": "85", "text": None, "day": None, "quote": "Woonoppervlakte 85 m2",
    }  # fmt: skip
    return {**base, **over}


def _read(**over: object) -> dict[str, object]:
    base: dict[str, object] = {
        "doc_kind": "brochure", "title": "Brochure Kerkstraat 12", "document_date": None, "valid_until": None,
        "claims": [_claim()], "flags": [], "confidence": 0.9,
    }  # fmt: skip
    return {**base, **over}


def test_claim_number_field_takes_a_number() -> None:
    claim = DDClaim.model_validate(_claim())
    assert claim.number == Decimal(85)
    assert claim.field is DDField.living_area_m2


@pytest.mark.parametrize(
    "bad",
    [
        {"number": None, "text": "85"},  # number field with a text value
        {"number": "85", "text": "85"},  # two slots filled
        {"number": None},  # nothing filled
        {"field": "energy_label", "number": None, "text": "C", "day": date(2020, 1, 1)},  # text field, day also set
        {"field": "ground_lease_end", "number": "2045", "text": None},  # date field with a number
        {"number": "-5"},  # negative
        {"quote": "  "},  # blank quote
    ],
)
def test_claim_rejects_wrong_slot_or_blank_quote(bad: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        DDClaim.model_validate(_claim(**bad))


def test_every_field_has_a_value_kind() -> None:
    assert set(FIELD_KIND) == set(DDField)


def test_doc_read_caps_claims_and_flags() -> None:
    DDDocRead.model_validate(_read(claims=[_claim()] * 25))
    with pytest.raises(ValidationError):
        DDDocRead.model_validate(_read(claims=[_claim()] * 26))
    flag = {"category": "legal", "summary": "Pending dispute", "quote": "geschil met de VvE"}
    DDDocRead.model_validate(_read(flags=[flag] * 6))
    with pytest.raises(ValidationError):
        DDDocRead.model_validate(_read(flags=[flag] * 7))


def test_doc_read_confidence_is_a_probability() -> None:
    with pytest.raises(ValidationError):
        DDDocRead.model_validate(_read(confidence=1.5))


@pytest.mark.parametrize("model", [DDDocRead, DDClaim, DDFlag])
def test_reader_output_schema_is_openai_strict(model: type[DDDocRead] | type[DDClaim] | type[DDFlag]) -> None:
    assert _walk(model.model_json_schema()) == []


def test_doc_kind_values_are_stable() -> None:
    assert {k.value for k in DDDocKind} >= {"brochure", "purchase_agreement", "vve_rules", "energy_label", "other"}
