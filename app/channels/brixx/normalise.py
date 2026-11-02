"""BRIXX row normalisation: the API encodes null as an empty JSON object `{}`."""


def normalise_row(row: dict[str, object]) -> dict[str, object]:
    return {key: (None if value == {} else value) for key, value in row.items()}
