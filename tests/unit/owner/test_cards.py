from uuid import uuid4

from app.channels.whatsapp import payloads
from app.contracts import ButtonChoice, ButtonId, Urgency
from app.owner.cards import ApprovalCard, approval_payloads, exception_payload

TO = "+31600000100"


def _card(drafts: tuple[str, ...], urgency: Urgency = Urgency.normal, kind: str = "Reply") -> ApprovalCard:
    return ApprovalCard(uuid4(), "Sanne de Vries · maintenance", urgency, "Water leak in bathroom", kind, drafts, None)


def test_three_drafts_text_then_list_menu_with_every_choice() -> None:
    card = _card(("Optie A", "Optie B", "Optie C"), Urgency.emergency)
    first, menu = [build(TO) for build in approval_payloads(card)]
    body = first["text"]["body"]
    assert body.startswith("[EMERGENCY] Reply: Sanne de Vries · maintenance\nWater leak in bathroom")
    assert "Draft 1:\nOptie A" in body
    assert "Draft 3:\nOptie C" in body
    rows = menu["interactive"]["action"]["sections"][0]["rows"]
    ids = [ButtonId.parse(r["id"]).choice for r in rows]
    assert ids == [ButtonChoice.d1, ButtonChoice.d2, ButtonChoice.d3, ButtonChoice.edit, ButtonChoice.rej]
    assert all(len(r["title"]) <= payloads.LIST_ROW_TITLE_MAX for r in rows)


def test_single_draft_uses_reply_buttons() -> None:
    _, buttons = [build(TO) for build in approval_payloads(_card(("Alleen deze",)))]
    choices = [ButtonId.parse(b["reply"]["id"]).choice for b in buttons["interactive"]["action"]["buttons"]]
    assert choices == [ButtonChoice.ok, ButtonChoice.edit, ButtonChoice.rej]


def test_non_draft_action_is_one_message_with_approve_reject() -> None:
    card = ApprovalCard(uuid4(), "Case", Urgency.high, "Leak", "Escalation", (), "Emergency reported by tenant")
    [only] = [build(TO) for build in approval_payloads(card)]
    assert "[HIGH] Escalation: Case" in only["interactive"]["body"]["text"]
    choices = [ButtonId.parse(b["reply"]["id"]).choice for b in only["interactive"]["action"]["buttons"]]
    assert choices == [ButtonChoice.ok, ButtonChoice.rej]


def test_very_long_drafts_are_split_within_text_limit() -> None:
    card = _card(("x" * 3000, "y" * 3000))
    built = [build(TO) for build in approval_payloads(card)]
    texts = [p["text"]["body"] for p in built if p["type"] == "text"]
    assert len(texts) >= 2
    assert all(len(t) <= payloads.TEXT_BODY_MAX for t in texts)
    assert built[-1]["type"] == "interactive"


def test_exception_alert() -> None:
    body = exception_payload("Sanne · payment", "IBAN change requested")(TO)["text"]["body"]
    assert body.startswith("Needs your eyes (not drafted): Sanne · payment")
    assert "IBAN change requested" in body
