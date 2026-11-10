"""The model download is pinned and verified: nothing unchecked reaches the image."""

import hashlib
from pathlib import Path

import httpx
import pytest
import respx

from app.translation import fetch as fetch_module


@pytest.fixture
def tiny_model(monkeypatch: pytest.MonkeyPatch) -> dict[str, bytes]:
    files = {name: name.encode() for name in fetch_module.FILES}
    monkeypatch.setattr(fetch_module, "FILES", {n: hashlib.sha256(b).hexdigest() for n, b in files.items()})
    return files


@respx.mock
def test_files_are_fetched_from_the_pinned_revision(tmp_path: Path, tiny_model: dict[str, bytes]) -> None:
    for name, data in tiny_model.items():
        url = f"https://huggingface.co/{fetch_module.REPO}/resolve/{fetch_module.REVISION}/{name}"
        respx.get(url).mock(return_value=httpx.Response(200, content=data))
    fetch_module.fetch(tmp_path)
    assert {p.name for p in tmp_path.iterdir()} == set(tiny_model)


@respx.mock
def test_a_file_with_the_wrong_checksum_is_deleted_and_refused(tmp_path: Path, tiny_model: dict[str, bytes]) -> None:
    respx.get(url__regex=r"https://huggingface\.co/.*").mock(return_value=httpx.Response(200, content=b"tampered"))
    with pytest.raises(SystemExit, match="checksum mismatch"):
        fetch_module.fetch(tmp_path)
    assert list(tmp_path.iterdir()) == []


@respx.mock
def test_matching_files_already_on_disk_are_not_downloaded_again(tmp_path: Path, tiny_model: dict[str, bytes]) -> None:
    for name, data in tiny_model.items():
        (tmp_path / name).write_bytes(data)
    route = respx.get(url__regex=r"https://huggingface\.co/.*")
    fetch_module.fetch(tmp_path)
    assert not route.called
