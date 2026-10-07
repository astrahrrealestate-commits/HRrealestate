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
    subj_str = f"Subject: {subject}\n" if subject else ""
    return f"Channel: {channel.value}\n{subj_str}{attachments_block(attachments)}\n{data_block('message', text)}"
