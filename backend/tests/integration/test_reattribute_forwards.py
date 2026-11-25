"""One-off repair of mail stored under the team's own address: each message gets its original sender; cases stay."""

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.channels.gmail.fake import FakeMailbox, MemoryMailboxStore
from app.channels.gmail.google import GmailApiError
from app.contracts import ActionType, CaseState, Category, Channel, Direction, Urgency
from app.db.enums import ActionStatus, ApprovalStatus, LinkMethod, PersonKind, SendStatus, TaskStatus
from app.db.models import (
    ActionRow,
    Approval,
    Case,
    CaseEvent,
    CaseLink,
    ChannelAccount,
    ChannelIdentity,
    Company,
    Lease,
    LeaseParty,
    MessageRow,
    OwnerAccount,
    Person,
    RawEvent,
    Send,
    TaskRow,
    Unit,
)
from app.pipeline.approvals import approved_unexecuted
from app.sender.gmail_reply import gmail_draft
from app.sender.targets import SendBlockedError
from app.sender.tenant_plans import tenant_gmail
from app.workflows.reattribute import RepairRefusedError, reattribute
from tests.integration.conftest import purge_company

pytestmark = pytest.mark.integration
MAILBOX, HARJOT = "info@vastgoed.example.test", "harjot@vastgoed.example.test"
JAN, PIET = "jan@example.test", "piet@example.test"
T0 = datetime(2026, 1, 5, 9, 0, tzinfo=UTC)


@dataclass
class World:
    engine: Engine
    company: UUID
    mailbox: FakeMailbox
    harjot: UUID
    case: UUID
    unit: UUID
    approval: UUID
    action: UUID


def _mail(reply_to: str | None, subject: str) -> bytes:
    mail = EmailMessage()
    mail["From"] = f"Harjot Singh <{HARJOT}>"
    mail["To"] = MAILBOX
    mail["Subject"] = subject
    if reply_to:
        mail["Reply-To"] = reply_to
    mail.set_content(f"{subject} body")
    return mail.as_bytes()


def _stored(
    s: Session, w_company: UUID, case: UUID, provider_id: str, thread: str, minutes: int,
    direction: Direction = Direction.inbound, sender: str = HARJOT, person: UUID | None = None,
) -> UUID:  # fmt: skip
    raw = RawEvent(company_id=w_company, provider=Channel.gmail, provider_msg_id=f"r-{uuid4()}", payload={})
    s.add(raw)
    s.flush()
    row = MessageRow(
        company_id=w_company, raw_event_id=raw.id, channel=Channel.gmail, provider_msg_id=provider_id,
        thread_ref=thread, sender_identity=sender, direction=direction, sent_at=T0 + timedelta(minutes=minutes),
        text="x", person_id=person, meta={"subject": thread, "mailbox": MAILBOX, "from_name": "Harjot Singh"},
    )  # fmt: skip
    s.add(row)
    s.flush()
    s.add(CaseLink(company_id=w_company, case_id=case, message_id=row.id, method=LinkMethod.open_case))
    return row.id


