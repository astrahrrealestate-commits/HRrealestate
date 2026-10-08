"""Integration test: pipeline_entry workflow triages message into understandings and model_calls."""

from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from dbos import DBOS
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.contracts import Category, Channel, Direction, Urgency
from app.core.ids import new_id
from app.core.settings import Settings
from app.db.enums import PipelineStatus
from app.db.models import Company, MessageRow, ModelCall, RawEvent, UnderstandingRow
from app.workflows import pipeline
from app.workflows.deps import set_engine
from app.workflows.runtime import launch

pytestmark = pytest.mark.integration
NOW = datetime(2026, 10, 7, 10, 0, tzinfo=UTC)


@pytest.fixture
def dbos_runtime(test_settings: Settings, migrated_engine: Engine) -> Iterator[None]:
    DBOS.destroy()
    launch(test_settings, reset_for_tests=True, schedules=False)
    set_engine(migrated_engine)
    yield
    set_engine(None)
    DBOS.destroy()


def test_pipeline_entry_understand(
    dbos_runtime: None,
    migrated_engine: Engine,
    committed_company: Company,
) -> None:
    cid = committed_company.id
    with Session(migrated_engine) as session, session.begin():
        raw = RawEvent(company_id=cid, provider=Channel.whatsapp, provider_msg_id=str(new_id()), payload={})
        session.add(raw)
        session.flush()

        msg = MessageRow(
            company_id=cid,
            raw_event_id=raw.id,
            channel=Channel.whatsapp,
            provider_msg_id=raw.provider_msg_id,
            thread_ref="thr-test",
            sender_identity="+31612345678",
            direction=Direction.inbound,
            sent_at=NOW,
            text="Help! Overstroming in de keuken, het water staat op de vloer!",
            meta={},
        )
        session.add(msg)
        session.flush()
        msg_id = msg.id

    # Run the workflow
    status = pipeline.pipeline_entry(str(msg_id))
    assert status == "understood"

    with Session(migrated_engine) as session:
        u_row = session.scalar(select(UnderstandingRow).where(UnderstandingRow.message_id == msg_id))
        assert u_row is not None
        assert u_row.category == Category.maintenance
        assert u_row.urgency == Urgency.emergency
        assert u_row.prompt_version == "understanding/v1"

        call_row = session.scalar(select(ModelCall).where(ModelCall.id == u_row.model_call_id))
        assert call_row is not None
        assert call_row.prompt_name == "understanding"
        assert call_row.model == "fake"
        assert call_row.error is None

        refreshed_msg = session.scalar(select(MessageRow).where(MessageRow.id == msg_id))
        assert refreshed_msg is not None
        assert refreshed_msg.pipeline_status == PipelineStatus.done

    # Replay workflow: must be idempotent and succeed
    status_replay = pipeline.pipeline_entry(str(msg_id))
    assert status_replay == "understood"

    with Session(migrated_engine) as session:
        u_count = len(session.scalars(select(UnderstandingRow).where(UnderstandingRow.message_id == msg_id)).all())
        assert u_count == 1


def test_failed_runs_are_requeued_until_three_attempts_and_success_clears_failed(
    dbos_runtime: None, migrated_engine: Engine, committed_company: Company, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pydantic_ai.messages import ModelResponse, ToolCallPart
    from pydantic_ai.models.function import FunctionModel

    from app.pipeline.understand import requeue_candidates

    cid = committed_company.id
    with Session(migrated_engine) as session, session.begin():
        raw = RawEvent(company_id=cid, provider=Channel.whatsapp, provider_msg_id=str(new_id()), payload={})
        session.add(raw)
        session.flush()
        msg = MessageRow(
            company_id=cid,
            raw_event_id=raw.id,
            channel=Channel.whatsapp,
            provider_msg_id=raw.provider_msg_id,
            thread_ref="+31611111111",
            sender_identity="+31611111111",
            direction=Direction.inbound,
            sent_at=NOW,
            text="Lekkage",
            meta={},
        )
        session.add(msg)
        session.flush()
        msg_id = msg.id
    bad = FunctionModel(lambda m, info: ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, {"x": 1})]))
    monkeypatch.setattr("app.llm.calls.build_model", lambda _s, _n: bad)
    assert pipeline.pipeline_entry(str(msg_id)) == "failed"
    sweep_at = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)
    assert [(m, wf) for m, wf in requeue_candidates(migrated_engine, sweep_at) if m == msg_id] == [
        (msg_id, f"pipe:{msg_id}:r1:2026100712")
    ]
    monkeypatch.undo()
    assert pipeline.pipeline_entry(str(msg_id)) == "understood"
    with Session(migrated_engine) as session:
        refreshed = session.get(MessageRow, msg_id)
        assert refreshed is not None
        assert (refreshed.pipeline_status, refreshed.pipeline_error) == (PipelineStatus.done, None)
    assert all(m != msg_id for m, _ in requeue_candidates(migrated_engine, datetime.now(UTC)))
    with Session(migrated_engine) as session, session.begin():
        row = session.get(MessageRow, msg_id)
        assert row is not None
        row.pipeline_status, row.pipeline_attempts = PipelineStatus.failed, 3
    assert all(
        m != msg_id for m, _ in requeue_candidates(migrated_engine, datetime.now(UTC))
    )  # gave up after 3 attempts


