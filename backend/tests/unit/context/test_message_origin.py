"""What a stored message's metadata says about where it came from (M13 T1)."""

from typing import Any

from app.context.message_origin import full_text, is_history, is_owner_authored
from app.db.models import MessageRow


def _msg(text: str = "Ok.", **meta: Any) -> MessageRow:
    return MessageRow(text=text, meta=meta)


def test_history_and_owner_authored_are_read_from_metadata() -> None:
    assert is_history(_msg(history=True))
    assert not is_history(_msg())
    assert is_owner_authored(_msg(owner_authored=True))
    assert not is_owner_authored(_msg())


def test_only_a_real_true_counts() -> None:
    assert not is_history(_msg(history="false"))
    assert not is_owner_authored(_msg(owner_authored="yes"))


def test_full_text_is_the_unstripped_mail_when_quotes_were_removed() -> None:
    assert full_text(_msg("Ok.", full_text="Ok.\n\nOp 3 nov schreef Harjot:\n> Donderdag.")).endswith("Donderdag.")
    assert full_text(_msg("Ok.", full_text=None)) == "Ok."