@pytest.fixture
def world(migrated_engine: Engine) -> Iterator[World]:
    """Two forwards from Harjot (Jan, then Piet) and one real sent reply, all filed in one case under Harjot."""
    mailbox = FakeMailbox(MAILBOX, MemoryMailboxStore())
    jan_id = mailbox.add_message(_mail(f"Jan de Vries <{JAN}>", "lekkage"), labels=["INBOX"], thread_id="t-jan")
    piet_id = mailbox.add_message(_mail(PIET, "sleutel"), labels=["INBOX"], thread_id="t-piet")
    sent_id = mailbox.add_message(_mail(JAN, "antwoord"), labels=["SENT"], thread_id="t-jan")
    own_id = mailbox.add_message(_mail(None, "notitie"), labels=["INBOX"], thread_id="t-own")
    with Session(migrated_engine) as s:
        company = Company(name="Reattribute")
        s.add(company)
        s.flush()
        cid = company.id
        harjot = Person(company_id=cid, kind=PersonKind.other, display_name="Harjot Singh", valid_from=T0.date())
        jan = Person(company_id=cid, kind=PersonKind.tenant, display_name="Jan", valid_from=T0.date())
        unit = Unit(company_id=cid, label="Singel 1", valid_from=T0.date())
        s.add_all([harjot, jan, unit, ChannelAccount(company_id=cid, channel=Channel.gmail, address=MAILBOX)])
        s.add(OwnerAccount(company_id=cid, display_name="Harjot", whatsapp_e164="+31600000001", email=HARJOT))
        s.flush()
        lease = Lease(company_id=cid, unit_id=unit.id, valid_from=T0.date())
        s.add(lease)
        s.flush()
        s.add(LeaseParty(company_id=cid, lease_id=lease.id, person_id=jan.id, role="tenant"))
        for person, address in ((harjot, HARJOT), (jan, JAN)):
            s.add(ChannelIdentity(company_id=cid, person_id=person.id, channel=Channel.gmail, identity=address,
                                  valid_from=T0.date()))  # fmt: skip
        case = Case(company_id=cid, primary_person_id=harjot.id, category=Category.maintenance, urgency=Urgency.high,
                    summary="mixed", state=CaseState.open)  # fmt: skip
        s.add(case)
        s.flush()
        action = ActionRow(company_id=cid, case_id=case.id, type=ActionType.reply_draft, rationale="r", context_ref=[],
                           payload={"kind": "reply_draft", "channel": "gmail", "body_variants": ["Beste Harjot"]},
                           status=ActionStatus.pending_approval)  # fmt: skip
        s.add(action)
        s.flush()
        approval = Approval(company_id=cid, action_id=action.id, draft_version=1, status=ApprovalStatus.pending)
        s.add(approval)
        _stored(s, cid, case.id, jan_id, "t-jan", 1, person=harjot.id)
        _stored(s, cid, case.id, piet_id, "t-piet", 2, person=harjot.id)
        _stored(s, cid, case.id, sent_id, "t-jan", 3, direction=Direction.outbound, sender=MAILBOX)
        _stored(s, cid, case.id, own_id, "t-own", 4, person=harjot.id)
        _stored(s, cid, case.id, "hist_0123456789abcdef", "t-hist", 5, direction=Direction.outbound)
        s.commit()
        made = World(migrated_engine, cid, mailbox, harjot.id, case.id, unit.id, approval.id, action.id)
    yield made
    with Session(migrated_engine) as s:
        s.query(OwnerAccount).filter(OwnerAccount.company_id == made.company).delete()
        s.commit()
    purge_company(migrated_engine, made.company)


def _senders(w: World) -> dict[str, tuple[str, str]]:
    with Session(w.engine) as s:
        rows = s.scalars(select(MessageRow).where(MessageRow.company_id == w.company).order_by(MessageRow.sent_at))
        return {str(r.sent_at.minute): (r.sender_identity, r.direction.value) for r in rows}


def _rows(s: Session, w: World) -> list[MessageRow]:
    return list(s.scalars(select(MessageRow).where(MessageRow.company_id == w.company).order_by(MessageRow.sent_at)))


def _run(w: World, apply: bool):  # type: ignore[no-untyped-def]
    return reattribute(w.engine, lambda address: w.mailbox, MAILBOX, apply=apply)


def test_a_dry_run_reports_the_changes_and_writes_nothing(world: World) -> None:
    before = _senders(world)
    report = _run(world, apply=False)
    assert sorted((c.old_sender, c.new_sender) for c in report.changes) == [(HARJOT, JAN), (HARJOT, PIET)]
    assert (len(report.cancelled), report.unrecoverable, report.unchanged) == (1, 1, 2)
    assert report.company_id == world.company
    assert report.to_label == 0  # the case's latest incoming mail is Harjot's own note: nothing to ask a model about
    assert _senders(world) == before
    with Session(world.engine) as s:
        assert s.get(Approval, world.approval).status is ApprovalStatus.pending  # type: ignore[union-attr]
        assert s.scalars(select(Case).where(Case.company_id == world.company)).all().__len__() == 1
        assert s.scalar(select(ChannelIdentity).where(ChannelIdentity.identity == PIET)) is None
        assert {r.person_id for r in _rows(s, world) if r.sent_at.minute in (1, 2)} == {world.harjot}
        assert all("reattributed_from" not in r.meta for r in _rows(s, world))
        assert s.get(ActionRow, world.action).status is ActionStatus.pending_approval  # type: ignore[union-attr]


