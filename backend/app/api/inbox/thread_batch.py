"""Batched read-only loaders for `/api/inbox/threads` and `/api/inbox/stats`."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime
from uuid import UUID

from sqlalchemy import case as sql_case
from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session

from app.context.sender_label import UNASSIGNED_UNIT
from app.context.shown_sender import saved_names, sender_person_ids
from app.contracts import ActionType, CaseState, Channel, Direction, OutboundMode, SenderRole, Urgency
from app.db.enums import ActionStatus, ApprovalStatus, PersonKind, SendStatus
from app.db.models import (
    ActionRow,
    Approval,
    AttachmentRow,
    Case,
    CaseLink,
    ChannelIdentity,
    Company,
    DocumentRow,
    Lease,
    LeaseParty,
    MessageRow,
    Person,
    Send,
    UnderstandingRow,
    Unit,
)
from app.db.models.ingestion import not_chat_only


@dataclass
class ThreadMessagesBatch:
    """Messages and directory basics prefetched in bulk before per-thread assembly."""

    company: Company | None
    company_units: list[tuple[str, str | None]]
    msgs_by_case: dict[UUID, list[MessageRow]]
    people_by_id: dict[UUID, Person]
    units_by_id: dict[UUID, Unit]
    lease_party_ids: set[UUID]
    und_by_msg_id: dict[UUID, UnderstandingRow]
    saved_names: dict[UUID, str]  # message id → the saved contact name of its sender
    sender_person_by_msg: dict[UUID, UUID]  # each case's shown incoming message → who wrote it
    unit_by_person: dict[UUID, str]  # those writers → the flat of their current lease


@dataclass
class ThreadDetailsBatch:
    """Actions, approvals, sends, attachments, and leaseholders prefetched for kept cases."""

    actions_by_case: dict[UUID, list[ActionRow]]
    approvals_by_action: dict[UUID, list[Approval]]
    sends_by_action: dict[UUID, list[Send]]
    attachments_by_msg: dict[UUID, list[AttachmentRow]]
    docs_by_att: dict[UUID, DocumentRow]
    leases_by_unit_key: dict[str, list[tuple[UUID, str, str | None]]]


def _leased_flats(session: Session, company_id: UUID, person_ids: set[UUID]) -> dict[UUID, str]:
    """The flat of each person's current lease (an open-ended one first, as `case_repo.create_case` picks)."""
    if not person_ids:
        return {}
    today = datetime.now(UTC).date()
    rows = session.execute(
        select(LeaseParty.person_id, Unit.address, Unit.label)
        .join(Lease, Lease.id == LeaseParty.lease_id)
        .join(Unit, Unit.id == Lease.unit_id)
        .where(
            LeaseParty.company_id == company_id,
            Lease.company_id == company_id,
            Unit.company_id == company_id,
            LeaseParty.person_id.in_(person_ids),
            (Lease.valid_to.is_(None)) | (Lease.valid_to >= today),
        )
        .order_by(Lease.valid_to.is_(None).desc(), Lease.valid_to.desc(), Lease.valid_from.desc(), Lease.id.desc())
    )
    flats: dict[UUID, str] = {}
    for person_id, address, label in rows:
        flats.setdefault(person_id, address or label)
    return flats


