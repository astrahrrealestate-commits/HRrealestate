"""Understanding agent specification and user prompt builder."""

from collections.abc import Sequence

from app.contracts import Channel, PromptRef, Understanding
from app.llm.calls import AgentSpec
from app.llm.prompts import LoadedPrompt
from app.llm.render import AttachmentMeta, attachments_block, data_block


def _stamp_prompt_version(output: Understanding, loaded: LoadedPrompt) -> Understanding:
    return output.model_copy(update={"prompt_version": loaded.ref.key})


UNDERSTANDING = AgentSpec(
    name="understanding",
    prompt=PromptRef(name="understanding", version="v6"),
    output_type=Understanding,
    finalize=_stamp_prompt_version,
    thinking="minimal",
)


MAX_UNDERSTANDING_BODY_CHARS: int = 10_000
MAX_SENDER_CHARS: int = 320  # an email address; anything longer is not one
SENDER_AWARE_PROMPTS = frozenset(
    {"v3", "v4", "v5", "v6"}
)  # prompts that tell the model what a `From:` line is; earlier ones never see it


def sees_sender(version: str) -> bool:
    """Whether a prompt version may be shown the sender's address (v1 and v2 predate the line)."""
    return version in SENDER_AWARE_PROMPTS


def sender_shown_to_model(channel: Channel, identity: str | None) -> str | None:
    """The sender's address for the prompt: email only (a phone number adds nothing to triage), and only once the
    pinned prompt version knows what the line is."""
    if channel is not Channel.gmail or not identity or not sees_sender(UNDERSTANDING.prompt.version):
        return None
    return identity


def understanding_prompt(
    text: str,
    channel: Channel,
    subject: str | None = None,
    attachments: Sequence[AttachmentMeta] = (),
    sender: str | None = None,
) -> str:
    """The email subject and the sender are sender-controlled, so both render inside the untrusted <message> block."""
    if len(text) > MAX_UNDERSTANDING_BODY_CHARS:
        text = text[:MAX_UNDERSTANDING_BODY_CHARS] + "\n\n...[content truncated for triage]"
    if subject and len(subject) > 500:
        subject = subject[:500] + "..."
    header = [f"From: {sender.strip()[:MAX_SENDER_CHARS]}"] if sender and sender.strip() else []
    if subject:
        header.append(f"Subject: {subject}")
    body = "\n".join(header) + f"\n\n{text}" if header else text
    return f"Channel: {channel.value}\n{attachments_block(attachments)}\n{data_block('message', body)}"
