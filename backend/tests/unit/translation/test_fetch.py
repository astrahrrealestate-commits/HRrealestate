"""The model downloads are pinned and verified: nothing unchecked reaches the image."""

import hashlib
from pathlib import Path

import httpx
import pytest
import respx

from app.translation import fetch as fetch_module


@pytest.fixture
def tiny_models(monkeypatch: pytest.MonkeyPatch) -> dict[str, dict[str, bytes]]:
    contents = {
        direction: {name: f"{direction}/{name}".encode() for name in spec.files}
        for direction, spec in fetch_module.MODELS.items()
    }
    monkeypatch.setattr(
        fetch_module,
        "MODELS",
        {
            direction: fetch_module.ModelSpec(
                repo=spec.repo,
                revision=spec.revision,
                files={n: hashlib.sha256(b).hexdigest() for n, b in contents[direction].items()},
            )
            for direction, spec in fetch_module.MODELS.items()
        },
    )
    return contents


@respx.mock
def test_files_are_fetched_from_the_pinned_revision_of_each_direction(
    tmp_path: Path, tiny_models: dict[str, dict[str, bytes]]
) -> None:
    for direction, files in tiny_models.items():
        spec = fetch_module.MODELS[direction]
        for name, data in files.items():
            url = f"https://huggingface.co/{spec.repo}/resolve/{spec.revision}/{name}"
            respx.get(url).mock(return_value=httpx.Response(200, content=data))
        fetch_module.fetch(tmp_path / direction, direction)
        assert {p.name for p in (tmp_path / direction).iterdir()} == set(files)


@respx.mock
def test_a_file_with_the_wrong_checksum_is_deleted_and_refused(
    tmp_path: Path, tiny_models: dict[str, dict[str, bytes]]
) -> None:
    respx.get(url__regex=r"https://huggingface\.co/.*").mock(return_value=httpx.Response(200, content=b"tampered"))
    with pytest.raises(SystemExit, match="checksum mismatch"):
        fetch_module.fetch(tmp_path)
    assert list(tmp_path.iterdir()) == []


@respx.mock
def test_matching_files_already_on_disk_are_not_downloaded_again(
    tmp_path: Path, tiny_models: dict[str, dict[str, bytes]]
) -> None:
    for name, data in tiny_models["nl-en"].items():
        (tmp_path / name).write_bytes(data)
    route = respx.get(url__regex=r"https://huggingface\.co/.*")
    fetch_module.fetch(tmp_path)
    assert not route.called
