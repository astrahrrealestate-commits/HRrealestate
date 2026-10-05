"""Importing this package registers every table on `Base.metadata`."""

from app.db.models.directory import ChannelIdentity, DirectoryImport, Lease, LeaseParty, Person, Unit
from app.db.models.ingestion import AttachmentRow, MessageRow, RawEvent
from app.db.models.ops import ModelCall, Outcome, Timer
from app.db.models.owner import Approval, Send
from app.db.models.pipeline import ActionRevision, ActionRow, Case, CaseEvent, CaseLink, UnderstandingRow
from app.db.models.tenancy import ChannelAccount, Company, GmailSyncState, OwnerAccount

__all__ = [
    "ActionRevision",
    "ActionRow",
    "Approval",
    "AttachmentRow",
    "Case",
    "CaseEvent",
    "CaseLink",
    "ChannelAccount",
    "ChannelIdentity",
    "Company",
    "DirectoryImport",
    "GmailSyncState",
    "Lease",
    "LeaseParty",
    "MessageRow",
    "ModelCall",
    "Outcome",
    "OwnerAccount",
    "Person",
    "RawEvent",
    "Send",
    "Timer",
    "UnderstandingRow",
    "Unit",
]
