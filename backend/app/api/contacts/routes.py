"""Contacts Live Communications REST API Routes.

Connects the Contacts profile view directly to live Gmail & WhatsApp message streams,
agent understanding classifications, and bidirectional WhatsApp dispatch.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import Engine, or_, select
from sqlalchemy.orm import Session

from app.api.deps import get_engine, get_settings_dep
from app.api.v1.access import require_section
from app.api.v1.auth import Principal, require_session
from app.contracts import ActionType, Channel, Direction
from app.core.logging import get_logger
from app.core.settings import Settings
from app.db.models import ActionRow, CaseLink, ChannelIdentity, MessageRow, Person, UnderstandingRow
from app.pipeline import propose

router = APIRouter(prefix="/api/contacts", tags=["contacts"], dependencies=[Depends(require_section("contacts"))])
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


def _action_to_draft_variants(action: ActionRow | None, labels: list[str]) -> list[DraftVariantItem]:
    if not action or not action.payload or not isinstance(action.payload, dict):
        return []
    variants = action.payload.get("body_variants") or []
    if not variants and action.payload.get("text"):
        variants = [action.payload["text"]]
    elif not variants and action.payload.get("body"):
        variants = [action.payload["body"]]
    return [
        DraftVariantItem(
            id=f"d{i + 1}",
            label=labels[i] if i < len(labels) else f"Option {i + 1}",
            body=str(v).strip(),
        )
        for i, v in enumerate(variants[:3])
        if str(v).strip()
    ]


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
            # Map messages and extract understanding categories + pre-staged AI reply drafts
            mapped_emails: list[ContactEmailItemResponse] = []
            mapped_whatsapp: list[ContactWhatsAppMessageResponse] = []

            msg_ids = [m.id for m in live_messages]
            case_links = (
                session.query(CaseLink)
                .filter(CaseLink.company_id == company_id, CaseLink.message_id.in_(msg_ids))
                .all()
            )
            case_by_msg = {cl.message_id: cl.case_id for cl in case_links}
            case_ids = list(set(case_by_msg.values()))
            draft_conds = [ActionRow.context_ref.overlap(msg_ids)]
            if case_ids:
                draft_conds.append(ActionRow.case_id.in_(case_ids))
            candidate_draft_actions = session.scalars(
                select(ActionRow)
                .where(
                    ActionRow.company_id == company_id,
                    ActionRow.type == ActionType.reply_draft,
                    or_(*draft_conds),
                )
                .order_by(ActionRow.created_at.desc())
            ).all()

            def _find_reply_action(msg_id: UUID) -> ActionRow | None:
                direct = next((a for a in candidate_draft_actions if msg_id in (a.context_ref or [])), None)
                if direct:
                    return direct
                cid = case_by_msg.get(msg_id)
                if cid:
                    return next((a for a in candidate_draft_actions if a.case_id == cid), None)
                return None

            email_labels = [
                "Option 1: Direct Confirmation",
                "Option 2: Clarification / Extra Details",
                "Option 3: Schedule Visit / Appointment",
            ]
            wa_labels = [
                "Option 1: Direct Confirmation",
                "Option 2: Clarification / Extra Details",
                "Option 3: Time Slot Proposal",
            ]

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

                meta_subject = msg.meta.get("subject") if isinstance(msg.meta, dict) else None
                msg_subj = (
                    (str(meta_subject).strip() if meta_subject else None)
                    or getattr(msg, "subject", None)
                    or "(No Subject)"
                )
                msg_body = msg.text or ""

                if msg.channel == Channel.gmail:
                    email_drafts = (
                        _action_to_draft_variants(_find_reply_action(msg.id), email_labels)
                        if msg.direction == Direction.inbound
                        else []
                    )
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
                            draftVariants=email_drafts,
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

            # Look for existing AI reply drafts for the latest inbound WhatsApp message
            suggested_wa_drafts: list[DraftVariantItem] = []
            latest_inbound_wa = next(
                (m for m in live_messages if m.channel == Channel.whatsapp and m.direction == Direction.inbound), None
            )
            if latest_inbound_wa:
                suggested_wa_drafts = _action_to_draft_variants(_find_reply_action(latest_inbound_wa.id), wa_labels)

            return ContactCommunicationsResponse(
                contact_id=contact_id,
                email=next(iter(target_emails), None),
                phone=next(iter(target_phones), None),
                emails=mapped_emails,
                whatsapp_messages=mapped_whatsapp,
                suggested_whatsapp_drafts=suggested_wa_drafts,
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
    settings: Annotated[Settings, Depends(get_settings_dep)],
    principal: Annotated[Principal, Depends(require_session)],
) -> GenerateDraftsResponse:
    """Produces 3 distinct reply drafts: checks existing pipeline ActionRow first, or invokes live Proposer agent."""
    labels = [
        "Option 1: Direct Confirmation",
        "Option 2: Clarification / Extra Details",
        "Option 3: Schedule Visit / Appointment",
    ]

    if _is_uuid(message_id):
        msg_uuid = UUID(message_id)
        company_id = principal.company_id

        # 1. Cache hit check: if no custom guidance was supplied, return existing pipeline proposal immediately
        if not payload.guidance:
            with Session(engine) as session:
                existing_action = session.scalars(
                    select(ActionRow)
                    .where(
                        ActionRow.company_id == company_id,
                        ActionRow.context_ref.contains([msg_uuid]),
                        ActionRow.type == ActionType.reply_draft,
                    )
                    .order_by(ActionRow.created_at.desc())
                ).first()
                if existing_action and existing_action.payload:
                    variants = existing_action.payload.get("body_variants") or []
                    if variants:
                        return GenerateDraftsResponse(
                            message_id=message_id,
                            drafts=[
                                DraftVariantItem(
                                    id=f"d{i + 1}",
                                    label=labels[i] if i < len(labels) else f"Option {i + 1}",
                                    body=v.strip(),
                                )
                                for i, v in enumerate(variants[:3])
                            ],
                        )

        # 2. Trigger Gemini Proposer agent for fresh drafts or custom guidance
        try:
            propose.propose_for_message(engine, settings, msg_uuid, guidance=payload.guidance)
        except Exception as e:
            log.warning("propose_for_email_failed", error=str(e), message_id=message_id)

        # 3. Read newly generated drafts from ActionRow
        with Session(engine) as session:
            new_action = session.scalars(
                select(ActionRow)
                .where(
                    ActionRow.company_id == company_id,
                    ActionRow.context_ref.contains([msg_uuid]),
                    ActionRow.type == ActionType.reply_draft,
                )
                .order_by(ActionRow.created_at.desc())
            ).first()
            if new_action and new_action.payload:
                variants = new_action.payload.get("body_variants") or []
                if variants:
                    return GenerateDraftsResponse(
                        message_id=message_id,
                        drafts=[
                            DraftVariantItem(
                                id=f"d{i + 1}",
                                label=labels[i] if i < len(labels) else f"Option {i + 1}",
                                body=v.strip(),
                            )
                            for i, v in enumerate(variants[:3])
                        ],
                    )

    # 4. Contextual fallback if unlinked or model error
    subject = "uw bericht"
    with Session(engine) as session:
        if _is_uuid(message_id):
            msg = session.scalars(
                select(MessageRow).where(
                    MessageRow.id == UUID(message_id), MessageRow.company_id == principal.company_id
                )
            ).first()
            if msg and msg.meta and msg.meta.get("subject"):
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
    description=(
        "Generates 3 quick chat draft replies for WhatsApp, "
        "checking existing pipeline ActionRow or invoking Proposer agent."
    ),
)
def generate_whatsapp_drafts(
    contact_id: str,
    payload: GenerateDraftsRequest,
    engine: Annotated[Engine, Depends(get_engine)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
    principal: Annotated[Principal, Depends(require_session)],
) -> GenerateDraftsResponse:
    """Produces 3 chat-optimized WhatsApp replies via existing ActionRow or live Proposer agent."""
    company_id = principal.company_id
    labels = [
        "Option 1: Direct Confirmation",
        "Option 2: Clarification / Photo",
        "Option 3: Time Slot Proposal",
    ]
    latest_inbound_msg_id: UUID | None = None

    with Session(engine) as session:
        if _is_uuid(contact_id):
            person_id = UUID(contact_id)
            channels = session.scalars(
                select(ChannelIdentity.identity).where(
                    ChannelIdentity.company_id == company_id,
                    ChannelIdentity.person_id == person_id,
                    ChannelIdentity.channel == Channel.whatsapp,
                )
            ).all()
            if channels:
                msg = session.scalars(
                    select(MessageRow)
                    .where(
                        MessageRow.company_id == company_id,
                        MessageRow.channel == Channel.whatsapp,
                        MessageRow.direction == Direction.inbound,
                        MessageRow.sender_identity.in_(channels),
                    )
                    .order_by(MessageRow.sent_at.desc(), MessageRow.created_at.desc())
                ).first()
                if msg:
                    latest_inbound_msg_id = msg.id

        # 1. Cache hit check: if no custom guidance was supplied, return existing ActionRow immediately
        if latest_inbound_msg_id and not payload.guidance:
            existing_action = session.scalars(
                select(ActionRow)
                .where(
                    ActionRow.company_id == company_id,
                    ActionRow.context_ref.contains([latest_inbound_msg_id]),
                    ActionRow.type == ActionType.reply_draft,
                )
                .order_by(ActionRow.created_at.desc())
            ).first()
            if existing_action and existing_action.payload:
                variants = existing_action.payload.get("body_variants") or []
                if variants:
                    return GenerateDraftsResponse(
                        message_id=str(latest_inbound_msg_id),
                        drafts=[
                            DraftVariantItem(
                                id=f"d{i + 1}",
                                label=labels[i] if i < len(labels) else f"Option {i + 1}",
                                body=v.strip(),
                            )
                            for i, v in enumerate(variants[:3])
                        ],
                    )

    # 2. Trigger Proposer agent for fresh drafts or custom guidance
    if latest_inbound_msg_id:
        try:
            propose.propose_for_message(engine, settings, latest_inbound_msg_id, guidance=payload.guidance)
        except Exception as e:
            log.warning("propose_for_whatsapp_failed", error=str(e), message_id=str(latest_inbound_msg_id))

        with Session(engine) as session:
            new_action = session.scalars(
                select(ActionRow)
                .where(
                    ActionRow.company_id == company_id,
                    ActionRow.context_ref.contains([latest_inbound_msg_id]),
                    ActionRow.type == ActionType.reply_draft,
                )
                .order_by(ActionRow.created_at.desc())
            ).first()
            if new_action and new_action.payload:
                variants = new_action.payload.get("body_variants") or []
                if variants:
                    return GenerateDraftsResponse(
                        message_id=str(latest_inbound_msg_id),
                        drafts=[
                            DraftVariantItem(
                                id=f"d{i + 1}",
                                label=labels[i] if i < len(labels) else f"Option {i + 1}",
                                body=v.strip(),
                            )
                            for i, v in enumerate(variants[:3])
                        ],
                    )

    # 3. Fallback persona chat replies
    drafts = [
        DraftVariantItem(
            id="d1",
            label="Option 1: Direct Confirmation",
            body="Dank voor het bericht! Ik heb het direct genoteerd en ga er vandaag mee aan de slag.",
        ),
        DraftVariantItem(
            id="d2",
            label="Option 2: Clarification / Photo",
            body="Top, dank voor de update! Kun je voor de zekerheid even een duidelijke foto sturen?",
        ),
        DraftVariantItem(
            id="d3",
            label="Option 3: Time Slot Proposal",
            body="Schikt komende woensdagochtend 10:00 uur voor een inspectie ter plaatse?",
        ),
    ]
    return GenerateDraftsResponse(message_id=contact_id, drafts=drafts)
