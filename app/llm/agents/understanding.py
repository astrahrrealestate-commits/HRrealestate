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
    prompt=PromptRef(name="understanding", version="v1"),
    output_type=Understanding,
    finalize=_stamp_prompt_version,
)


def understanding_prompt(
    text: str,
    channel: Channel,
    subject: str | None = None,
    attachments: Sequence[AttachmentMeta] = (),
) -> str:
    """The email subject is sender-controlled, so it is rendered inside the untrusted <message> block."""
    body = f"Subject: {subject}\n\n{text}" if subject else text
    return f"Channel: {channel.value}\n{attachments_block(attachments)}\n{data_block('message', body)}"
