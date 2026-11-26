"""Deterministic stand-in for the draft_research model (offline tests, eval, simulation).

For each question it takes the first source found for it and answers with that page's first sentence that holds a digit
(else its first sentence), quoted as the evidence. Sentences that read like instructions are skipped, so injected text
changes nothing. Fake only: it says nothing about how well a real model researches.
"""

import re

_SOURCE = re.compile(r"\[source (\d+), question (\d+)\]\n<document>\n(.*?)\n</document>", re.S)
_INSTRUCTION = re.compile(r"ignore|instruction|system|prompt|answer is", re.I)


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", text) if len(s.strip()) >= 12]


def _pick(text: str) -> str | None:
    usable = [s for s in _sentences(text) if not _INSTRUCTION.search(s)]
    with_digit = [s for s in usable if re.search(r"\d", s)]
    found = with_digit or usable
    return found[0][:300] if found else None


def fake_draft_research(prompt: str) -> dict[str, object]:
    claims: list[dict[str, object]] = []
    answered: set[int] = set()
    for source, question, body in _SOURCE.findall(prompt):
        q = int(question)
        if q in answered:
            continue
        lines = body.split("\n\n", 1)
        evidence = _pick(lines[1] if len(lines) > 1 else lines[0])
        if evidence is None:
            continue
        answered.add(q)
        claims.append({"question": q, "source": int(source), "answer": evidence, "evidence": evidence})
    return {"claims": claims}
