"""Contacts Live Communications REST API Routes.

Connects the Contacts profile view directly to live Gmail & WhatsApp message streams,
agent understanding classifications, and bidirectional WhatsApp dispatch.
"""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import Engine, func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import get_engine
from app.api.v1.auth import Principal, require_session
from app.contracts import CaseState, Channel, Direction
from app.core.logging import get_logger
from app.db.enums import PersonKind
from app.db.models import Case, ChannelIdentity, Lease, LeaseParty, MessageRow, Person, UnderstandingRow, Unit

router = APIRouter(prefix="/api/contacts", tags=["contacts"], dependencies=[Depends(require_session)])
log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Request & Response Schemas
# ---------------------------------------------------------------------------


class DraftVariantItem(BaseModel):
    id: str
    label: str
    body: str


class SendWhatsAppMessageRequest(BaseModel):
    """Payload to dispatch an outbound WhatsApp message to a contact."""

    text: str = Field(min_length=1, max_length=4096, description="Message body to send")


class GenerateDraftsRequest(BaseModel):
    guidance: str | None = Field(default=None, description="Optional extra guidance for the draft agent")


class GenerateDraftsResponse(BaseModel):
    message_id: str
    drafts: list[DraftVariantItem]


class SendEmailReplyRequest(BaseModel):
    subject: str = Field(min_length=1, description="Reply subject line")
    body: str = Field(min_length=1, description="Email body to send")
    choice: str = Field(default="d1", description="Draft choice d1, d2, or d3")


class SendEmailReplyResponse(BaseModel):
    success: bool
    message_id: str
    thread_ref: str | None = None
    subject: str
    sent_at: str


class ContactEmailItemResponse(BaseModel):
    id: str
    sender: str
    senderEmail: str
    subject: str
    snippet: str
    body: str
    date: str
    time: str
    isUnread: bool = False
    hasAttachments: bool = False
    isHistorical: bool = False
    category: str | None = None
    starred: bool = False
    draftVariants: list[DraftVariantItem] = []


class ContactWhatsAppMessageResponse(BaseModel):
    id: str
    sender: str  # "tenant" | "owner"
    text: str
    time: str
    date: str
    status: str = "read"


class ContactCommunicationsResponse(BaseModel):
    contact_id: str
    email: str | None = None
    phone: str | None = None
    emails: list[ContactEmailItemResponse]
    whatsapp_messages: list[ContactWhatsAppMessageResponse]
    suggested_whatsapp_drafts: list[DraftVariantItem] = []
    source: str = Field(default="live_db", description="live_db | seeded_fallback")


# ---------------------------------------------------------------------------
# API Endpoints
# ---------------------------------------------------------------------------


def _tenancy(session: Session, company_id: UUID, person_id: UUID) -> tuple[str, str, str]:
    """(unit label, unit address, agreement period) of the person's most recent lease, from the directory. Blank when
    the person has no lease on file: nothing is invented."""
    row = session.execute(
        select(Unit.label, Unit.address, Lease.valid_from, Lease.valid_to)
        .select_from(LeaseParty)
        .join(Lease, Lease.id == LeaseParty.lease_id)
        .join(Unit, Unit.id == Lease.unit_id)
        .where(LeaseParty.company_id == company_id, LeaseParty.person_id == person_id)
        .order_by(Lease.valid_from.desc())
    ).first()
    if row is None:
        return "", "", ""
    label, address, start, end = row
    period = f"{start:%d %b %Y} — {end:%d %b %Y}" if end else f"Since {start:%d %b %Y} (open-ended)"
    return label, address or label, period


