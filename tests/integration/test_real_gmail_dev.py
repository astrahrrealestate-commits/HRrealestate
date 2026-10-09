"""Dev tools for testing a real mailbox: one sync enqueued per pull; pending approvals listed with their card."""

from collections.abc import Iterator
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.channels.gmail.fake import FakeMailbox, MemoryMailboxStore
from app.contracts import ActionType, Category, Urgency
from app.core.errors import UnsafeConfigurationError
from app.core.settings import Settings
from app.db.enums import ActionStatus, SendStatus
from app.db.models import ActionRow, ChannelAccount, Company, Send
from app.dev import real_gmail
from app.dev.seed import seed_dev_tenant
from app.pipeline import approvals, case_repo

pytestmark = pytest.mark.integration
REAL = "tester@example.test"


@pytest.fixture(autouse=True)
def _purge_dev_tenant(migrated_engine: Engine) -> Iterator[None]:
    """seed_dev_tenant commits the dev company (dev WhatsApp number): remove it so other tests can create theirs."""
    yield
    from app.dev.fixtures import DEV_COMPANY
    from tests.integration.conftest import purge_company

    with Session(migrated_engine) as s:
        dev_ids = s.scalars(select(Company.id).where(Company.name == DEV_COMPANY)).all()
    for company_id in dev_ids:
        purge_company(migrated_engine, company_id)


class _Recorder:
    def __init__(self) -> None:
        self.calls: list[tuple[dict[str, Any], tuple[Any, ...]]] = []

    def enqueue_in_transaction(self, conn_or_session: Any, options: Any, *args: Any) -> None:
        self.calls.append((options, args))


def test_pull_registers_the_mailbox_and_enqueues_one_sync(
    migrated_engine: Engine, test_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    google = test_settings.model_copy(update={"gmail_provider": "google"})
    with pytest.raises(UnsafeConfigurationError):
        real_gmail.pull_mailbox(migrated_engine, test_settings, _Recorder(), REAL)  # fake provider: refused
    mailbox = FakeMailbox(REAL, MemoryMailboxStore())
    monkeypatch.setattr("app.dev.real_gmail.registry.gmail_mailbox", lambda _s, _a: mailbox)
    client = _Recorder()
    workflow_id = real_gmail.pull_mailbox(migrated_engine, google, client, REAL.upper())
    [(options, args)] = client.calls
    assert options["workflow_name"] == "ingest.gmail_sync"
    assert options["workflow_id"] == workflow_id
    with Session(migrated_engine) as s:
        account = s.scalar(select(ChannelAccount).where(ChannelAccount.address == REAL))
        assert account is not None
        assert args == (str(account.id), mailbox.current_history_id())


def test_pending_lists_newest_first_with_the_card_message(migrated_engine: Engine) -> None:
    tenant = seed_dev_tenant(migrated_engine)
    cid = tenant.company_id
    with Session(migrated_engine) as s, s.begin():
        case_id = case_repo.create_case(s, cid, None, Category.maintenance, Urgency.normal)
        a = ActionRow(
            company_id=cid,
            case_id=case_id,
            type=ActionType.reply_draft,
            rationale="r",
            context_ref=[],
            payload={
                "kind": "reply_draft",
                "channel": "gmail",
                "subject": None,
                "body_variants": ["Geachte heer, dank voor uw bericht.", "B"],
            },
            status=ActionStatus.pending_approval,
        )
        s.add(a)
        s.flush()
        approval_id: UUID = approvals.open_approval(s, cid, a.id, 1, urgency=Urgency.normal, now=a.created_at)
        s.add(
            Send(
                company_id=cid,
                idempotency_key=f"approval:{approval_id}:1",
                channel="whatsapp",
                target="+3",
                status=SendStatus.sent,
                provider_ref="wamid.CARD",
            )
        )
    found = real_gmail.pending_approvals(migrated_engine, cid)
    mine = next(p for p in found if p.approval_id == approval_id)
    assert (mine.kind, mine.card_wamid) == ("reply_draft", "wamid.CARD")
    assert mine.draft_preview.startswith("Geachte heer")
    assert found[0].n == 1


def test_first_pull_starts_from_now_and_backfill_is_opt_in(
    migrated_engine: Engine, test_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A real inbox holds personal mail: the first pull must not ingest the past unless asked."""
    from app.db.models import GmailSyncState

    google = test_settings.model_copy(update={"gmail_provider": "google"})
    mailbox = FakeMailbox(REAL, MemoryMailboxStore())
    mailbox.add_message(b"From: bank@example.test\r\nSubject: old\r\n\r\nold", labels=["INBOX"])
    monkeypatch.setattr("app.dev.real_gmail.registry.gmail_mailbox", lambda _s, _a: mailbox)
    real_gmail.pull_mailbox(migrated_engine, google, _Recorder(), REAL)
    with Session(migrated_engine) as s:
        state = s.scalar(select(GmailSyncState))
        assert state is not None
        assert state.history_id == str(mailbox.current_history_id())  # cursor at "now": the old mail is skipped
        s.delete(state)
        s.commit()
    real_gmail.pull_mailbox(migrated_engine, google, _Recorder(), REAL, backfill=True)
    with Session(migrated_engine) as s:
        assert s.scalar(select(GmailSyncState)) is None  # no cursor: the first sync reads the last day
