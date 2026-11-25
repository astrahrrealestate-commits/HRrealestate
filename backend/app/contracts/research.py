"""Web and reference research behind a draft (M13)."""

from typing import Annotated

from pydantic import StringConstraints

from app.contracts.common import Contract, NonBlankStr, max_len


class Finding(Contract):
    """One answer with the page it was read from. There is no finding without a source."""

    question: Annotated[NonBlankStr, max_len(300)]
    answer: Annotated[NonBlankStr, max_len(1500)]
    url: Annotated[str, StringConstraints(pattern=r"^https?://")]
