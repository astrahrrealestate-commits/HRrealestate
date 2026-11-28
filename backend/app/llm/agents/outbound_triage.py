"""Lightweight fast-tier outbound triage agent specification."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from app.contracts import Channel, OutboundTriage, PromptRef
from app.llm.calls import AgentSpec
from app.llm.prompts import LoadedPrompt
from app.llm.render import data_block


def _stamp_prompt_version(output: OutboundTriage, loaded: LoadedPrompt) -> OutboundTriage:
    return output.model_copy(update={"prompt_version": loaded.ref.key})


OUTBOUND_TRIAGE = AgentSpec(
    name="outbound_triage",
    prompt=PromptRef(name="outbound_triage", version="v1"),
    output_type=OutboundTriage,
    finalize=_stamp_prompt_version,
    thinking="minimal",
)


def outbound_triage_prompt(
    text: str,
    channel: Channel,
    subject: str | None = None,
    sent_at: datetime | None = None,
    case_summary: str | None = None,
) -> str:
    """Build compact prompt for fast-tier extraction of commitments & awaited replies from an outbound message."""
    trimmed = text[:6000] if text else ""
    header: list[str] = []
    if sent_at is not None:
        local = (sent_at if sent_at.tzinfo else sent_at.replace(tzinfo=UTC)).astimezone(ZoneInfo("Europe/Amsterdam"))
        header.append(f"Date: {local:%Y-%m-%d (%A)}")
    if subject:
        header.append(f"Subject: {subject[:300]}")
    body = ("\n".join(header) + f"\n\n{trimmed}") if header else trimmed
    blocks = [f"Channel: {channel.value}"]
    if case_summary:
        blocks.append(data_block("case_summary", case_summary[:600]))
    blocks.append(data_block("message", body))
    return "\n".join(blocks)