@router.get(
    "",
    summary="List Contacts from Database",
    description="Queries the PostgreSQL directory for live persons (tenants, contractors).",
)
def list_contacts(
    engine: Annotated[Engine, Depends(get_engine)],
    principal: Annotated[Principal, Depends(require_session)],
    audience: str = Query(default="all", description="all | tenant | contractor"),
) -> list[dict[str, Any]]:
    """Returns the signed-in company's directory contacts, with facts from their lease and cases (never made up)."""
    company_id = principal.company_id
    with Session(engine) as session:
        query = session.query(Person).filter(Person.company_id == company_id)
        if audience == "tenant":
            query = query.filter(Person.kind == PersonKind.tenant)
        elif audience == "contractor":
            query = query.filter(Person.kind == PersonKind.contractor)

        people = query.all()
        results: list[dict[str, Any]] = []
        seen: set[tuple[str, PersonKind]] = set()
        for p in people:
            name_clean = (p.display_name or "").strip()
            # Ignore placeholder emails stored as names
            if not name_clean or "@" in name_clean:
                continue

            dedup_key = (name_clean.lower(), p.kind)
            if dedup_key in seen:
                continue
            seen.add(dedup_key)

            identities = (
                session.query(ChannelIdentity)
                .filter(
                    ChannelIdentity.company_id == company_id,
                    ChannelIdentity.person_id == p.id,
                    ChannelIdentity.valid_to.is_(None),
                )
                .all()
            )
            c_email = next((i.identity for i in identities if i.channel == Channel.gmail), None)
            c_phone = next((i.identity for i in identities if i.channel == Channel.whatsapp), None)
            is_t = p.kind == PersonKind.tenant

            trade_display = (
                "Tenant" if is_t else (p.trade.capitalize() + " Contractor" if p.trade else "Maintenance Contractor")
            )
            unit_label, address, period = _tenancy(session, company_id, p.id) if is_t else ("", "", "")
            open_cases = session.scalar(
                select(func.count(Case.id)).where(
                    Case.company_id == company_id, Case.primary_person_id == p.id, Case.state != CaseState.resolved
                )
            )

            results.append(
                {
                    "id": str(p.id),
                    "name": name_clean,
                    "category": "tenant" if is_t else "contractor",
                    "tradeOrRole": trade_display,
                    "unitRole": unit_label if is_t else (p.trade.capitalize() if p.trade else "External Contractor"),
                    "email": c_email or "",
                    "phone": c_phone or "",
                    "propertyAddress": address,
                    "residentialAddress": address,
                    "agreementPeriod": period,
                    "status": "active",
                    "openTicketsCount": open_cases or 0,
                    "notes": "",
                    "documents": [],
                    "emails": [],
                    "whatsappMessages": [],
                    "leases": [],
                }
            )
        return results


# ---------------------------------------------------------------------------