def test_apply_gives_each_forward_its_own_sender_and_contact_and_leaves_cases_alone(world: World) -> None:
    report = _run(world, apply=True)
    senders = _senders(world)
    assert (senders["1"], senders["2"]) == ((JAN, "inbound"), (PIET, "inbound"))
    assert senders["3"] == (MAILBOX, "outbound")  # really sent by the mailbox
    assert senders["4"] == (HARJOT, "inbound")  # his own note: nobody else is named
    assert senders["5"] == (HARJOT, "outbound")  # no Gmail id to re-read: left alone
    with Session(world.engine) as s:
        rows = {r.sent_at.minute: r for r in _rows(s, world)}
        assert s.get(Person, rows[1].person_id).display_name == "Jan"  # type: ignore[union-attr]
        assert s.get(Person, rows[2].person_id).display_name == PIET  # type: ignore[union-attr]
        assert rows[1].meta["from_name"] == "Jan de Vries"
        assert "from_name" not in rows[2].meta
        assert rows[1].meta["reattributed_from"] == {
            "sender": HARJOT, "direction": "inbound", "person_id": str(world.harjot),
            "headers": {"from_name": "Harjot Singh", "mailbox": MAILBOX},
        }  # fmt: skip
        case = s.get(Case, world.case)
        assert case is not None
        assert (case.primary_person_id, case.unit_id, case.summary) == (world.harjot, None, "mixed")
        assert s.scalars(select(Case.id).where(Case.company_id == world.company)).all() == [world.case]
        assert {s.scalar(select(CaseLink.case_id).where(CaseLink.message_id == r.id)) for r in rows.values()} == {
            world.case
        }
    [flagged] = report.cases
    assert (flagged.case_id, flagged.senders) == (world.case, (HARJOT, JAN, PIET))  # everyone who wrote on it
    assert (flagged.contact, flagged.state) == ("Harjot Singh", "open")
    again = _run(world, apply=True)
    assert (again.changes, again.cancelled, again.cases) == ([], [], [])


def _reply_state(w: World, approval: ApprovalStatus, action: ActionStatus, send: SendStatus | None = None) -> None:
    with Session(w.engine) as s:
        s.get(Approval, w.approval).status = approval  # type: ignore[union-attr]
        s.get(ActionRow, w.action).status = action  # type: ignore[union-attr]
        if send is not None:
            s.add(Send(company_id=w.company, action_id=w.action, idempotency_key=f"exec:{w.action}:1",
                       channel=Channel.gmail, target=JAN, status=send))  # fmt: skip
        s.commit()


def _reply(w: World) -> tuple[ApprovalStatus, ActionStatus]:
    with Session(w.engine) as s:
        return s.get(Approval, w.approval).status, s.get(ActionRow, w.action).status  # type: ignore[union-attr]


@pytest.mark.parametrize(
    ("approval", "action", "send"),
    [
        (ApprovalStatus.pending, ActionStatus.pending_approval, None),
        (ApprovalStatus.approved, ActionStatus.approved, None),  # blocked or paused: resume would send it
        (ApprovalStatus.approved, ActionStatus.approved, SendStatus.pending),
        (ApprovalStatus.edited, ActionStatus.pending_approval, None),
        (ApprovalStatus.approved, ActionStatus.paused, None),
    ],
)
def test_every_unsent_reply_on_a_repaired_case_is_cancelled_and_cannot_resume(
    world: World, approval: ApprovalStatus, action: ActionStatus, send: SendStatus | None
) -> None:
    _reply_state(world, approval, action, send)
    with Session(world.engine) as s:
        s.add(TaskRow(company_id=world.company, case_id=world.case, action_id=world.action, title="Approve",
                      source="action", status=TaskStatus.open, assignee="owner"))  # fmt: skip
        s.commit()
    report = _run(world, apply=True)
    assert [(c.action_id, c.was) for c in report.cancelled] == [(world.action, action.value)]
    if send is SendStatus.pending:  # claimed, not yet attempted: it must never be able to start
        with Session(world.engine) as s:
            held = s.scalars(select(Send).where(Send.company_id == world.company)).one()
            assert held.status is SendStatus.failed
            assert held.error
    assert _reply(world) == (ApprovalStatus.expired, ActionStatus.superseded)
    with Session(world.engine) as s:
        assert approved_unexecuted(s, world.company) == []
        assert s.scalar(select(TaskRow.status).where(TaskRow.company_id == world.company)) is TaskStatus.done
        notes = s.scalars(select(CaseEvent.note).where(CaseEvent.company_id == world.company)).all()
        assert any(str(world.action) in n and action.value in n and approval.value in n for n in notes)


