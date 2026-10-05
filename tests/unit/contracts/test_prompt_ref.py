from pathlib import Path

import pytest
from pydantic import ValidationError

from app.contracts import PromptRef


def test_paths() -> None:
    r = PromptRef(name="understanding", version="v1")
    assert r.key == "understanding/v1"
    assert r.relative_path == Path("v1/understanding.md")


@pytest.mark.parametrize(("name", "version"), [("../etc", "v1"), ("Understanding", "v1"), ("u", "1"), ("u", "v1/..")])
def test_rejects_traversal_and_bad_names(name: str, version: str) -> None:
    with pytest.raises(ValidationError):
        PromptRef(name=name, version=version)