def load_messages_batch(session: Session, company_id: UUID, cases: list[Case]) -> ThreadMessagesBatch:
    """Prefetches messages (including shared thread_ref siblings), people, units, and understanding in 7 queries."""
    company = session.get(Company, company_id)
    company_units = [
        (row[0], row[1])
        for row in session.execute(select(Unit.label, Unit.address).where(Unit.company_id == company_id)).all()
    ]
    if not cases:
        return ThreadMessagesBatch(company, company_units, {}, {}, {}, set(), {}, {}, {}, {})

    case_ids = [c.id for c in cases]
    links = session.scalars(
        select(CaseLink).where(CaseLink.company_id == company_id, CaseLink.case_id.in_(case_ids))
    ).all()
    link_msg_ids_by_case: dict[UUID, list[UUID]] = defaultdict(list)
    initial_msg_ids: set[UUID] = set()
    for link in links:
        link_msg_ids_by_case[link.case_id].append(link.message_id)
        initial_msg_ids.add(link.message_id)

    msgs_by_id: dict[UUID, MessageRow] = {}
    if initial_msg_ids:
        for msg in session.scalars(
            select(MessageRow)
            .where(MessageRow.company_id == company_id, MessageRow.id.in_(initial_msg_ids), not_chat_only())
            .order_by(MessageRow.sent_at.asc())
        ).all():
            msgs_by_id[msg.id] = msg

    thread_refs = {m.thread_ref for m in msgs_by_id.values() if m.thread_ref}
    msgs_by_ref: dict[tuple[Channel, str], list[MessageRow]] = defaultdict(list)
    if thread_refs:
        for msg in session.scalars(
            select(MessageRow)
            .where(MessageRow.company_id == company_id, MessageRow.thread_ref.in_(thread_refs), not_chat_only())
            .order_by(MessageRow.sent_at.asc())
        ).all():
            if msg.thread_ref:
                msgs_by_ref[(msg.channel, msg.thread_ref)].append(msg)

    linked_case_by_msg: dict[UUID, UUID] = {}
    sib_ids = [m.id for rows in msgs_by_ref.values() for m in rows if m.id not in msgs_by_id]
    if sib_ids:
        for mid_row, cid_row in session.execute(
            select(CaseLink.message_id, CaseLink.case_id).where(
                CaseLink.company_id == company_id, CaseLink.message_id.in_(sib_ids)
            )
        ).all():
            linked_case_by_msg.setdefault(mid_row, cid_row)

    msgs_by_case: dict[UUID, list[MessageRow]] = {}
    target_und_msg_ids: set[UUID] = set()
    shown_incoming: list[MessageRow] = []
    epoch = datetime.min.replace(tzinfo=UTC)
    for c in cases:
        seen_ids: set[UUID] = set()
        combined: list[MessageRow] = []
        refs: set[tuple[Channel, str]] = set()
        for mid in link_msg_ids_by_case.get(c.id, ()):
            found_msg = msgs_by_id.get(mid)
            if found_msg is not None and found_msg.id not in seen_ids:
                seen_ids.add(found_msg.id)
                combined.append(found_msg)
                if found_msg.thread_ref:
                    refs.add((found_msg.channel, found_msg.thread_ref))
        for ref in refs:
            for sib in msgs_by_ref.get(ref, ()):
                owner_case = linked_case_by_msg.get(sib.id)
                if owner_case is not None and owner_case != c.id:
                    continue
                if sib.id not in seen_ids:
                    seen_ids.add(sib.id)
                    combined.append(sib)
        if not combined:
            continue
        combined.sort(key=lambda m: m.sent_at or epoch)
        msgs_by_case[c.id] = combined
        inbound_msgs = [m for m in combined if m.direction != Direction.outbound]
        tenant_msg = inbound_msgs[-1] if inbound_msgs else combined[0]
        shown_incoming.extend(inbound_msgs[-1:])
        target_und_msg_ids.add(tenant_msg.id)
        target_und_msg_ids.add(combined[-1].id)

    sender_person_by_msg = sender_person_ids(session, company_id, shown_incoming)
    writers = set(sender_person_by_msg.values())
    person_ids = {c.primary_person_id for c in cases if c.primary_person_id} | writers
    unit_ids = {c.unit_id for c in cases if c.unit_id}

    people_by_id: dict[UUID, Person] = {}
    lease_party_ids: set[UUID] = set()
    if person_ids:
        people_by_id = {
            p.id: p
            for p in session.scalars(
                select(Person).where(Person.company_id == company_id, Person.id.in_(person_ids))
            ).all()
        }
        lease_party_ids = set(
            session.scalars(
                select(LeaseParty.person_id).where(
                    LeaseParty.company_id == company_id, LeaseParty.person_id.in_(person_ids)
                )
            ).all()
        )

    units_by_id: dict[UUID, Unit] = {}
    if unit_ids:
        units_by_id = {
            u.id: u
            for u in session.scalars(select(Unit).where(Unit.company_id == company_id, Unit.id.in_(unit_ids))).all()
        }

    und_by_msg_id: dict[UUID, UnderstandingRow] = {}
    if target_und_msg_ids:
        for und in session.scalars(
            select(UnderstandingRow).where(
                UnderstandingRow.company_id == company_id, UnderstandingRow.message_id.in_(target_und_msg_ids)
            )
        ).all():
            und_by_msg_id[und.message_id] = und

    return ThreadMessagesBatch(
        company=company,
        company_units=company_units,
        msgs_by_case=msgs_by_case,
        people_by_id=people_by_id,
        units_by_id=units_by_id,
        lease_party_ids=lease_party_ids,
        und_by_msg_id=und_by_msg_id,
        saved_names=saved_names(session, company_id, [m for rows in msgs_by_case.values() for m in rows]),
        sender_person_by_msg=sender_person_by_msg,
        unit_by_person=_leased_flats(session, company_id, writers),
    )