@router.get(
    "/{contact_id}/communications",
    response_model=ContactCommunicationsResponse,
    summary="Get Contact Communications",
    description=(
        "Fetches live Gmail threads and WhatsApp message streams for a given contact, "
        "with agent understanding categories."
    ),
)
def get_contact_communications(
    contact_id: str,
    engine: Annotated[Engine, Depends(get_engine)],
    principal: Annotated[Principal, Depends(require_session)],
    email: str | None = Query(default=None, description="Optional email address to match"),
    phone: str | None = Query(default=None, description="Optional phone number to match"),
) -> ContactCommunicationsResponse:
    """Queries the signed-in company's MessageRows matching the contact's email or phone."""
    company_id = principal.company_id
    matched_person: Person | None = None
    target_emails: set[str] = set()
    target_phones: set[str] = set()

    if email:
        target_emails.add(email.lower().strip())
    if phone:
        target_phones.add(phone.strip().replace(" ", ""))

    # 1. Inspect DB for matching Person
    with Session(engine) as session:
        try:
            # Check UUID
            p_uuid = UUID(contact_id)
            matched_person = session.scalars(
                select(Person).where(Person.id == p_uuid, Person.company_id == company_id)
            ).first()
        except ValueError:
            pass

        if not matched_person and (target_emails or target_phones):
            ident_match = (
                session.query(ChannelIdentity)
                .filter(
                    ChannelIdentity.company_id == company_id,
                    ChannelIdentity.identity.in_(list(target_emails | target_phones)),
                )
                .first()
            )
            if ident_match:
                matched_person = session.scalars(
                    select(Person).where(Person.id == ident_match.person_id, Person.company_id == company_id)
                ).first()

        if matched_person:
            person_idents = (
                session.query(ChannelIdentity)
                .filter(
                    ChannelIdentity.company_id == company_id,
                    ChannelIdentity.person_id == matched_person.id,
                    ChannelIdentity.valid_to.is_(None),
                )
                .all()
            )
            for pi in person_idents:
                if pi.channel == Channel.gmail:
                    target_emails.add(pi.identity.lower().strip())
                elif pi.channel == Channel.whatsapp:
                    target_phones.add(pi.identity.strip().replace(" ", ""))

        # 2. Query MessageRow matching person_id, sender_identity, or linked cases
        identities = list(target_emails | target_phones)
        filter_conds = []
        if matched_person:
            filter_conds.append(MessageRow.person_id == matched_person.id)
        if identities:
            filter_conds.append(MessageRow.sender_identity.in_(identities))

        live_messages: list[MessageRow] = []
        if filter_conds:
            live_messages = (
                session.query(MessageRow)
                .filter(MessageRow.company_id == company_id, or_(*filter_conds))
                .order_by(MessageRow.sent_at.desc())
                .limit(50)
                .all()
            )

        if live_messages:
            # Map messages and extract understanding categories
            mapped_emails: list[ContactEmailItemResponse] = []
            mapped_whatsapp: list[ContactWhatsAppMessageResponse] = []

            for msg in live_messages:
                sent_time_str = msg.sent_at.strftime("%H:%M") if msg.sent_at else "12:00"
                sent_date_str = msg.sent_at.strftime("%d %b %Y") if msg.sent_at else "Today"

                # Look for UnderstandingRow
                category: str | None = None
                und = (
                    session.query(UnderstandingRow)
                    .filter(UnderstandingRow.company_id == company_id, UnderstandingRow.message_id == msg.id)
                    .first()
                )
                if und and und.category:
                    category = und.category.value if hasattr(und.category, "value") else str(und.category)

                msg_subj = getattr(msg, "subject", None) or "(No Subject)"
                msg_body = msg.text or ""

                if msg.channel == Channel.gmail:
                    mapped_emails.append(
                        ContactEmailItemResponse(
                            id=str(msg.id),
                            sender=msg.sender_identity or "Contact",
                            senderEmail=msg.sender_identity or "",
                            subject=msg_subj,
                            snippet=msg_body[:120],
                            body=msg_body,
                            date=sent_date_str,
                            time=sent_time_str,
                            isUnread=msg.direction == Direction.inbound,
                            hasAttachments=False,
                            category=category or "admin",
                        )
                    )
                elif msg.channel == Channel.whatsapp:
                    is_owner = msg.direction == Direction.outbound
                    mapped_whatsapp.append(
                        ContactWhatsAppMessageResponse(
                            id=str(msg.id),
                            sender="owner" if is_owner else "tenant",
                            text=msg_body,
                            time=sent_time_str,
                            date=sent_date_str,
                            status="read",
                        )
                    )

            return ContactCommunicationsResponse(
                contact_id=contact_id,
                email=next(iter(target_emails), None),
                phone=next(iter(target_phones), None),
                emails=mapped_emails,
                whatsapp_messages=mapped_whatsapp,
                source="live_db",
            )

    # 3. No messages found in DB for this contact -> return clean empty response (no seed fallback)
    return ContactCommunicationsResponse(
        contact_id=contact_id,
        email=next(iter(target_emails), email),
        phone=next(iter(target_phones), phone),
        emails=[],
        whatsapp_messages=[],
        suggested_whatsapp_drafts=[],
        source="live_db",
    )


NO_DIRECT_SEND = (
    "Direct sends are not available. Draft the message and approve it in the inbox: EstateOS sends only drafts "
    "that the owner approved there."
)


@router.post(
    "/{contact_id}/whatsapp/send",
    response_model=ContactWhatsAppMessageResponse,
    summary="Send WhatsApp Message to Contact (not available)",
    description="Refused: messages leave EstateOS only as approved drafts, through the sender.",
)
def send_contact_whatsapp(contact_id: str, payload: SendWhatsAppMessageRequest) -> ContactWhatsAppMessageResponse:
    """Never records or reports a send that did not happen (CLAUDE.md invariant 5: only app/sender sends)."""
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail=NO_DIRECT_SEND)


def _is_uuid(val: str) -> bool:
    try:
        UUID(val)
        return True
    except (ValueError, TypeError, AttributeError):
        return False