@pytest.mark.parametrize(
    ("approval", "action", "send"),
    [
        (ApprovalStatus.approved, ActionStatus.executed, SendStatus.sent),
        (ApprovalStatus.edited, ActionStatus.executed, None),  # history: an old edit tap on a finished reply
        (ApprovalStatus.approved, ActionStatus.approved, SendStatus.failed),  # never re-run: left as the record
        (ApprovalStatus.rejected, ActionStatus.rejected, None),
    ],
)
def test_finished_replies_keep_their_history(
    world: World, approval: ApprovalStatus, action: ActionStatus, send: SendStatus | None
) -> None:
    _reply_state(world, approval, action, send)
    assert _run(world, apply=True).cancelled == []
    assert _reply(world) == (approval, action)


def test_a_send_in_progress_stops_the_whole_run_before_anything_changes(world: World) -> None:
    _reply_state(world, ApprovalStatus.approved, ActionStatus.approved, SendStatus.sending)
    before = _senders(world)
    with pytest.raises(RepairRefusedError):
        _run(world, apply=True)
    assert _senders(world) == before


def test_a_sent_marked_row_is_not_flipped_on_quoted_text_alone(world: World) -> None:
    """A history import marked the team's own reply as sent; a quoted forward in it does not make it incoming."""
    quoted = "---------- Forwarded message ---------\r\nFrom: Other <other@example.test>\r\n\r\nzie hieronder"
    mail = EmailMessage()
    mail["From"], mail["To"], mail["Subject"] = HARJOT, MAILBOX, "fwd"
    mail.set_content(quoted)
    provider_id = world.mailbox.add_message(mail.as_bytes(), labels=["INBOX"], thread_id="t-q")
    with Session(world.engine) as s:
        _stored(s, world.company, world.case, provider_id, "t-q", 6, direction=Direction.outbound)
        s.commit()
    report = _run(world, apply=True)
    assert report.uncertain == 1
    assert _senders(world)["6"] == (HARJOT, "outbound")


class Broken(FakeMailbox):
    status = 503

    def get_message(self, message_id: str):  # type: ignore[no-untyped-def]
        raise GmailApiError("boom", status=self.status, retryable=self.status >= 500)


@pytest.mark.parametrize("status", [401, 429, 503])
def test_a_gmail_outage_changes_nothing(world: World, status: int) -> None:
    broken = Broken(MAILBOX, MemoryMailboxStore())
    broken.status = status
    before = _senders(world)
    with pytest.raises(GmailApiError):
        reattribute(world.engine, lambda _: broken, MAILBOX, apply=True)
    assert _senders(world) == before


def test_applying_is_refused_when_not_one_original_can_be_read(world: World) -> None:
    broken = Broken(MAILBOX, MemoryMailboxStore())
    broken.status = 400  # one odd id is only "cannot be read"; every one failing means the wrong mailbox
    assert reattribute(world.engine, lambda _: broken, MAILBOX, apply=False).unrecoverable == 5
    with pytest.raises(RepairRefusedError):
        reattribute(world.engine, lambda _: broken, MAILBOX, apply=True)
    assert _reply(world) == (ApprovalStatus.pending, ActionStatus.pending_approval)


def test_another_companys_mail_from_the_same_address_is_untouched(world: World) -> None:
    with Session(world.engine) as s:
        rival = Company(name="Rival")
        s.add(rival)
        s.flush()
        case = Case(company_id=rival.id, category=Category.other, urgency=Urgency.low, summary="r")
        s.add(case)
        s.flush()
        message = _stored(s, rival.id, case.id, "18c000000000009a", "t-r", 7)
        s.commit()
        rival_id = rival.id
    try:
        _run(world, apply=True)
        with Session(world.engine) as s:
            row = s.get(MessageRow, message)
            assert row is not None
            assert (row.sender_identity, "reattributed_from" in row.meta) == (HARJOT, False)
    finally:
        purge_company(world.engine, rival_id)


def test_an_unknown_mailbox_is_refused(world: World) -> None:
    from app.core.errors import NotFoundError

    with pytest.raises(NotFoundError):
        reattribute(world.engine, lambda address: world.mailbox, "nobody@example.test", apply=False)