def load_details_batch(
    session: Session,
    company_id: UUID,
    case_ids: list[UUID],
    msg_ids: list[UUID],
    unit_labels: set[str],
    today: date,
) -> ThreadDetailsBatch:
    """Prefetches actions, approvals, sends, attachments, documents, and active leaseholders for kept threads."""
    if not case_ids:
        return ThreadDetailsBatch({}, {}, {}, {}, {}, {})

    actions_by_case: dict[UUID, list[ActionRow]] = defaultdict(list)
    reply_action_ids: list[UUID] = []
    all_action_ids: list[UUID] = []
    for act in session.scalars(
        select(ActionRow)
        .where(ActionRow.company_id == company_id, ActionRow.case_id.in_(case_ids))
        .order_by(ActionRow.created_at.desc())
    ).all():
        actions_by_case[act.case_id].append(act)
        all_action_ids.append(act.id)
        if act.type == ActionType.reply_draft:
            reply_action_ids.append(act.id)

    approvals_by_action: dict[UUID, list[Approval]] = defaultdict(list)
    if reply_action_ids:
        for ap in session.scalars(
            select(Approval)
            .where(Approval.company_id == company_id, Approval.action_id.in_(reply_action_ids))
            .order_by(Approval.created_at.desc())
        ).all():
            approvals_by_action[ap.action_id].append(ap)

    sends_by_action: dict[UUID, list[Send]] = defaultdict(list)
    if all_action_ids:
        for snd in session.scalars(
            select(Send)
            .where(Send.company_id == company_id, Send.action_id.in_(all_action_ids))
            .order_by(Send.attempted_at.asc())
        ).all():
            if snd.action_id is not None:
                sends_by_action[snd.action_id].append(snd)

    attachments_by_msg: dict[UUID, list[AttachmentRow]] = defaultdict(list)
    att_ids: list[UUID] = []
    if msg_ids:
        for att in session.scalars(
            select(AttachmentRow).where(AttachmentRow.company_id == company_id, AttachmentRow.message_id.in_(msg_ids))
        ).all():
            attachments_by_msg[att.message_id].append(att)
            att_ids.append(att.id)

    docs_by_att: dict[UUID, DocumentRow] = {}
    if att_ids:
        for doc in session.scalars(
            select(DocumentRow).where(DocumentRow.company_id == company_id, DocumentRow.attachment_id.in_(att_ids))
        ).all():
            if doc.attachment_id is not None and doc.attachment_id not in docs_by_att:
                docs_by_att[doc.attachment_id] = doc

    leases_by_unit_key: dict[str, list[tuple[UUID, str, str | None]]] = defaultdict(list)
    wanted_labels = {lbl for lbl in unit_labels if lbl and lbl != UNASSIGNED_UNIT}
    if wanted_labels:
        rows = session.execute(
            select(Unit.label, Unit.address, Person.id, Person.display_name, ChannelIdentity.identity)
            .select_from(Lease)
            .join(Unit, Unit.id == Lease.unit_id)
            .join(LeaseParty, LeaseParty.lease_id == Lease.id)
            .join(Person, Person.id == LeaseParty.person_id)
            .outerjoin(
                ChannelIdentity,
                (ChannelIdentity.person_id == Person.id) & (ChannelIdentity.valid_to.is_(None)),
            )
            .where(
                Unit.company_id == company_id,
                (Unit.label.in_(wanted_labels)) | (Unit.address.in_(wanted_labels)),
                (Lease.valid_to.is_(None)) | (Lease.valid_to >= today),
            )
        ).all()
        for u_label, u_address, pid, pname, ident in rows:
            item = (pid, pname, ident)
            if u_label in wanted_labels:
                leases_by_unit_key[u_label].append(item)
            if u_address and u_address in wanted_labels and u_address != u_label:
                leases_by_unit_key[u_address].append(item)

    return ThreadDetailsBatch(
        actions_by_case=actions_by_case,
        approvals_by_action=approvals_by_action,
        sends_by_action=sends_by_action,
        attachments_by_msg=attachments_by_msg,
        docs_by_att=docs_by_att,
        leases_by_unit_key=leases_by_unit_key,
    )


