"""The six pipeline contracts (spec §2). Import from here, not from submodules."""

from app.contracts.action import (
    Action,
    ActionPayload,
    ActionType,
    CreateReminderPayload,
    EscalatePayload,
    NotifyOwnerPayload,
    ReplyDraftPayload,
    RequestContractorPayload,
    UpdateCaseStatePayload,
)
from app.contracts.button_id import MAX_BUTTON_ID_LEN, ButtonChoice, ButtonId
from app.contracts.case_state import ALLOWED, CaseState, assert_transition, can_transition
from app.contracts.common import Channel, Contract, Direction, Money
from app.contracts.document import DocType, DocumentClassification
from app.contracts.linking import LinkDecision
from app.contracts.message import Attachment, Message, normalise_identity
from app.contracts.owner_outputs import Briefing, BriefingSection, OwnerAnswer
from app.contracts.prompt_ref import PromptRef
from app.contracts.proposal import Proposal
from app.contracts.summary import CaseSummary
from app.contracts.understanding import Category, Entities, Suspicious, Understanding, Urgency

__all__ = [
    "ALLOWED",
    "MAX_BUTTON_ID_LEN",
    "Action",
    "ActionPayload",
    "ActionType",
    "Attachment",
    "Briefing",
    "BriefingSection",
    "ButtonChoice",
    "ButtonId",
    "CaseState",
    "CaseSummary",
    "Category",
    "Channel",
    "Contract",
    "CreateReminderPayload",
    "Direction",
    "DocType",
    "DocumentClassification",
    "Entities",
    "EscalatePayload",
    "LinkDecision",
    "Message",
    "Money",
    "NotifyOwnerPayload",
    "OwnerAnswer",
    "PromptRef",
    "Proposal",
    "ReplyDraftPayload",
    "RequestContractorPayload",
    "Suspicious",
    "Understanding",
    "UpdateCaseStatePayload",
    "Urgency",
    "assert_transition",
    "can_transition",
    "normalise_identity",
]
