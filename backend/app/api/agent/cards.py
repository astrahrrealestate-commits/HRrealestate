"""What a Super Agent answer shows besides its text: preview cards, the assistant cards built from them, and buttons.

Shared by the ask route and the plan-step answers in `intent_responses` (which the route imports, so these shapes
cannot live in the route module).
"""

from typing import Any

from pydantic import BaseModel, Field


class CardActionData(BaseModel):
    label: str
    kind: str = Field(default="api_call", description="api_call | navigate | open_external")
    endpoint: str | None = None
    method: str = "POST"
    payload: dict[str, Any] | None = None
    targetUrl: str | None = None
    variant: str = "primary"  # primary | secondary | danger | whatsapp | gmail


class AssistantCardData(BaseModel):
    id: str
    type: (
        str  # draft_message | case_summary | financial_item | calendar_item | document_item | memory_item | data_table
    )
    badgeLabel: str
    badgeColor: str = "orange"
    title: str
    subtitle: str | None = None
    body: str | None = None
    amount: str | None = None
    contractor: str | None = None
    dueDate: str | None = None
    status: str | None = None
    unitLabel: str | None = None
    recipient: str | None = None
    channel: str | None = None
    actions: list[CardActionData] = Field(default_factory=list)
    externalUrl: str | None = None
    threadSearchUrl: str | None = None
    targetUrl: str | None = None
    caseId: str | None = None
    actionId: str | None = None
    columns: list[str] = Field(default_factory=list)
    rows: list[dict[str, Any]] = Field(default_factory=list)
    totalCount: int | None = None
    phone: str | None = None
    email: str | None = None
    leaseStart: str | None = None
    leaseEnd: str | None = None


class PreviewCardData(BaseModel):
    type: str = Field(
        default="draft_message",
        description=(
            "Type of card: draft_message, case_summary, data_table, tenant_lease, financial_item, "
            "calendar_item, document_item, memory_item, notice"
        ),
    )
    channel: str | None = Field(default=None, description="whatsapp | gmail | internal")
    recipient: str = Field(default="", description="Recipient phone or email")
    unitLabel: str = Field(default="", description="Target property/unit address")
    subject: str | None = None
    body: str = Field(default="", description="The drafted text content")
    actionId: str | None = None
    caseId: str | None = None
    title: str | None = None
    subtitle: str | None = None
    badgeLabel: str | None = None
    badgeColor: str | None = None
    amount: str | None = None
    status: str | None = None
    dueDate: str | None = None
    contractor: str | None = None
    targetUrl: str | None = None
    externalUrl: str | None = None
    threadSearchUrl: str | None = None
    variants: list[str] = Field(default_factory=list, description="All body variants for draft switcher")
    personaName: str | None = Field(default=None, description="Owner persona the draft was written in")
    personaVersion: int | None = None
    columns: list[str] = Field(default_factory=list)
    rows: list[dict[str, Any]] = Field(default_factory=list)
    totalCount: int | None = None
    phone: str | None = None
    email: str | None = None
    leaseStart: str | None = None
    leaseEnd: str | None = None


class ActionButtonData(BaseModel):
    label: str
    actionType: str = Field(default="navigate", description="navigate | approve_action | query")
    payload: str | None = None
    isPrimary: bool = False


