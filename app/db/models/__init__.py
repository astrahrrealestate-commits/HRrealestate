"""Importing this package registers every table on `Base.metadata`."""

from app.db.models.brixx import BrixxSyncRun, BrixxSyncTableState
from app.db.models.calendar import CalendarEventRow
from app.db.models.dashboard import AgentConversation, AgentPageState, AgentTurn, OwnerFeed
from app.db.models.diligence import DDDocumentRead, DDReview, DDReviewDocument
from app.db.models.directory import ChannelIdentity, DirectoryImport, Lease, LeaseParty, Person, PersonProfile, Unit
from app.db.models.documents import DocumentChunk, DocumentLink, DriveReorgItem, DriveReorgPlan
from app.db.models.finance import PriceSnapshot, QuoteLineRow, QuoteReview, QuoteRow, VendorRate
from app.db.models.ingestion import AttachmentRow, MessageRow, RawEvent
from app.db.models.memory import MemoryItem
from app.db.models.message_rag import MessageChunk, MessageIndexState
from app.db.models.ops import MetricSnapshot, ModelCall, Outcome, Timer
from app.db.models.owner import Approval, OwnerOutbox, OwnerPersona, Send
from app.db.models.pipeline import ActionRevision, ActionRow, Case, CaseEvent, CaseLink, UnderstandingRow
from app.db.models.tenancy import ChannelAccount, Company, GmailSyncState, OwnerAccount
from app.db.models.work import DocumentRow, TaskRow, WaitRow

__all__ = [
    "ActionRevision",
    "ActionRow",
    "AgentConversation",
    "AgentPageState",
    "AgentTurn",
    "Approval",
    "AttachmentRow",
    "BrixxSyncRun",
    "BrixxSyncTableState",
    "CalendarEventRow",
    "Case",
    "CaseEvent",
    "CaseLink",
    "ChannelAccount",
    "ChannelIdentity",
    "Company",
    "DDDocumentRead",
    "DDReview",
    "DDReviewDocument",
    "DirectoryImport",
    "DocumentChunk",
    "DocumentLink",
    "DocumentRow",
    "DriveReorgItem",
    "DriveReorgPlan",
    "GmailSyncState",
    "Lease",
    "LeaseParty",
    "MemoryItem",
    "MessageChunk",
    "MessageIndexState",
    "MessageRow",
    "MetricSnapshot",
    "ModelCall",
    "Outcome",
    "OwnerAccount",
    "OwnerFeed",
    "OwnerOutbox",
    "OwnerPersona",
    "Person",
    "PersonProfile",
    "PriceSnapshot",
    "QuoteLineRow",
    "QuoteReview",
    "QuoteRow",
    "RawEvent",
    "Send",
    "TaskRow",
    "Timer",
    "UnderstandingRow",
    "Unit",
    "VendorRate",
    "WaitRow",
]
