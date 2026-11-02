"""Deterministic fake LLM models (FunctionModel) for offline tests, eval and simulation."""

import re

from pydantic_ai.messages import BinaryContent, ModelMessage, ModelResponse, ToolCallPart, UserPromptPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from app.contracts import Category, Urgency
from app.llm.fakes_concierge import fake_concierge
from app.llm.fakes_diligence import fake_dd_reader
from app.llm.fakes_finance import fake_job_items, fake_price_extractor, fake_quote_reader
from app.llm.fakes_owner_qa import fake_owner_qa
from app.llm.fakes_proposer import fake_proposer


def _extract_user_text(messages: list[ModelMessage]) -> str:
    for m in reversed(messages):
        for part in getattr(m, "parts", []):
            if isinstance(part, UserPromptPart):
                if isinstance(part.content, str):
                    return part.content
                return "\n".join(c for c in part.content if isinstance(c, str))
    return ""


def _extract_binary(messages: list[ModelMessage]) -> bytes:
    for m in reversed(messages):
        for part in getattr(m, "parts", []):
            if isinstance(part, UserPromptPart) and not isinstance(part.content, str):
                for c in part.content:
                    if isinstance(c, BinaryContent):
                        return c.data
    return b""


_SUSPICIOUS = (
    r"ignore previous|iban|bankrekening wijzig"
    r"|rekeningnummer\b.{0,40}\bgewijzigd|gewijzigd\b.{0,40}\brekeningnummer|nieuw(e)? rekeningnummer"
    r"|verify your (bank|account|payment) details|update your (bank|payment) details"
)


def _fake_understanding(prompt: str) -> dict[str, object]:
    low = prompt.lower()
    if re.search(r"(contract|kündigung|opzeg|verhuis)", low):
        category = Category.lease
        intent = "Lease inquiry"
    elif re.search(r"(lek|leak|overstrom|flood|heizung|verwarming|kapot|broken|gaslucht|\bgas\b|brand|fire)", low):
        category = Category.maintenance
        intent = "Maintenance request"
    elif re.search(r"(huur|miete|\brent\b|betal)", low):
        category = Category.payment
        intent = "Payment inquiry"
    elif re.search(r"(offerte|quote|factuur|invoice)", low):
        category = Category.contractor_update
        intent = "Contractor update"
    else:
        category = Category.other
        intent = "General inquiry"

    if re.search(r"(overstrom|flood|gaslucht|\bgas\b|\bbrand\b|fire|rook|smoke|water staat)", low):
        urgency = Urgency.emergency
    elif category is Category.maintenance:
        urgency = Urgency.high
    else:
        urgency = Urgency.normal

    if re.search(_SUSPICIOUS, low):
        suspicious = {"flag": True, "reason": "Suspicious instruction or payment details"}
    else:
        suspicious = {"flag": False, "reason": None}

    no_reply = category is Category.spam or re.search(
        r"(unsubscribe|uitschrijven|newsletter|nieuwsbrief|delivered|bezorgd|out for delivery|was debited|"
        r"order[- ]?bevestiging|receipt|bedankt voor|dank u wel voor|thank you for|thanks for)",
        low,
    )
    return {
        "category": category.value,
        "intent": intent,
        "urgency": urgency.value,
        "requires_reply": not no_reply,
        "entities": {"people": [], "unit_refs": [], "dates": [], "amounts": []},
        "suspicious": suspicious,
        "confidence": 0.6,
        "prompt_version": "understanding/v2",
    }


