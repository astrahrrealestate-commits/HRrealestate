"""Importing this package registers every table on `Base.metadata`."""

from app.db.models.dashboard import AgentConversation, AgentTurn, OwnerFeed
from app.db.models.directory import ChannelIdentity, DirectoryImport, Lease, LeaseParty, Person, Unit
from app.db.models.ingestion import AttachmentRow, MessageRow, RawEvent
from app.db.models.ops import MetricSnapshot, ModelCall, Outcome, Timer
from app.db.models.owner import Approval, OwnerOutbox, Send
from app.db.models.pipeline import ActionRevision, ActionRow, Case, CaseEvent, CaseLink, UnderstandingRow
from app.db.models.tenancy import ChannelAccount, Company, GmailSyncState, OwnerAccount
from app.db.models.work import DocumentRow, TaskRow, WaitRow

__all__ = [
    "ActionRevision",
    "ActionRow",
    "AgentConversation",
    "AgentTurn",
    "Approval",
    "AttachmentRow",
    "Case",
    "CaseEvent",
    "CaseLink",
    "ChannelAccount",
    "ChannelIdentity",
    "Company",
    "DirectoryImport",
    "DocumentRow",
    "GmailSyncState",
    "Lease",
    "LeaseParty",
    "MessageRow",
    "MetricSnapshot",
    "ModelCall",
    "Outcome",
    "OwnerAccount",
    "OwnerFeed",
    "OwnerOutbox",
    "Person",
    "RawEvent",
    "Send",
    "TaskRow",
    "Timer",
    "UnderstandingRow",
    "Unit",
    "WaitRow",
]
