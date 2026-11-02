"""The checklist is data: the default framework is valid and a JSON file can replace it."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.contracts.diligence import DDDocKind, DDPropertyKind
from app.diligence.framework import Framework, default_framework, load_framework


def test_default_framework_covers_every_property_kind() -> None:
    fw = default_framework()
    for kind in DDPropertyKind:
        assert any(kind in r.property_kinds for r in fw.requirements), kind


def test_requirement_keys_are_unique() -> None:
    keys = [r.key for r in default_framework().requirements]
    assert len(keys) == len(set(keys))


def test_every_doc_kind_has_an_authority() -> None:
    assert set(default_framework().authority) == set(DDDocKind)


def test_brochure_is_the_lowest_authority() -> None:
    authority = default_framework().authority
    assert authority[DDDocKind.brochure] == min(authority.values())
    assert authority[DDDocKind.deed_of_title] == max(authority.values())


def test_framework_round_trips_through_json(tmp_path: Path) -> None:
    fw = default_framework()
    path = tmp_path / "fw.json"
    path.write_text(fw.model_dump_json())
    assert load_framework(path) == fw


def test_load_framework_none_gives_default() -> None:
    assert load_framework(None) == default_framework()


def test_duplicate_keys_are_rejected(tmp_path: Path) -> None:
    fw = default_framework()
    data = fw.model_dump(mode="json")
    data["requirements"].append(data["requirements"][0])
    with pytest.raises(ValidationError):
        Framework.model_validate(data)


def test_authority_must_cover_every_doc_kind() -> None:
    data = default_framework().model_dump(mode="json")
    del data["authority"]["brochure"]
    with pytest.raises(ValidationError):
        Framework.model_validate(data)
