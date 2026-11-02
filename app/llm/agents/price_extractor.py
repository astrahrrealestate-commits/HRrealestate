"""Price extractor agent (M11): one web page -> the EUR prices it states for a named service (ADR 0009).

Page text is untrusted data (invariant 6): it only reaches the model inside escaped `<document>` and `<data>` blocks.
There is no trusted marker line, so there is nothing for page text to forge beyond the shared block tags. The agent
has no tools and cannot set a URL; the web source takes the URL from the search hit and re-checks the evidence.
"""

from app.contracts import ExtractedPrices, PromptRef
from app.llm.calls import AgentSpec
from app.llm.prompts import LoadedPrompt
from app.llm.render import data_block, one_line

MAX_PAGE_CHARS = 12_000


def _unchanged(output: ExtractedPrices, _loaded: LoadedPrompt) -> ExtractedPrices:
    return output


PRICE_EXTRACTOR = AgentSpec(
    name="price_extractor",
    prompt=PromptRef(name="price_extractor", version="v1"),
    output_type=ExtractedPrices,
    finalize=_unchanged,
)


def price_extractor_prompt(item_key: str, unit: str, page_title: str, page_text: str) -> str:
    wanted = data_block("data", f"Service: {one_line(item_key)}\nUnit: {one_line(unit)}")
    title = data_block("data", f"Page title: {one_line(page_title) or 'none'}")
    page = data_block("document", page_text.strip() or "none", MAX_PAGE_CHARS)
    return "\n".join([wanted, title, page])
