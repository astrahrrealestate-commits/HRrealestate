"""List the Gemini models the configured key can call and name the strongest Pro model (M13 T5).

Run: `uv run python -m app.dev.gemini_models`. Prints model names only, never the key. The chosen model goes into
`LLM_QUALITY_MODEL` of the task definition (docs/go-live-channels.md).
"""

import re
import sys
from collections.abc import Iterable

from app.core.settings import Settings

_PRO = re.compile(r"gemini-(\d+(?:\.\d+)?)-pro(-preview[\w-]*)?$")


def strongest_pro(names: Iterable[str]) -> str | None:
    """The highest-version `gemini-X-pro` model as a Pydantic AI string; at one version a stable release beats a
    preview. None when the key lists no Pro model."""
    ranked: list[tuple[float, int, str]] = []
    for raw in names:
        name = raw.removeprefix("models/")
        m = _PRO.search(name)
        if m:
            ranked.append((float(m.group(1)), 0 if m.group(2) else 1, name))
    return f"google-gla:{max(ranked)[2]}" if ranked else None


def _listed(api_key: str) -> list[str]:
    from google import genai

    client = genai.Client(api_key=api_key, http_options={"api_version": "v1beta"})
    return [m.name for m in client.models.list() if m.name]


def main() -> int:
    settings = Settings()
    if not settings.gemini_api_key:
        sys.stderr.write("GEMINI_API_KEY is not set\n")
        return 1
    names = sorted(_listed(settings.gemini_api_key.get_secret_value()))
    sys.stdout.write("".join(f"{name}\n" for name in names))
    sys.stdout.write(f"strongest pro: {strongest_pro(names)}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