_WORD = re.compile(r"[a-zà-ÿ]{4,}")
_STOPWORDS = frozenset(
    [
        "deze",
        "niet",
        "maar",
        "voor",
        "heeft",
        "hebben",
        "wordt",
        "worden",
        "zijn",
        "naar",
        "over",
        "onder",
        "alle",
        "weer",
        "still",
        "with",
        "this",
        "that",
        "have",
        "from",
        "been",
        "were",
        "will",
        "they",
        "their",
        "about",
        "again",
        "since",
    ]
)
# Summaries are English (case_summary writes them), messages mostly Dutch: map common Dutch terms so the offline
# fake can see an overlap a real model would see.
_NL_EN = {
    "lekt": "leak", "lekkage": "leak", "lekken": "leak", "gootsteen": "sink", "keuken": "kitchen",
    "badkamer": "bathroom", "deurbel": "doorbell", "schimmel": "mould", "plafond": "ceiling", "borg": "deposit",
    "huur": "rent", "verwarming": "heating", "kachel": "radiator", "opzegging": "notice", "onderhuur": "sublet",
    "onderverhuren": "sublet", "wonen": "sublet", "raam": "window", "foto": "photos", "betaalbewijs": "rent",
}  # fmt: skip


def _terms(text: str) -> set[str]:
    words = {w for w in _WORD.findall(text.lower()) if w not in _STOPWORDS}
    return words | {_NL_EN[w] for w in words if w in _NL_EN}


def _fake_link_check(prompt: str) -> dict[str, object]:
    """Pick the candidate whose summary shares the most words with the message; none shared → new case."""
    blocks = re.findall(r"<message>\n(.*?)\n</message>", prompt, flags=re.S)
    message = _terms(blocks[-1]) if blocks else set()
    best, best_score = None, 0
    for case_id, summary in re.findall(r"candidate:\s*([0-9a-fA-F-]{36})[^\n]*\n\s*([^\n]*)", prompt):
        score = len(message & _terms(summary))
        if score > best_score:
            best, best_score = case_id, score
    if best is None:
        return {"case_id": None, "reason": "No shared topic with any open case", "confidence": 0.7}
    return {"case_id": best, "reason": "Shares the topic of this open case", "confidence": 0.8}


def _fake_case_summary(prompt: str) -> dict[str, object]:
    blocks = re.findall(r"<message>\n(.*?)\n</message>", prompt, flags=re.S)
    text = " ".join(blocks[-1].split())[:200] if blocks else "Case opened."
    return {"summary": text, "next_step": "Review and reply"}


def _fake_briefing(prompt: str) -> dict[str, object]:
    sections: list[dict[str, object]] = []
    items: list[str] = []
    for line in prompt.splitlines():
        if line.startswith("## "):
            items = []
            sections.append({"title": line[3:][:40], "items": items})
        elif line.startswith("- ") and sections and len(items) < 8:
            items.append(line[2:][:240])
    return {"headline": f"{len(sections)} topics today (offline briefing).", "sections": sections[:6]}


_DOC_KEYWORDS = (
    (r"factuur|invoice|\bnota\b", "invoice", "Invoice"),
    (r"huurcontract|huurovereenkomst|\blease\b", "lease", "Lease agreement"),
    (r"offerte|prijsopgave|\bquote\b", "quote", "Quote"),
    (r"paspoort|passport|id-kaart|identiteitskaart|rijbewijs", "id_document", "Identity document"),
    (r"polis|verzekering|insurance", "insurance", "Insurance document"),
    (r"keuring|certifica|energielabel|attest", "certificate", "Certificate"),
)


def _fake_doc_classifier(prompt: str) -> dict[str, object]:
    low = prompt.lower()
    for pattern, doc_type, title in _DOC_KEYWORDS:
        if re.search(pattern, low):
            return {"doc_type": doc_type, "title": title, "document_date": None, "confidence": 0.85}
    if "mime_type: image/" in low:
        return {"doc_type": "photo", "title": "Photo", "document_date": None, "confidence": 0.5}
    return {"doc_type": "other", "title": "Document", "document_date": None, "confidence": 0.4}


def _block(prompt: str, tag: str) -> str:
    found = re.search(rf"<{tag}>\n(.*?)\n</{tag}>", prompt, re.S)
    return found.group(1) if found else ""


def _party(text: str, label: str, role: str) -> list[dict[str, str]]:
    found = re.search(rf"^{label}:\s*(.+)$", text, re.M | re.I)
    return [{"name": found.group(1).strip()[:120], "role": role}] if found else []


