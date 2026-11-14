"""resolve_page_facts against real Postgres: own ids become facts, another company's ids are dropped by kind only and
nothing of the other company (ids, names, message text, drafts, file names) appears in the rendered facts."""

from collections.abc import Iterator
from dataclasses import dataclass
from uuid import UUID

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.contracts import ActionType, PageContext
from app.db.enums import ActionStatus, ApprovalStatus
from app.db.models import ActionRow, Approval, AttachmentRow, Company, MessageRow
from app.pipeline.page_facts import facts_text, resolve_page_facts
from app.pipeline.read_repo import encode_thread_key
from tests.integration.concierge_support import seed_case, seed_task
from tests.integration.conftest import purge_company

pytestmark = pytest.mark.integration


@dataclass(frozen=True)
class World:
    cid: UUID
    case_id: UUID
    thread_key: str
    approval_id: UUID
    task_ref: str
    task_id: UUID
    attachment_id: UUID
    secret: str  # text only this company has


def _seed(engine: Engine, cid: UUID, secret: str) -> World:
    case_id, _ = seed_case(engine, cid, f"bericht {secret}")
    task_id, ref = seed_task(engine, cid, f"taak {secret}")
    with Session(engine) as s, s.begin():
        msg = s.scalars(select(MessageRow).where(MessageRow.company_id == cid)).one()
        action = ActionRow(
            company_id=cid, case_id=case_id, type=ActionType.reply_draft,
            payload={"body_variants": [f"draft {secret}", "tweede"]}, rationale="r", context_ref=[msg.id],
            status=ActionStatus.pending_approval,
        )  # fmt: skip
        s.add(action)
        s.flush()
        approval = Approval(company_id=cid, action_id=action.id, draft_version=1, status=ApprovalStatus.pending)
        attachment = AttachmentRow(
            company_id=cid, message_id=msg.id, s3_key=f"k/{secret}", mime_type="application/pdf",
            filename=f"{secret}.pdf", size_bytes=10, sha256="0" * 64,
        )  # fmt: skip
        s.add_all([approval, attachment])
        s.flush()
        key = encode_thread_key(msg.channel, msg.thread_ref or msg.provider_msg_id)
        return World(cid, case_id, key, approval.id, ref, task_id, attachment.id, secret)


@pytest.fixture
def worlds(migrated_engine: Engine, committed_company: Company) -> Iterator[tuple[World, World]]:
    with Session(migrated_engine, expire_on_commit=False) as s:
        other = Company(name="Foreign BV")
        s.add(other)
        s.commit()
    mine = _seed(migrated_engine, committed_company.id, "MINEONLY")
    theirs = _seed(migrated_engine, other.id, "THEIRSONLY")
    yield mine, theirs
    purge_company(migrated_engine, other.id)


def _page(w: World, view: str = "case") -> PageContext:
    return PageContext.model_validate(
        {
            "view": view,
            "case_id": str(w.case_id),
            "thread_key": w.thread_key,
            "approval_id": str(w.approval_id),
            "task_ref": w.task_ref,
            "attachment_id": str(w.attachment_id),
            "visible_ids": [str(w.case_id), w.task_ref, w.thread_key, str(w.approval_id), str(w.attachment_id)],
        }
    )


def test_own_ids_resolve_to_facts(migrated_engine: Engine, worlds: tuple[World, World]) -> None:
    mine = worlds[0]
    with Session(migrated_engine) as s:
        facts = resolve_page_facts(s, mine.cid, _page(mine))
    assert facts.dropped == ()
    assert facts.case is not None
    assert facts.case.case_id == mine.case_id
    assert facts.thread is not None
    assert facts.thread.case_id == mine.case_id
    assert facts.approval is not None
    assert facts.approval.drafts[0] == "draft MINEONLY"
    assert facts.approval.suspicious is False
    assert facts.task is not None
    assert facts.task.ref == mine.task_ref
    assert facts.document is not None
    assert facts.document.filename == "MINEONLY.pdf"
    assert len(facts.visible) == 5
    text = facts_text(facts)
    assert "MINEONLY" in text
    assert "THEIRSONLY" not in text


def test_foreign_ids_are_dropped_and_never_leak(migrated_engine: Engine, worlds: tuple[World, World]) -> None:
    mine, theirs = worlds
    with Session(migrated_engine) as s:
        facts = resolve_page_facts(s, mine.cid, _page(theirs))
    assert (facts.case, facts.thread, facts.approval, facts.task, facts.document) == (None,) * 5
    assert facts.visible == ()
    assert facts.dropped == ("case", "thread", "approval", "task", "document", "visible")
    text = facts_text(facts)
    for leaked in ("THEIRSONLY", str(theirs.case_id), str(theirs.approval_id), theirs.task_ref, theirs.thread_key):
        assert leaked not in text


def test_mixed_visible_ids_label_only_own_rows(migrated_engine: Engine, worlds: tuple[World, World]) -> None:
    mine, theirs = worlds
    page = PageContext.model_validate(
        {"view": "tasks", "visible_ids": [str(theirs.task_id), str(mine.task_id), theirs.task_ref, str(mine.case_id)]}
    )
    with Session(migrated_engine) as s:
        facts = resolve_page_facts(s, mine.cid, page)
    assert facts.visible == (
        f"task #{mine.task_ref} | taak MINEONLY | open",
        f"case {mine.case_id} | Sanne · maintenance | open",
    )
    assert facts.dropped == ("visible",)
