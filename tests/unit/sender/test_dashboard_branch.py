"""send_to_owner for a dashboard owner: one feed insert, no Send row, no provider call (no database)."""

from functools import partial
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch
from uuid import uuid4

from app.channels.whatsapp import payloads
from app.channels.whatsapp.outbound import FakeWhatsAppOutbound
from app.channels.whatsapp.render import render_whatsapp
from app.contracts import InteractiveChannel, OwnerChoice, OwnerMessage
from app.db.enums import FeedKind
from app.sender.dashboard import resolve_message
from app.sender.execute import SenderDeps, send_to_owner

COMPANY = uuid4()
APPROVAL = uuid4()
CARD = OwnerMessage(text="pick", choices=(OwnerChoice(f"apr:{APPROVAL}:d1", "Send draft 1"),))


def _run(build: Any, key: str) -> tuple[str | None, MagicMock, FakeWhatsAppOutbound]:
    wa = FakeWhatsAppOutbound()
    engine = MagicMock()
    owner = SimpleNamespace(interactive_channel=InteractiveChannel.dashboard, whatsapp_e164="+31600000100")
    row_id = uuid4()
    with (
        patch("app.sender.execute.Session") as sess,
        patch("app.sender.dashboard.Session"),
        patch("app.sender.dashboard.feed.existing", return_value=None),  # a first delivery
        patch("app.sender.dashboard.feed.deliver", return_value=row_id) as deliver,
    ):
        sess.return_value.__enter__.return_value.scalar.side_effect = [None, owner]
        out = send_to_owner(SenderDeps(engine, wa, lambda _a: MagicMock()), COMPANY, key, build)
    assert out == str(row_id)
    return out, deliver, wa


def test_dashboard_owner_gets_feed_row_and_no_provider_call() -> None:
    _, deliver, wa = _run(partial(render_whatsapp, CARD), f"approval:{APPROVAL}:1")
    args = deliver.call_args.args
    assert args[1:5] == (COMPANY, f"approval:{APPROVAL}:1", FeedKind.approval, APPROVAL)
    assert args[5] is CARD  # the message survives the partial(render_whatsapp, ...) wrapper: choices kept
    assert wa.sent == []


def test_whatsapp_dict_falls_back_to_text() -> None:
    _, deliver, _ = _run(lambda to: payloads.text(to, "hello"), "owner_reply:1:0")
    assert deliver.call_args.args[3:5] == (FeedKind.alert, None)
    assert deliver.call_args.args[5] == OwnerMessage(text="hello")


def test_resolve_message_never_crashes_on_odd_builds() -> None:
    assert resolve_message(CARD, "+31") is CARD
    assert resolve_message(lambda to: CARD, "+31") is CARD
    assert resolve_message({"weird": 1}, "+31").text == "(no text)"
    assert resolve_message(lambda to: 42, "+31").text == "42"
    interactive = {"interactive": {"body": {"text": "body!"}}}
    assert resolve_message(lambda to: interactive, "+31").text == "body!"
    assert resolve_message({"text": "chat"}, "+31").text == "chat"


def test_dict_shapes_become_readable_text() -> None:
    whatsapp = payloads.text("+31600000100", "from whatsapp")
    chat_text = {"text": "plain chat"}
    chat_card = {
        "cardsV2": [
            {
                "card": {
                    "header": {"title": "Daily briefing"},
                    "sections": [
                        {
                            "widgets": [
                                {"textParagraph": {"text": "2 approvals"}},
                                {"decoratedText": {"text": "1 overdue task"}},
                                {"buttonList": {"buttons": []}},
                            ]
                        }
                    ],
                }
            }
        ]
    }
    assert resolve_message(whatsapp, "+31").text == "from whatsapp"
    assert resolve_message(chat_text, "+31").text == "plain chat"
    assert resolve_message(chat_card, "+31").text == "Daily briefing\n2 approvals\n1 overdue task"


def test_a_replay_returns_the_delivered_row_without_building_or_inserting() -> None:
    row_id = uuid4()
    built: list[str] = []

    def build(to: str) -> OwnerMessage:
        built.append(to)
        return CARD

    owner = SimpleNamespace(interactive_channel=InteractiveChannel.dashboard, whatsapp_e164="+31600000100")
    with (
        patch("app.sender.execute.Session") as sess,
        patch("app.sender.dashboard.Session"),
        patch("app.sender.dashboard.feed.existing", return_value=row_id),
        patch("app.sender.dashboard.feed.deliver") as deliver,
    ):
        sess.return_value.__enter__.return_value.scalar.side_effect = [None, owner]
        out = send_to_owner(
            SenderDeps(MagicMock(), FakeWhatsAppOutbound(), lambda _a: MagicMock()), COMPANY, "k", build
        )
    assert out == str(row_id)
    assert built == []
    deliver.assert_not_called()