_FACT_LINE = re.compile(r"^(waarborgsom|huur|opzegtermijn|totaal|vervaldatum):\s*(.+)$", re.M | re.I)
_TERM = re.compile(r"^looptijd:\s*(\d{4}-\d{2}-\d{2})\s*(?:tot|-)\s*(\d{4}-\d{2}-\d{2})", re.M | re.I)


def _fake_doc_reader(prompt: str) -> dict[str, object]:
    """Offline reader: type from the document text (else the file name); `Huurder:`, `Verhuurder:`, `Leverancier:`
    and `Adres:` lines give parties and unit, `Looptijd: yyyy-mm-dd tot yyyy-mm-dd` the term, `Label: value` facts."""
    doc, meta = _block(prompt, "document"), _block(prompt, "file")
    cls = _fake_doc_classifier(doc + "\n" + meta if doc != "none" else meta)
    term, address = _TERM.search(doc), re.search(r"^adres:\s*(.+)$", doc, re.M | re.I)
    facts = [{"label": m.group(1).lower(), "value": m.group(2).strip()[:160]} for m in _FACT_LINE.finditer(doc)]
    parties = _party(doc, "huurder", "tenant") + _party(doc, "verhuurder", "landlord")
    parties += _party(doc, "leverancier", "contractor")
    return {
        "doc_type": cls["doc_type"], "title": cls["title"], "document_date": None,
        "summary": " ".join(doc.split())[:300] or "No readable text.",
        "parties": parties, "unit_hint": address.group(1).strip()[:200] if address else None,
        "start_date": term.group(1) if term else None, "end_date": term.group(2) if term else None,
        "key_facts": facts[:10],
        "confidence": 0.9 if doc != "none" and cls["doc_type"] != "other" else 0.4,
    }  # fmt: skip


_ENTRY = re.compile(r"\[ref ([0-9a-f]{8})\] ([^\n]*)\n(.*?)(?=\n\n---\n\n|\Z)", re.S)


def _fake_doc_qa(prompt: str) -> dict[str, object]:
    """Offline answer: the excerpt sentence sharing the most ideas with the question (glossary words of both languages
    count as one idea; an idea every sentence has counts for little), quoted verbatim."""
    from app.core.property_terms import canonical_tokens

    excerpts, question = _block(prompt, "excerpts"), _block(prompt, "message")
    wanted = {t for t in canonical_tokens(question) if len(t) >= 4}
    wanted = (wanted - {"lease"}) or wanted  # asking "in the lease" names the document, not the clause
    sentences = [
        (ref, s.strip(), {t for t in canonical_tokens(s) if len(t) >= 4})
        for ref, _title, text in _ENTRY.findall(excerpts)
        for s in re.split(r"(?<=[.!?\n])\s+", text)
        if len(s.strip()) >= 8
    ]
    weight = {t: 1 / (1 + sum(t in tokens for _, _, tokens in sentences)) for t in wanted}
    best: tuple[float, str, str] = (0.0, "", "")
    for ref, sentence, tokens in sentences:
        score = sum(weight[t] for t in wanted & tokens)
        if score > best[0]:
            best = (score, ref, sentence[:300])
    if best[0] == 0:
        return {"found": False, "answer": "The excerpts do not answer that.", "quotes": []}
    return {"found": True, "answer": best[2], "quotes": [{"doc_ref": best[1], "text": best[2]}]}


_FACT_BY_GROUP = (("rent", "monthly_rent"), ("deposit", "deposit"), ("notice", "notice_period"))


def _fake_fact(question: str, groups: list[str]) -> str | None:
    low = question.lower()
    if len(question.split()) > 8:
        return None
    if len(groups) == 1:
        for key, kind in _FACT_BY_GROUP:
            if key == groups[0]:
                return kind
    if "lease" in groups or "term" in groups:
        if re.search(r"\b(end|ends|einde|einddatum|expir\w*|verloopt)\b", low):
            return "lease_end"
        if re.search(r"\b(start|starts|begin|begint|ingangsdatum)\b", low):
            return "lease_start"
    return None


