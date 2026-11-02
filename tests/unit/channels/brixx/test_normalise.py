from app.channels.brixx.normalise import normalise_row


def test_normalise_null_object() -> None:
    row: dict[str, object] = {"website": {}, "id": 1, "name": "x"}
    assert normalise_row(row) == {"website": None, "id": 1, "name": "x"}


def test_normalise_keeps_non_empty_dict() -> None:
    row: dict[str, object] = {"meta": {"a": 1}, "empty_list": [], "zero": 0, "blank": ""}
    assert normalise_row(row) == row


def test_normalise_does_not_mutate_input() -> None:
    row: dict[str, object] = {"x": {}}
    normalise_row(row)
    assert row == {"x": {}}