def inbox_stats_counts(session: Session, company_id: UUID) -> dict[str, int]:
    """Computes fast SQL aggregate stats for inbox navigation badges without fetching message bodies."""
    latest_inbound_at = (
        select(func.max(MessageRow.sent_at))
        .join(CaseLink, CaseLink.message_id == MessageRow.id)
        .where(
            CaseLink.case_id == Case.id,
            MessageRow.company_id == company_id,
            MessageRow.direction != Direction.outbound,
            not_chat_only(),
        )
        .correlate(Case)
        .scalar_subquery()
    )
    latest_outbound_at = (
        select(func.max(MessageRow.sent_at))
        .join(CaseLink, CaseLink.message_id == MessageRow.id)
        .where(
            CaseLink.case_id == Case.id,
            MessageRow.company_id == company_id,
            MessageRow.direction == Direction.outbound,
            not_chat_only(),
        )
        .correlate(Case)
        .scalar_subquery()
    )
    has_outbound = latest_outbound_at.is_not(None) & (
        latest_inbound_at.is_(None) | (latest_outbound_at >= latest_inbound_at)
    )
    has_sent_reply = exists(
        select(1)
        .select_from(ActionRow)
        .join(Send, Send.action_id == ActionRow.id)
        .join(Company, Company.id == ActionRow.company_id)
        .where(
            ActionRow.case_id == Case.id,
            ActionRow.company_id == company_id,
            ActionRow.type == ActionType.reply_draft,
            Send.status == SendStatus.sent,
            Send.channel != Channel.dashboard,
            Company.outbound_mode == OutboundMode.send,
        )
    )
    has_pending_reply_approval = exists(
        select(1)
        .select_from(ActionRow)
        .join(
            Approval,
            (Approval.action_id == ActionRow.id) & (Approval.draft_version == ActionRow.draft_version),
        )
        .where(
            ActionRow.case_id == Case.id,
            ActionRow.company_id == company_id,
            ActionRow.type == ActionType.reply_draft,
            Approval.status == ApprovalStatus.pending,
        )
    )
    has_decided_approval = exists(
        select(1)
        .select_from(ActionRow)
        .join(Approval, Approval.action_id == ActionRow.id)
        .where(
            ActionRow.case_id == Case.id,
            ActionRow.company_id == company_id,
            ActionRow.type == ActionType.reply_draft,
            Approval.status.in_((ApprovalStatus.approved, ApprovalStatus.rejected)),
        )
    )
    has_whatsapp = exists(
        select(1)
        .select_from(CaseLink)
        .join(MessageRow, MessageRow.id == CaseLink.message_id)
        .where(
            CaseLink.case_id == Case.id,
            MessageRow.company_id == company_id,
            MessageRow.channel == Channel.whatsapp,
            not_chat_only(),
        )
    )
    has_gmail = exists(
        select(1)
        .select_from(CaseLink)
        .join(MessageRow, MessageRow.id == CaseLink.message_id)
        .where(
            CaseLink.case_id == Case.id,
            MessageRow.company_id == company_id,
            MessageRow.channel == Channel.gmail,
        )
    )
    is_contractor = exists(
        select(1)
        .select_from(Person)
        .where(
            Person.id == Case.primary_person_id,
            Person.company_id == company_id,
            Person.kind == PersonKind.contractor,
        )
    )
    contractor_role = exists(
        select(1)
        .select_from(CaseLink)
        .join(UnderstandingRow, UnderstandingRow.message_id == CaseLink.message_id)
        .where(
            CaseLink.case_id == Case.id,
            UnderstandingRow.company_id == company_id,
            UnderstandingRow.body["sender_role"].astext == SenderRole.contractor.value,
        )
    )
    is_tenant = exists(
        select(1)
        .select_from(Person)
        .where(
            Person.id == Case.primary_person_id,
            Person.company_id == company_id,
            Person.kind == PersonKind.tenant,
        )
    )
    has_pending_action = exists(
        select(1)
        .select_from(ActionRow)
        .where(
            ActionRow.case_id == Case.id,
            ActionRow.company_id == company_id,
            ActionRow.status.in_((ActionStatus.pending_approval, ActionStatus.exception)),
        )
    )
    latest_inbound_msg = (
        select(MessageRow.id)
        .join(CaseLink, CaseLink.message_id == MessageRow.id)
        .where(
            CaseLink.case_id == Case.id,
            MessageRow.company_id == company_id,
            MessageRow.direction != Direction.outbound,
            not_chat_only(),
        )
        .order_by(MessageRow.sent_at.desc(), MessageRow.id.desc())
        .limit(1)
        .correlate(Case)
        .scalar_subquery()
    )
    is_fyi_case = (~has_pending_action) & exists(
        select(1)
        .select_from(UnderstandingRow)
        .where(
            UnderstandingRow.company_id == company_id,
            UnderstandingRow.message_id == latest_inbound_msg,
            UnderstandingRow.body["requires_reply"].astext == "false",
        )
    )
    needs_you_cond = (
        Case.state.notin_((CaseState.closed, CaseState.resolved))
        & ~has_outbound
        & (has_pending_reply_approval | (~has_sent_reply & ~has_decided_approval & ~is_fyi_case))
    )

    row = session.execute(
        select(
            func.count(Case.id),
            func.sum(sql_case((needs_you_cond, 1), else_=0)),
            func.sum(sql_case((Case.urgency.in_((Urgency.high, Urgency.emergency)), 1), else_=0)),
            func.sum(sql_case((is_tenant, 1), else_=0)),
            func.sum(
                sql_case(
                    (
                        is_contractor | contractor_role,
                        1,
                    ),
                    else_=0,
                )
            ),
            func.sum(sql_case((has_whatsapp, 1), else_=0)),
            func.sum(sql_case((has_gmail, 1), else_=0)),
        ).where(Case.company_id == company_id)
    ).one()

    return {
        "allCount": int(row[0] or 0),
        "needsYouCount": int(row[1] or 0),
        "urgentCount": int(row[2] or 0),
        "tenantsCount": int(row[3] or 0),
        "contractorsCount": int(row[4] or 0),
        "whatsappCount": int(row[5] or 0),
        "gmailCount": int(row[6] or 0),
    }
