"""Same tenant report over WhatsApp and Gmail → equivalent normalised rows; the simulator drives the real API."""

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest
from dbos import DBOS, DBOSClient
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.channels import registry
from app.core.settings import Settings
from app.core.workflow_names import event_workflow_id
from app.db.models import RawEvent
from app.dev.demo import send_scenario, wait_for_parity
from app.dev.seed import DevTenant, seed_dev_tenant
from app.dev.simulate import Simulator
from app.ingestion.process import IngestDeps
from app.main import create_app
from app.storage.factory import build_storage
from app.workflows.deps import DEV_TOPIC, set_deps
from app.workflows.runtime import launch
from tests.integration.conftest import purge_company

pytestmark = pytest.mark.integration


@dataclass
class Stack:
    sim: Simulator
    tenant: DevTenant
    client: DBOSClient
    engine: Engine


@pytest.fixture
def stack(test_settings: Settings, migrated_engine: Engine, tmp_path: Path) -> Iterator[Stack]:
    """API (TestClient) + in-process DBOS executor + settings-built fake providers sharing one data directory."""
    settings = test_settings.model_copy(
        update={"storage_local_dir": tmp_path / "data", "dev_signing_dir": tmp_path / "keys"}
    )
    DBOS.destroy()
    launch(settings, reset_for_tests=True, schedules=False)
    client = DBOSClient(system_database_url=settings.dbos_database_url)
    set_deps(
        IngestDeps(
            engine=migrated_engine,
            storage=build_storage(settings),
            enqueuer=client,
            gmail_mailbox=lambda address: registry.gmail_mailbox(settings, address),
            whatsapp_media=lambda pnid: registry.whatsapp_media(settings, pnid),
            gmail_topic=DEV_TOPIC,
        )
    )
    tenant = seed_dev_tenant(migrated_engine)
    app = create_app(settings, engine=migrated_engine, workflow_client=client)
    try:
        with TestClient(app) as http:
            yield Stack(Simulator(settings, http), tenant, client, migrated_engine)
    finally:
        set_deps(None)
        client.destroy()
        DBOS.destroy()
        purge_company(migrated_engine, tenant.company_id)


def test_whatsapp_and_gmail_yield_equivalent_rows(stack: Stack) -> None:
    sent = send_scenario(stack.sim, stack.tenant.company_id)
    assert wait_for_parity(stack.engine, stack.client, sent, timeout=60) == []
    # one raw event per provider message (2 WhatsApp + 2 Gmail + 1 owner button), one workflow per raw event
    with Session(stack.engine) as s:
        raw_ids = s.scalars(select(RawEvent.id).where(RawEvent.company_id == stack.tenant.company_id)).all()
    assert len(raw_ids) == 5
    outcomes = [stack.client.retrieve_workflow(event_workflow_id(r)).get_result() for r in raw_ids]
    assert outcomes == ["processed"] * 5
    assert len(stack.client.list_workflows(workflow_id_prefix="evt:")) == 5


def test_seed_is_idempotent(stack: Stack) -> None:
    assert seed_dev_tenant(stack.engine) == stack.tenant