def build_cards_list(target_cards: list[PreviewCardData]) -> list[AssistantCardData]:
    """Convert PreviewCardData models into polymorphic AssistantCardData models."""
    cards_list: list[AssistantCardData] = []
    for p_card in target_cards:
        card_actions: list[CardActionData] = []
        if p_card.type == "draft_message":
            if p_card.status == "pending" or not p_card.status:
                card_actions.append(
                    CardActionData(
                        label="Accept and send",
                        kind="api_call",
                        endpoint=f"/api/inbox/approvals/{p_card.actionId}/decide" if p_card.actionId else None,
                        payload={"decision": "approved"},
                        variant="primary",
                    )
                )
            if p_card.externalUrl:
                label = "Open in WhatsApp" if p_card.channel == "whatsapp" else "Open in Gmail"
                card_actions.append(
                    CardActionData(
                        label=label,
                        kind="open_external",
                        targetUrl=p_card.externalUrl,
                        variant="whatsapp" if p_card.channel == "whatsapp" else "gmail",
                    )
                )
            if p_card.threadSearchUrl:
                label = "View Thread on WhatsApp" if p_card.channel == "whatsapp" else "View Thread in Gmail"
                card_actions.append(
                    CardActionData(
                        label=label,
                        kind="open_external",
                        targetUrl=p_card.threadSearchUrl,
                        variant="secondary",
                    )
                )
            card_actions.append(
                CardActionData(
                    label="Open in Inbox",
                    kind="navigate",
                    targetUrl=p_card.targetUrl
                    or (f"/inbox?thread=case-{p_card.caseId}" if p_card.caseId else "/inbox"),
                    variant="secondary",
                )
            )
        elif p_card.type == "notice":
            card_actions.append(
                CardActionData(
                    label="Review in Inbox",
                    kind="navigate",
                    targetUrl=p_card.targetUrl
                    or (f"/inbox?thread=case-{p_card.caseId}" if p_card.caseId else "/inbox"),
                    variant="primary",
                )
            )
            if p_card.caseId:
                card_actions.append(
                    CardActionData(
                        label="Retry draft",
                        kind="query",
                        payload={"query": f"draft a reply for case {p_card.caseId}"},
                        variant="secondary",
                    )
                )
        elif p_card.type == "case_summary":
            card_actions.append(
                CardActionData(
                    label="Open in Maintenance",
                    kind="navigate",
                    targetUrl=p_card.targetUrl
                    or (f"/maintenance?ticket={p_card.caseId}" if p_card.caseId else "/maintenance"),
                    variant="primary",
                )
            )
        elif p_card.type == "calendar_item":
            card_actions.append(
                CardActionData(
                    label="Approve and Add to Calendar",
                    kind="api_call",
                    endpoint=f"/api/calendar/events/{p_card.actionId}/approve" if p_card.actionId else None,
                    variant="primary",
                )
            )
        elif p_card.type in ("data_table", "tenant_lease"):
            nav_target = p_card.targetUrl or "/tenants"
            nav_labels = {
                "/tenants": "Open Tenants",
                "/maintenance": "Open Maintenance",
                "/calendar": "Open Calendar",
                "/money": "Open Money",
                "/contacts": "Open Contacts",
                "/waiting": "Open Waiting",
                "/documents": "Open Documents",
            }
            nav_label = nav_labels.get(nav_target, "View Details")
            card_actions.append(
                CardActionData(
                    label=nav_label,
                    kind="navigate",
                    targetUrl=nav_target,
                    variant="primary",
                )
            )

        cards_list.append(
            AssistantCardData(
                id=p_card.actionId or p_card.caseId or f"card-{len(cards_list)}",
                type=p_card.type,
                badgeLabel=p_card.badgeLabel or ("DRAFT" if p_card.type == "draft_message" else "TICKET"),
                badgeColor=getattr(p_card, "badgeColor", None) or "orange",
                title=p_card.title or (p_card.unitLabel or "Draft Message"),
                subtitle=p_card.subtitle,
                body=p_card.body,
                amount=p_card.amount,
                contractor=p_card.contractor,
                dueDate=p_card.dueDate,
                status=p_card.status,
                unitLabel=p_card.unitLabel,
                recipient=p_card.recipient,
                channel=p_card.channel,
                actions=card_actions,
                externalUrl=p_card.externalUrl,
                threadSearchUrl=p_card.threadSearchUrl,
                targetUrl=p_card.targetUrl,
                caseId=p_card.caseId,
                actionId=p_card.actionId,
                columns=p_card.columns,
                rows=p_card.rows,
                totalCount=p_card.totalCount,
                phone=p_card.phone,
                email=p_card.email,
                leaseStart=p_card.leaseStart,
                leaseEnd=p_card.leaseEnd,
            )
        )
    return cards_list
