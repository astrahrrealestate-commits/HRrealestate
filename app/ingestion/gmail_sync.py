"""Gmail mailbox sync (no DBOS here): history → raw events with a compare-and-swap cursor; watch renewal; accounts.

A sync reads Gmail with no transaction open, then records everything in one short transaction that re-checks the
cursor. New messages become raw events keyed by the Gmail id. A message that gains the INBOX label after it was
ignored (e.g. "Not spam") is recorded once more as `<id>:inbox`, so mail rescued from spam still reaches the pipeline.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.channels.gmail.ports import GmailMailbox, HistoryExpiredError
from app.contracts import Channel
from app.core.errors import NotFoundError
from app.core.ids import new_id
from app.core.logging import get_logger
from app.db.enums import RawEventStatus
from app.db.models import ChannelAccount, GmailSyncState, RawEvent
from app.ingestion.process import IngestDeps
from app.ingestion.repository import record_event

log = get_logger(__name__)
RESYNC_WINDOW = timedelta(days=7)  # expired history cursor: bounded catch-up
FIRST_SYNC_WINDOW = timedelta(days=1)  # mailbox without a cursor (watch never ran): recent mail only, no flood


@dataclass
class NewMail:
    ids: list[str]  # newly added messages
    cursor: int  # history id to store once these are recorded
    inbox: list[str] = field(default_factory=list)  # messages that gained INBOX (spam rescue, un-archive)


def sync_mailbox(deps: IngestDeps, account_id: UUID, push_history_id: int, max_messages: int | None = 2) -> int:
    """Record one raw event per new Gmail message and advance the cursor. Returns the number recorded."""
    with Session(deps.engine) as session:
        account = session.get(ChannelAccount, account_id)
        if account is None or account.channel is not Channel.gmail:
            return 0
        company_id, address = account.company_id, account.address
        cursor = _cursor(session, company_id, account_id)
    if cursor is not None and push_history_id <= cursor:
        return 0  # stale or duplicate notification
    mail = _new_mail(deps.gmail_mailbox(address), cursor)
    if max_messages and len(mail.ids) > max_messages:
        mail.ids = mail.ids[:max_messages]
    with Session(deps.engine) as session, session.begin():
        _ensure_state(session, company_id, account_id)
        state = _locked_state(session, company_id, account_id)
        current = int(state.history_id) if state.history_id else None
        if current != cursor:
            log.info("gmail.sync.cursor_moved", account_id=str(account_id))
            return 0  # another sync committed meanwhile and covered this range
        account = session.get(ChannelAccount, account_id)
        if account is None:
            raise NotFoundError(f"gmail account {account_id} removed during sync")
        recorded = _record(session, deps, account, mail)
        state.history_id = str(max(mail.cursor, push_history_id))
    log.info("gmail.sync", account_id=str(account_id), new=recorded)
    return recorded


def _record(session: Session, deps: IngestDeps, account: ChannelAccount, mail: NewMail) -> int:
    base = {"v": 1, "kind": "gmail", "mailbox": account.address}
    keys = [(mid, mid) for mid in mail.ids]
    keys += [(_inbox_key(session, account, mid), mid) for mid in mail.inbox if mid not in mail.ids]
    new = [record_event(session, deps.enqueuer, account, key, {**base, "message_id": mid}) for key, mid in keys]
    return sum(raw_id is not None for raw_id in new)


def _inbox_key(session: Session, account: ChannelAccount, message_id: str) -> str:
    """Unseen message → its own id. Seen and ignored (spam), or still pending (its run may yet mark it ignored) →
    `<id>:inbox`, recorded once; if the original does get processed, `save_message` dedupes the second run.
    Otherwise the plain id again, which the unique key turns into a no-op."""
    status = session.scalar(
        select(RawEvent.status).where(
            RawEvent.company_id == account.company_id,
            RawEvent.provider == Channel.gmail,
            RawEvent.provider_msg_id == message_id,
        )
    )
    rescue = status in (RawEventStatus.ignored, RawEventStatus.pending)
    return f"{message_id}:inbox" if rescue else message_id


def _cursor(session: Session, company_id: UUID, account_id: UUID) -> int | None:
    value = session.scalar(
        select(GmailSyncState.history_id).where(
            GmailSyncState.company_id == company_id, GmailSyncState.channel_account_id == account_id
        )
    )
    return int(value) if value else None


def _ensure_state(session: Session, company_id: UUID, account_id: UUID) -> None:
    """Upsert the cursor row so concurrent first syncs / watch renewals never collide on insert."""
    session.execute(
        insert(GmailSyncState)
        .values(id=new_id(), company_id=company_id, channel_account_id=account_id)
        .on_conflict_do_nothing(index_elements=["channel_account_id"])
    )


def _locked_state(session: Session, company_id: UUID, account_id: UUID) -> GmailSyncState:
    state = session.scalar(
        select(GmailSyncState)
        .where(GmailSyncState.company_id == company_id, GmailSyncState.channel_account_id == account_id)
        .with_for_update()
    )
    if state is None:  # pragma: no cover — _ensure_state just inserted it
        raise NotFoundError(f"gmail sync state for {account_id}")
    return state


def _new_mail(mailbox: GmailMailbox, start: int | None) -> NewMail:
    if start is None:
        return _listing(mailbox, FIRST_SYNC_WINDOW)  # first sync without a cursor: recent mail only
    mail = NewMail(ids=[], cursor=start)
    token: str | None = None
    try:
        while True:
            page = mailbox.history_since(start, page_token=token)
            mail.ids += [i for i in page.message_ids if i not in mail.ids]
            mail.inbox += [i for i in page.inbox_added if i not in mail.inbox]
            mail.cursor = page.history_id
            if not page.next_page_token:
                return mail
            token = page.next_page_token
    except HistoryExpiredError:
        log.warning("gmail.history_expired_resync", start=start)
        return _listing(mailbox, RESYNC_WINDOW)


def _listing(mailbox: GmailMailbox, window: timedelta) -> NewMail:
    """Read the history id BEFORE listing: mail arriving in between is then above the cursor and comes through
    history next time (listing it twice is a dedupe no-op), instead of being skipped for good."""
    cursor = mailbox.current_history_id()
    return NewMail(ids=mailbox.message_ids_since(datetime.now(UTC) - window), cursor=cursor)


# ---- watches / backfill ------------------------------------------------------------------------------------------


def gmail_accounts(deps: IngestDeps) -> list[tuple[UUID, str, UUID]]:
    """All Gmail accounts across companies — a deliberate cross-tenant read for system crons (watch, backfill)."""
    with Session(deps.engine) as session:
        rows = session.execute(
            select(ChannelAccount.id, ChannelAccount.address, ChannelAccount.company_id).where(
                ChannelAccount.channel == Channel.gmail
            )
        ).all()
    return [(r.id, r.address, r.company_id) for r in rows]


def renew_watch(deps: IngestDeps, account_id: UUID, address: str, company_id: UUID) -> datetime:
    result = deps.gmail_mailbox(address).watch(deps.gmail_topic)
    with Session(deps.engine) as session, session.begin():
        _ensure_state(session, company_id, account_id)  # may race a first sync: upsert, never a plain insert
        state = _locked_state(session, company_id, account_id)
        if not state.history_id:  # onboarding: syncs start from "now", no historic flood
            state.history_id = str(result.history_id)
        state.watch_expires_at = result.expiration
    return result.expiration