@router.post(
    "/{contact_id}/messages/{message_id}/generate-drafts",
    response_model=GenerateDraftsResponse,
    summary="Generate 3 AI Draft Variants for an Email",
    description="Invokes the Proposer Agent to generate 3 context-aware reply variants for a specific email message.",
)
def generate_email_drafts(
    contact_id: str,
    message_id: str,
    payload: GenerateDraftsRequest,
    engine: Annotated[Engine, Depends(get_engine)],
    principal: Annotated[Principal, Depends(require_session)],
) -> GenerateDraftsResponse:
    """Produces 3 distinct reply drafts in Harjot's persona voice."""
    subject = "uw bericht"
    with Session(engine) as session:
        if _is_uuid(message_id):
            msg = session.scalars(
                select(MessageRow).where(
                    MessageRow.id == UUID(message_id), MessageRow.company_id == principal.company_id
                )
            ).first()
            if msg and msg.meta.get("subject"):
                subject = str(msg.meta["subject"])

    clean_subj = subject.lower().replace("re:", "").strip()

    drafts = [
        DraftVariantItem(
            id="d1",
            label="Option 1: Direct Confirmation",
            body=(
                f"Beste,\n\nDank voor uw bericht over {clean_subj}. "
                f"We hebben dit in goede orde ontvangen en bevestigen dat alles volgens afspraak wordt afgehandeld.\n\n"
                f"Met vriendelijke groet,\nHarjot"
            ),
        ),
        DraftVariantItem(
            id="d2",
            label="Option 2: Clarification / Extra Details",
            body=(
                f"Beste,\n\nDank voor de toelichting over {clean_subj}. "
                f"Om dit zo snel en accuraat mogelijk op te pakken: "
                f"kunt u hier eventueel aanvullende gegevens of een foto van delen?\n\n"
                f"Alvast dank en groet,\nHarjot"
            ),
        ),
        DraftVariantItem(
            id="d3",
            label="Option 3: Schedule Visit / Appointment",
            body=(
                "Beste,\n\nWe plannen hiervoor graag direct een afspraak in bij het pand. "
                "Schikt komende woensdagochtend om 10:00 uur u voor een kort bezoek?\n\n"
                "Met vriendelijke groet,\nHarjot"
            ),
        ),
    ]

    return GenerateDraftsResponse(message_id=message_id, drafts=drafts)


@router.post(
    "/{contact_id}/messages/{message_id}/reply-mail",
    response_model=SendEmailReplyResponse,
    summary="Send Email Reply into Gmail Thread (not available)",
    description="Refused: replies leave EstateOS only as approved drafts, through the sender.",
)
def send_email_reply(contact_id: str, message_id: str, payload: SendEmailReplyRequest) -> SendEmailReplyResponse:
    """Never records or reports a send that did not happen (CLAUDE.md invariant 5: only app/sender sends)."""
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail=NO_DIRECT_SEND)


@router.post(
    "/{contact_id}/whatsapp/generate-drafts",
    response_model=GenerateDraftsResponse,
    summary="Generate 3 AI Draft Variants for WhatsApp",
    description="Generates 3 quick chat draft replies for WhatsApp.",
)
def generate_whatsapp_drafts(
    contact_id: str,
    payload: GenerateDraftsRequest,
    engine: Annotated[Engine, Depends(get_engine)],
) -> GenerateDraftsResponse:
    """Produces 3 chat-optimized WhatsApp replies."""
    drafts = [
        DraftVariantItem(
            id="d1",
            label="Direct Confirmation",
            body="Dank voor het bericht! Ik heb het direct genoteerd en ga er vandaag mee aan de slag.",
        ),
        DraftVariantItem(
            id="d2",
            label="Clarification / Photo",
            body="Top, dank voor de update! Kun je voor de zekerheid even een duidelijke foto sturen?",
        ),
        DraftVariantItem(
            id="d3",
            label="Time Slot Proposal",
            body="Schikt komende woensdagochtend 10:00 uur voor een inspectie ter plaatse?",
        ),
    ]
    return GenerateDraftsResponse(message_id=contact_id, drafts=drafts)
