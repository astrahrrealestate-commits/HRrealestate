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
            text="Help! Grote water lekkage in de keuken!",
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
