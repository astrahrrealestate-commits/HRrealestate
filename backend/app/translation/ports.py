"""The translation seam: pipeline code depends on this Protocol; tests pass a fake."""

from typing import Protocol


class Translator(Protocol):
    """Translates short segments (a sentence each) Dutch to English. Safe to call from several threads."""

    engine: str  # stored with every cached translation, so a model change is visible in the data

    def translate(self, segments: list[str]) -> list[str]:
        """One English string per input segment, in order."""
        ...
