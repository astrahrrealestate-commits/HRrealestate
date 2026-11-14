"""Chunk sizing keeps one INSERT under Postgres' 65535 bind-parameter limit."""

import pytest

from app.directory.brixx.upsert import MAX_BIND_PARAMS, chunk_size


@pytest.mark.parametrize("params_per_row", [1, 5, 12, 100, 1000, 65_000])
def test_chunk_never_exceeds_bind_limit(params_per_row: int) -> None:
    size = chunk_size(params_per_row)
    assert size >= 1
    assert size * params_per_row <= MAX_BIND_PARAMS or size == 1


def test_chunk_uses_most_of_the_budget() -> None:
    assert chunk_size(10) >= (MAX_BIND_PARAMS - 100) // 10


def test_very_wide_row_still_makes_progress() -> None:
    assert chunk_size(MAX_BIND_PARAMS) == 1
