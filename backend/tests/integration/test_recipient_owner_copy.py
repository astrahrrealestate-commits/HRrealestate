"""A reply is never addressed to Harjot's own copy of his mail (M13 security review)."""

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.contracts import Channel
from app.db.models import Company
from app.sender.recipient import latest_inbound
from tests.integration.conversation_support import OWNER, add_case, add_mail, add_owner, add_person

pytestmark = pytest.mark.integration
ANOUK = "anouk@example.test"


def test_the_latest_inbound_mail_skips_harjots_own_copies(migrated_engine: Engine, committed_company: Company) -> None:
    cid = committed_company.id
    add_owner(migrated_engine, cid)
    anouk = add_person(migrated_engine, cid, "Anouk", ANOUK)
    case = add_case(migrated_engine, cid, anouk)
    tenant = add_mail(migrated_engine, cid, "Lekkage", sender=ANOUK, person_id=anouk, case_id=case, days_ago=1)
    add_mail(migrated_engine, cid, "Mijn antwoord", sender=OWNER, case_id=case, owner_authored=True)
    with Session(migrated_engine) as s:
        found = latest_inbound(s, cid, case, Channel.gmail)
    assert found is not None
    assert found.id == tenant
