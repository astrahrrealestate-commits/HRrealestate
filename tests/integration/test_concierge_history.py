"""`earlier_exchanges` against real Postgres: this conversation only, this company only, before the cursor."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.db.enums import TurnStatus
from app.db.models import AgentConversation, AgentTurn, Company, OwnerAccount
from app.pipeline import read_turns

pytestmark = pytest.mark.integration
T0 = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)


def _turn(company: Company, conv: AgentConversation, n: int, status: TurnStatus, answer: str | None) -> AgentTurn:
    return AgentTurn(
        company_id=company.id,
        conversation_id=conv.id,
        text=f"q{n}",
        answer=answer,
        status=status,
        created_at=T0 + timedelta(minutes=n),
    )


def test_history_is_this_conversation_in_this_company(migrated_engine: Engine) -> None:
    with Session(migrated_engine) as s:
        ca, cb = Company(name="A"), Company(name="B")
        s.add_all([ca, cb])
        s.flush()
        owner = OwnerAccount(company_id=ca.id, display_name="H", whatsapp_e164="+31699999971", email="h@a.test")
        other = OwnerAccount(company_id=ca.id, display_name="P", whatsapp_e164="+31699999972", email="p@a.test")
        foreign = OwnerAccount(company_id=cb.id, display_name="F", whatsapp_e164="+31699999973", email="f@b.test")
        s.add_all([owner, other, foreign])
        s.flush()
        mine = AgentConversation(company_id=ca.id, owner_id=owner.id)
        sibling = AgentConversation(company_id=ca.id, owner_id=other.id)
        elsewhere = AgentConversation(company_id=cb.id, owner_id=foreign.id)
        s.add_all([mine, sibling, elsewhere])
        s.flush()
        done, fail = TurnStatus.done, TurnStatus.failed
        s.add_all(
            [
                _turn(ca, mine, 1, done, "a1"),
                _turn(ca, mine, 2, fail, "sorry"),
                _turn(ca, mine, 3, TurnStatus.running, None),
                _turn(ca, mine, 4, done, "a4"),
                _turn(ca, sibling, 5, done, "other owner"),
                _turn(cb, elsewhere, 6, done, "other company"),
                _turn(cb, mine, 7, done, "wrong company on my conversation"),
                _turn(ca, mine, 9, done, "after the cursor"),
            ]
        )
        s.commit()
        cursor = (T0 + timedelta(minutes=8), mine.id)
        rows = read_turns.earlier_exchanges(s, ca.id, mine.id, cursor, 6)
        assert rows == [("q1", "a1", done), ("q4", "a4", done)]
        assert read_turns.earlier_exchanges(s, cb.id, mine.id, cursor, 6) == []
        assert read_turns.earlier_exchanges(s, ca.id, elsewhere.id, cursor, 6) == []
