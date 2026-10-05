"""`PromptRef`: names one immutable prompt file `app/llm/prompts/<version>/<name>.md`."""

from pathlib import Path
from typing import Annotated

from pydantic import StringConstraints

from app.contracts.common import Contract


class PromptRef(Contract):
    name: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]*$")]
    version: Annotated[str, StringConstraints(pattern=r"^v[0-9]+$")]

    @property
    def key(self) -> str:
        return f"{self.name}/{self.version}"

    @property
    def relative_path(self) -> Path:
        return Path(self.version) / f"{self.name}.md"