def _fake_rag_plan(prompt: str) -> dict[str, object]:
    """Offline planner: glossary words in both languages as keywords, the question's own wording as the hypothetical
    answer, and a fact only for a short question about exactly one of them."""
    from app.core.property_terms import expand, groups_in

    question = _block(prompt, "message")
    groups = groups_in(question)
    fact = _fake_fact(question, groups)
    return {
        "keywords": expand(question)[:8],
        "hypothetical_answer": question if groups else "",
        "fact": fact,
        "doc_types": ["lease"] if "lease" in groups or fact else [],
    }


def _fake_rerank_scores(question: str, passages: list[tuple[int, str, str]]) -> list[dict[str, int]]:
    """Offline reranker. Relevance 3 when a passage covers two of the question's ideas or words, 2 for one idea or a
    long shared word, 1 for a short shared word. A name or address the question mentions that appears in some other
    passage's header but not in this one caps it at 1: it is about someone else."""
    from app.core.property_terms import GROUPS, canonical_tokens

    wanted = set(canonical_tokens(question))
    plain = {t for t in wanted if t not in GROUPS and len(t) >= 4}
    heads = {n: set(canonical_tokens(head)) for n, head, _ in passages}
    named = {t for t in plain if any(t in h for h in heads.values())}
    out: list[dict[str, int]] = []
    for number, head, body in passages:
        have = set(canonical_tokens(f"{head} {body}"))
        shared = wanted & have
        ideas = shared & set(GROUPS)
        rel = (
            3
            if len(ideas) >= 2 or len(shared) >= 3
            else 2
            if ideas or any(len(t) >= 5 for t in shared)
            else int(bool(shared))
        )
        if named and not (named & heads[number]):
            rel = min(rel, 1)
        out.append({"ref": number, "relevance": rel})
    return out


def _fake_rag_rerank(prompt: str) -> dict[str, object]:
    pattern = r"\[(\d+)\] ([^\n]*)\n(.*?)(?=\n\n\[\d+\] |\Z)"
    passages = [(int(n), head, body) for n, head, body in re.findall(pattern, _block(prompt, "excerpts"), re.S)]
    return {"scores": _fake_rerank_scores(_block(prompt, "message"), passages)}


def model_for(agent_name: str) -> FunctionModel:
    def fn(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        user_text = _extract_user_text(messages)
        tool_name = info.output_tools[0].name if info.output_tools else "output"

        if agent_name == "understanding":
            args = _fake_understanding(user_text)
        elif agent_name == "link_check":
            args = _fake_link_check(user_text)
        elif agent_name == "case_summary":
            args = _fake_case_summary(user_text)
        elif agent_name == "proposer":
            args = fake_proposer(user_text)
        elif agent_name == "owner_qa":
            args = fake_owner_qa(user_text)
        elif agent_name == "concierge":
            args = fake_concierge(user_text)
        elif agent_name == "briefing":
            args = _fake_briefing(user_text)
        elif agent_name == "doc_classifier":
            args = _fake_doc_classifier(user_text)
        elif agent_name == "doc_reader":
            args = _fake_doc_reader(user_text)
        elif agent_name == "doc_qa":
            args = _fake_doc_qa(user_text)
        elif agent_name == "dd_reader":
            args = fake_dd_reader(_block(user_text, "document"), _block(user_text, "file").removeprefix("filename: "))
        elif agent_name == "rag_plan":
            args = _fake_rag_plan(user_text)
        elif agent_name == "rag_rerank":
            args = _fake_rag_rerank(user_text)
        elif agent_name == "quote_reader":
            args = fake_quote_reader(user_text)
        elif agent_name == "job_items":
            args = fake_job_items(user_text)
        elif agent_name == "price_extractor":
            args = fake_price_extractor(user_text)
        elif agent_name == "doc_ocr":
            args = {"text": _extract_binary(messages).removeprefix(b"SCAN").decode("utf-8", errors="replace").strip()}
        else:
            args = {}

        return ModelResponse(parts=[ToolCallPart(tool_name, args)])

    return FunctionModel(fn)