def test_a_case_that_only_shares_the_thread_loses_its_unsent_reply_too(world: World) -> None:
    """The inbox shows a thread's messages on every case holding that thread, linked or not."""
    mail = _mail(JAN, "later")
    provider_id = world.mailbox.add_message(mail, labels=["INBOX"], thread_id="t-shared")
    with Session(world.engine) as s:
        other = Case(company_id=world.company, category=Category.other, urgency=Urgency.low, summary="o")
        s.add(other)
        s.flush()
        _stored(s, world.company, other.id, "hist_aaaaaaaaaaaaaaaa", "t-shared", 8, sender="anouk@example.test")
        loose = _stored(s, world.company, other.id, provider_id, "t-shared", 9)
        s.query(CaseLink).filter(CaseLink.message_id == loose).delete()
        action = ActionRow(company_id=world.company, case_id=other.id, type=ActionType.reply_draft, rationale="r",
                           context_ref=[], payload={}, status=ActionStatus.pending_approval)  # fmt: skip
        s.add(action)
        s.flush()
        s.add(Approval(company_id=world.company, action_id=action.id, draft_version=1, status=ApprovalStatus.pending))
        s.commit()
        other_id, other_action = other.id, action.id
    report = _run(world, apply=True)
    assert other_action in [c.action_id for c in report.cancelled]
    assert other_id in [c.case_id for c in report.cases]


def _draft_to(w: World, answers: int | None) -> str:
    """The recipient a draft-mode reply gets when it answers the mail sent at minute `answers` (None: a chaser)."""
    with Session(w.engine) as s:
        refs = [r.id for r in _rows(s, w) if r.sent_at.minute == answers]
        action = ActionRow(company_id=w.company, case_id=w.case, type=ActionType.reply_draft, rationale="r",
                           context_ref=refs, payload={}, status=ActionStatus.approved)  # fmt: skip
        s.add(action)
        s.flush()
        try:
            return gmail_draft(s, action, "tekst", "k").target
        finally:
            s.rollback()


def test_on_a_repaired_case_a_draft_only_goes_to_the_person_it_answers(world: World) -> None:
    _run(world, apply=True)
    with Session(world.engine) as s:  # Harjot's own note is not the newest mail here, so Piet's is
        s.query(CaseLink).filter(
            CaseLink.message_id.in_([r.id for r in _rows(s, world) if r.sent_at.minute == 4])
        ).delete()
        s.commit()
    assert _draft_to(world, answers=2) == PIET
    for answers in (1, None):  # written for Jan; or a chaser on a case several people share
        with pytest.raises(SendBlockedError, match="several senders"):
            _draft_to(world, answers=answers)


def test_a_case_without_repaired_mail_drafts_as_before(world: World) -> None:
    assert _draft_to(world, answers=1) == HARJOT  # the latest inbound sender, as before the repair


def test_the_draft_guard_also_sees_repaired_mail_that_only_shares_the_thread(world: World) -> None:
    _run(world, apply=True)
    with Session(world.engine) as s:
        other = Case(company_id=world.company, category=Category.other, urgency=Urgency.low, summary="o")
        s.add(other)
        s.flush()
        own = _stored(s, world.company, other.id, "hist_bbbbbbbbbbbbbbbb", "t-jan", 8, sender="anouk@example.test")
        row = s.get(MessageRow, own)
        assert row is not None
        row.meta = {**row.meta, "message_id": "<a@x>"}
        action = ActionRow(company_id=world.company, case_id=other.id, type=ActionType.reply_draft, rationale="r",
                           context_ref=[], payload={}, status=ActionStatus.approved)  # fmt: skip
        s.add(action)
        s.flush()
        with pytest.raises(SendBlockedError, match="several senders"):
            gmail_draft(s, action, "tekst", "k")
        s.rollback()


def test_send_mode_refuses_a_reply_written_to_someone_else_on_a_repaired_case(world: World) -> None:
    _run(world, apply=True)
    with Session(world.engine) as s:
        jan = s.scalar(select(Person.id).where(Person.company_id == world.company, Person.display_name == "Jan"))
        s.get(Case, world.case).primary_person_id = jan  # type: ignore[union-attr]
        piet_mail = [r.id for r in _rows(s, world) if r.sent_at.minute == 2]
        action = ActionRow(
            company_id=world.company, case_id=world.case, type=ActionType.reply_draft, rationale="r",
            context_ref=piet_mail, payload={"channel": "gmail"}, status=ActionStatus.approved,
        )  # fmt: skip
        s.add(action)
        s.flush()
        with pytest.raises(SendBlockedError, match="several senders"):
            tenant_gmail(s, action, "Beste Piet", "k")
        s.rollback()