def _bad_model(monkeypatch: pytest.MonkeyPatch) -> None:
    from pydantic_ai.messages import ModelResponse, ToolCallPart
    from pydantic_ai.models.function import FunctionModel

    bad = FunctionModel(lambda m, info: ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, {"x": 1})]))
    monkeypatch.setattr("app.llm.calls.build_model", lambda _s, _n: bad)


def _inbound(engine: Engine, cid: object, text: str = "Lekkage", sender: str = "+31622222222") -> object:
    with Session(engine) as session, session.begin():
        raw = RawEvent(company_id=cid, provider=Channel.whatsapp, provider_msg_id=str(new_id()), payload={})
        session.add(raw)
        session.flush()
        msg = MessageRow(
            company_id=cid,
            raw_event_id=raw.id,
            channel=Channel.whatsapp,
            provider_msg_id=raw.provider_msg_id,
            thread_ref=sender,
            sender_identity=sender,
            direction=Direction.inbound,
            sent_at=NOW,
            text=text,
            meta={},
        )
        session.add(msg)
        session.flush()
        return msg.id


def test_understanding_failure_with_attempts_left_links_nothing(
    dbos_runtime: None, migrated_engine: Engine, committed_company: Company, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.db.models import CaseLink

    _bad_model(monkeypatch)
    msg_id = _inbound(migrated_engine, committed_company.id)
    assert pipeline.pipeline_entry(str(msg_id)) == "failed"
    with Session(migrated_engine) as session:
        assert session.scalar(select(CaseLink.id).where(CaseLink.message_id == msg_id)) is None


def test_final_understanding_failure_opens_an_other_case(
    dbos_runtime: None, migrated_engine: Engine, committed_company: Company, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.db.models import Case, CaseLink

    _bad_model(monkeypatch)
    msg_id = _inbound(migrated_engine, committed_company.id)
    with Session(migrated_engine) as session, session.begin():
        row = session.get(MessageRow, msg_id)
        assert row is not None
        row.pipeline_attempts = 2  # this is the third and last attempt
    assert pipeline.pipeline_entry(str(msg_id)) == "failed"
    with Session(migrated_engine) as session:
        category = session.scalar(
            select(Case.category).join(CaseLink, CaseLink.case_id == Case.id).where(CaseLink.message_id == msg_id)
        )
    assert category is Category.other


def test_unexpected_error_marks_the_message_failed_for_the_requeue(
    dbos_runtime: None, migrated_engine: Engine, committed_company: Company, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*_a: object, **_k: object) -> None:
        raise ValueError("bug in a later stage")

    monkeypatch.setattr("app.workflows.pipeline.link_message", boom)
    msg_id = _inbound(migrated_engine, committed_company.id)
    with pytest.raises(ValueError, match="bug in a later stage"):
        pipeline.pipeline_entry(str(msg_id))
    with Session(migrated_engine) as session:
        row = session.get(MessageRow, msg_id)
        assert row is not None
        assert (row.pipeline_status, row.pipeline_attempts) == (PipelineStatus.failed, 1)
        assert row.pipeline_error is not None
    monkeypatch.undo()  # the hourly requeue reruns it and the bug is gone: the message ends `done`, not `failed`
    assert pipeline.pipeline_entry(str(msg_id)) == "understood"
    with Session(migrated_engine) as session:
        row = session.get(MessageRow, msg_id)
        assert row is not None
        assert (row.pipeline_status, row.pipeline_error) == (PipelineStatus.done, None)


def test_inbound_message_stranded_in_pending_is_swept_but_owner_messages_are_not(
    migrated_engine: Engine, committed_company: Company
) -> None:
    from datetime import timedelta

    from app.db.models import OwnerAccount
    from app.pipeline.understand import requeue_candidates

    cid = committed_company.id
    tenant_msg = _inbound(migrated_engine, cid)
    with Session(migrated_engine) as session, session.begin():
        session.add(OwnerAccount(company_id=cid, display_name="Harjot", whatsapp_e164="+31600000999"))
    owner_msg = _inbound(migrated_engine, cid, sender="+31600000999")
    later = datetime.now(UTC) + timedelta(hours=2)
    swept = dict(requeue_candidates(migrated_engine, later))
    assert swept[tenant_msg] == f"pipe:{tenant_msg}:p{later:%Y%m%d%H}"
    assert owner_msg not in swept
    assert tenant_msg not in dict(requeue_candidates(migrated_engine, datetime.now(UTC)))  # too fresh
