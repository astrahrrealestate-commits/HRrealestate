"""Page context on a Super Agent turn: stored at create time, resolved once at run time, reused on a retry."""

from unittest.mock import MagicMock, patch
from uuid import uuid4

from app.contracts import PageContext
from app.db.models import AgentTurn
from app.pipeline import concierge_turns as ct

M = "app.pipeline.concierge_turns"


def _added_turn(session: MagicMock) -> AgentTurn:
    turns = [c.args[0] for c in session.add.call_args_list if isinstance(c.args[0], AgentTurn)]
    assert len(turns) == 1
    return turns[0]


def test_create_turn_stores_the_validated_page_as_json() -> None:
    page = PageContext.model_validate({"view": "case", "case_id": str(uuid4()), "snapshot": "Sanne  ·  leak"})
    session = MagicMock()
    with patch(f"{M}.read_turns.owns_conversation", return_value=True):
        ct.create_turn(session, uuid4(), uuid4(), uuid4(), "summarise this", page=page)
    stored = _added_turn(session).page_context
    assert stored == page.model_dump(mode="json")
    assert stored is not None
    assert stored["snapshot"] == "Sanne · leak"


def test_create_turn_without_a_page_stores_none() -> None:
    session = MagicMock()
    with patch(f"{M}.read_turns.owns_conversation", return_value=True):
        ct.create_turn(session, uuid4(), uuid4(), uuid4(), "tasks")
    assert _added_turn(session).page_context is None
