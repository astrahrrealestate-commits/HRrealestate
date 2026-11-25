"""The draft report: how Harjot treated the drafts, per category and proposer prompt version, in counts only."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.contracts import ActionType, CaseState, Category, Channel, Direction, Urgency
from app.core.ids import new_id
from app.db.enums import ActionStatus, ApprovalStatus, OutcomeLabel, OutcomeSource
from app.db.models import (
    ActionRevision,
    ActionRow,
    Approval,
    Case,
    Company,
    MessageRow,
    ModelCall,
    Outcome,
    RawEvent,
)
from app.outcomes.draft_report import DraftReport, draft_report, render_report
from app.pipeline.propose import NO_USABLE_DRAFT

pytestmark = pytest.mark.integration
START = datetime(2026, 11, 1, 9, tzinfo=UTC)
SINCE, UNTIL = START - timedelta(days=1), START + timedelta(days=30)
SECRET = "Beste Anna, de loodgieter komt donderdag."


class Seed:
    def __init__(self, s: Session, cid: UUID) -> None:
        self.s, self.cid = s, cid

    def case(self, category: Category) -> UUID:
        c = Case(company_id=self.cid, state=CaseState.open, category=category, urgency=Urgency.normal)
        self.s.add(c)
        self.s.flush()
        return c.id

    def message(self, minutes_before: int, history: bool = False) -> UUID:
        raw = RawEvent(company_id=self.cid, provider=Channel.gmail, provider_msg_id=str(new_id()), payload={})
        self.s.add(raw)
        self.s.flush()
        msg = MessageRow(
            company_id=self.cid, raw_event_id=raw.id, channel=Channel.gmail, provider_msg_id=raw.provider_msg_id,
            thread_ref="t", sender_identity="a@x.test", direction=Direction.inbound, sent_at=START, text="vraag",
            meta={"history": True} if history else {}, created_at=START - timedelta(minutes=minutes_before),
        )  # fmt: skip
        self.s.add(msg)
        self.s.flush()
        return msg.id

    def draft(
        self, case: UUID, version: str | None, *, approval: ApprovalStatus | None = None, owner_edit: bool = False,
        minutes: int = 2, history: bool = False, outcome: OutcomeLabel | None = None,
    ) -> UUID:  # fmt: skip
        mid = self.message(minutes, history)
        payload = {"kind": "reply_draft", "channel": "gmail", "subject": None, "body_variants": [SECRET, "b"]}
        row = ActionRow(
            company_id=self.cid, case_id=case, type=ActionType.reply_draft, payload=payload, rationale="r",
            context_ref=[mid], draft_version=2 if owner_edit else 1, status=ActionStatus.proposed,
            prompt_version=version, created_at=START,
        )  # fmt: skip
        self.s.add(row)
        self.s.flush()
        if owner_edit:
            self.s.add(ActionRevision(company_id=self.cid, action_id=row.id, draft_version=2, payload=payload,
                                      edited_by="owner"))  # fmt: skip
        if approval is not None:
            self.s.add(Approval(company_id=self.cid, action_id=row.id, draft_version=row.draft_version,
                                status=approval, created_at=START))  # fmt: skip
        if outcome is not None:
            done = OutcomeSource.sent_folder
            self.s.add(Outcome(company_id=self.cid, action_id=row.id, draft_version=row.draft_version,
                               final_text=SECRET, label=outcome, similarity=0.9, source=done))  # fmt: skip
        self.s.flush()
        return row.id

    def no_usable(self, case: UUID, version: str) -> None:
        self.s.add(ActionRow(
            company_id=self.cid, case_id=case, type=ActionType.notify_owner,
            payload={"kind": "notify_owner", "text": NO_USABLE_DRAFT}, rationale="Draft rejected as generic",
            context_ref=[self.message(1)], prompt_version=version, created_at=START,
        ))  # fmt: skip

    def call(self, version: str, cost: str) -> None:
        self.s.add(ModelCall(
            company_id=self.cid, purpose="proposer", prompt_name="proposer", prompt_version=version,
            prompt_sha256="x" * 64, model="m", input={"prompt": SECRET}, cost_usd=Decimal(cost), created_at=START,
        ))  # fmt: skip


def _report(engine: Engine, cid: UUID) -> DraftReport:
    with Session(engine) as s:
        return draft_report(s, cid, since=SINCE, until=UNTIL)


def _seed(engine: Engine, cid: UUID) -> None:
    with Session(engine) as s, s.begin():
        seed = Seed(s, cid)
        repairs, money = seed.case(Category.maintenance), seed.case(Category.finance)
        seed.draft(repairs, "v6", approval=ApprovalStatus.approved, minutes=1, outcome=OutcomeLabel.unchanged)
        seed.draft(repairs, "v6", approval=ApprovalStatus.approved, owner_edit=True, minutes=3)
        seed.draft(repairs, "v6", approval=ApprovalStatus.rejected, minutes=5)
        seed.draft(repairs, "v6", approval=ApprovalStatus.expired, minutes=7)
        seed.draft(repairs, "v6", approval=ApprovalStatus.pending, minutes=9, history=True)
        seed.no_usable(repairs, "v6")
        seed.draft(money, None, approval=ApprovalStatus.approved, minutes=60)
        seed.call("v6", "0.010")
        seed.call("v6", "0.030")
        seed.call("v4", "0.002")


def _row(report: DraftReport, category: str, version: str) -> object:
    [row] = [r for r in report.rows if (r.category, r.prompt_version) == (category, version)]
    return row


def test_unedited_and_edited_approvals_are_counted_apart(migrated_engine: Engine, committed_company: Company) -> None:
    _seed(migrated_engine, committed_company.id)
    row = _row(_report(migrated_engine, committed_company.id), "maintenance", "v6")
    assert (row.offered, row.approved_unedited, row.approved_edited) == (5, 1, 1)  # type: ignore[attr-defined]
    assert (row.rejected, row.expired, row.pending) == (1, 1, 1)  # type: ignore[attr-defined]


def test_generic_drafts_dropped_are_counted(migrated_engine: Engine, committed_company: Company) -> None:
    _seed(migrated_engine, committed_company.id)
    assert _row(_report(migrated_engine, committed_company.id), "maintenance", "v6").no_usable == 1  # type: ignore[attr-defined]


def test_outcome_labels_are_reused(migrated_engine: Engine, committed_company: Company) -> None:
    _seed(migrated_engine, committed_company.id)
    row = _row(_report(migrated_engine, committed_company.id), "maintenance", "v6")
    assert row.outcomes == {"unchanged": 1}  # type: ignore[attr-defined]


def test_groups_by_category_and_prompt_version(migrated_engine: Engine, committed_company: Company) -> None:
    _seed(migrated_engine, committed_company.id)
    keys = {(r.category, r.prompt_version) for r in _report(migrated_engine, committed_company.id).rows}
    assert keys == {("maintenance", "v6"), ("finance", "before M13")}


def test_minutes_from_receipt_to_draft(migrated_engine: Engine, committed_company: Company) -> None:
    _seed(migrated_engine, committed_company.id)
    row = _row(_report(migrated_engine, committed_company.id), "maintenance", "v6")
    assert row.minutes_p50 == pytest.approx(4.0)  # type: ignore[attr-defined]
    assert row.minutes_p90 == pytest.approx(6.4)  # type: ignore[attr-defined]


def test_history_mail_is_not_counted_in_latency(migrated_engine: Engine, committed_company: Company) -> None:
    with Session(migrated_engine) as s, s.begin():
        seed = Seed(s, committed_company.id)
        seed.draft(seed.case(Category.legal), "v6", minutes=600, history=True)
    row = _row(_report(migrated_engine, committed_company.id), "legal", "v6")
    assert row.offered == 1  # type: ignore[attr-defined]
    assert row.minutes_p50 is None  # type: ignore[attr-defined]


def test_cost_per_prompt_version(migrated_engine: Engine, committed_company: Company) -> None:
    _seed(migrated_engine, committed_company.id)
    report = _report(migrated_engine, committed_company.id)
    assert report.cost_usd == {"v6": Decimal("0.040"), "v4": Decimal("0.002")}


def test_scoped_to_one_company(migrated_engine: Engine, committed_company: Company) -> None:
    with Session(migrated_engine) as s, s.begin():
        other = Company(name="Ander BV")
        s.add(other)
        s.flush()
        other_id = other.id
    _seed(migrated_engine, other_id)
    report = _report(migrated_engine, committed_company.id)
    assert (report.rows, report.cost_usd) == ([], {})


def test_output_has_no_message_text(migrated_engine: Engine, committed_company: Company) -> None:
    _seed(migrated_engine, committed_company.id)
    text = render_report(_report(migrated_engine, committed_company.id))
    assert "maintenance" in text
    assert "loodgieter" not in text
    assert "a@x.test" not in text


def test_the_command_prints_the_report_for_one_company(
    migrated_engine: Engine, committed_company: Company, capsys: pytest.CaptureFixture[str]
) -> None:
    from app.workflows.draft_report_cli import main

    with Session(migrated_engine) as s, s.begin():
        seed = Seed(s, committed_company.id)
        seed.draft(seed.case(Category.business), "v6", approval=ApprovalStatus.approved)
    assert main(["--company-id", str(committed_company.id), "--days", "3650"], engine=migrated_engine) == 0
    out = capsys.readouterr().out
    assert "business | v6 | 1 | 1 |" in out
    assert "loodgieter" not in out
