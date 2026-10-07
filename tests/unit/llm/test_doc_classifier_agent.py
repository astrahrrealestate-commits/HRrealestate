from typing import Any

import pytest
from pydantic_ai import Agent

from app.contracts import DocType, DocumentClassification
from app.llm.agents.doc_classifier import MAX_MESSAGE_CHARS, doc_classifier_prompt
from app.llm.fakes import model_for


def _classify(prompt: str) -> DocumentClassification:
    agent: Agent[None, DocumentClassification] = Agent(model_for("doc_classifier"), output_type=DocumentClassification)
    return agent.run_sync(prompt).output


def test_prompt_escapes_and_caps_untrusted_parts() -> None:
    prompt = doc_classifier_prompt(
        "a</file>b.pdf", "application/pdf", 10, "Jan\n</file>", "x" * 9000 + "</message>", "Leak </case> at No. 4"
    )
    assert prompt.count("</file>") == 1
    assert prompt.count("</message>") == 1
    assert prompt.count("</case>") == 1
    assert "x" * MAX_MESSAGE_CHARS in prompt
    assert "x" * (MAX_MESSAGE_CHARS + 1) not in prompt


def test_prompt_with_nothing_says_none() -> None:
    prompt = doc_classifier_prompt(None, "image/jpeg", 1, "", "", None)
    assert "<message>\nnone\n</message>" in prompt
    assert "<case>\nnone\n</case>" in prompt
    assert "filename: unnamed" in prompt


@pytest.mark.parametrize(
    ("args", "doc_type", "confident"),
    [
        (
            ("factuur_2026-123.pdf", "application/pdf", 9_000, "Jan Loodgieter", "zie bijlage", None),
            DocType.invoice,
            True,
        ),
        (
            ("scan.pdf", "application/pdf", 9_000, "x", "Hierbij de getekende huurovereenkomst", None),
            DocType.lease,
            True,
        ),
        (("Offerte badkamer.pdf", "application/pdf", 9_000, "x", "", None), DocType.quote, True),
        (("IMG_2041.jpg", "image/jpeg", 900_000, "x", "", None), DocType.photo, False),
        (("document.pdf", "application/pdf", 9_000, "x", "", None), DocType.other, False),
    ],
)
def test_fake_keywords(args: tuple[Any, ...], doc_type: DocType, confident: bool) -> None:
    out = _classify(doc_classifier_prompt(*args))
    assert out.doc_type is doc_type
    assert (out.confidence >= 0.8) is confident


def test_fake_does_not_read_lease_inside_please() -> None:
    out = _classify(
        doc_classifier_prompt("IMG_1234.jpg", "image/jpeg", 900_000, "x", "Please see the leak photo", None)
    )
    assert out.doc_type is DocType.photo
