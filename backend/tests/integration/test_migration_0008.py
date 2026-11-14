"""Migration 0008: owner settings (chat_user, interactive_channel) and Channel.google_chat."""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.contracts import Channel, InteractiveChannel
from app.db.models import Company, OwnerAccount

pytestmark = pytest.mark.integration


def test_owner_account_stores_chat_user_and_interactive_channel(db: Session, company: Company) -> None:
    owner = OwnerAccount(
        company_id=company.id,
        display_name="Harjot",
        whatsapp_e164="+31612345678",
        email="harjot@example.com",
        chat_user="users/1234567890",
        interactive_channel=InteractiveChannel.google_chat,
    )
    db.add(owner)
    db.flush()
    assert owner.chat_user == "users/1234567890"
    assert owner.interactive_channel is InteractiveChannel.google_chat


def test_invalid_interactive_channel_fails_check_constraint(db: Session, company: Company) -> None:
    nested = db.begin_nested()
    with pytest.raises(IntegrityError):
        db.execute(
            text(
                "INSERT INTO owner_accounts (id, company_id, display_name, whatsapp_e164, interactive_channel) "
                "VALUES (gen_random_uuid(), :cid, 'H', '+31611111111', 'slack')"
            ),
            {"cid": company.id},
        )
    nested.rollback()


def test_google_chat_is_valid_channel_in_messages_and_channel_accounts(db: Session, company: Company) -> None:
    # Channel accounts accepts google_chat
    res = db.execute(
        text(
            "INSERT INTO channel_accounts (id, company_id, channel, address, is_owner_channel) "
            "VALUES (gen_random_uuid(), :cid, :ch, 'spaces/test', false) RETURNING channel"
        ),
        {"cid": company.id, "ch": Channel.google_chat.value},
    ).scalar()
    assert res == "google_chat"
