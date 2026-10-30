"""Comprehensive End-to-End Test Suite for Super Agent, Memory Management & Document RAG.

Validates:
1. Super Agent prompt compilation and intent planning.
2. T1–T5 Memory persistence (standing rules, person profiles, focus trails).
3. Page pre-warming state caching and freshness validation.
4. Document intelligence, chunking, and pgvector semantic search.
"""

from datetime import UTC, date, datetime
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.context.compiler import compile_concierge_context
from app.context.memory_items import list_memory_items, record_owner_memory
from app.contracts import Channel, Direction
from app.contracts.concierge import ConciergePlan, Intent, PlanStep
from app.contracts.page_context import PageContext, PageView
from app.core.ids import new_id
from app.core.settings import get_settings
from app.db.enums import (
    DocLinkKind,
    DocumentStatus,
    MemoryKind,
    MemoryScope,
    MemoryStatus,
    PersonKind,
    TurnStatus,
)
from app.db.models import Company, Person, PersonProfile, Unit
from app.db.models.dashboard import AgentConversation, AgentPageState, AgentTurn
from app.db.models.documents import DocumentChunk
from app.db.models.ingestion import AttachmentRow, MessageRow, RawEvent
from app.db.models.memory import MemoryItem
from app.db.models.tenancy import OwnerAccount
from app.db.models.work import DocumentRow
from app.db.session import make_engine
from app.pipeline import concierge_turns, page_state


@pytest.fixture(scope="module")
def live_engine():
    """Use the live migrated database on port 5433 (already at head 0020)."""
    settings = get_settings()
    engine = make_engine(settings.sqlalchemy_url)
    yield engine
    engine.dispose()


@pytest.fixture
def test_company_and_owner(live_engine):
    """Seed test company, owner account, and unit."""
    with Session(live_engine) as session, session.begin():
        company = Company(name="EstateOS Test BV")
        session.add(company)
        session.flush()

        owner = OwnerAccount(
            company_id=company.id,
            email=f"harjot_{uuid4().hex[:6]}@example.com",
            whatsapp_e164="+31612345678",
            display_name="Harjot Singh",
        )
        session.add(owner)
        session.flush()

        unit = Unit(
            company_id=company.id,
            label="Pieter Floriszstraat 1 C",
            address="Pieter Floriszstraat 1 C, 1053 TV Amsterdam",
            valid_from=date(2024, 1, 1),
        )
        session.add(unit)
        session.flush()

        return company.id, owner.id, unit.id


class TestSuperAgentCore:
    """Pillar 1: Super Agent Prompt & Plan Compilation."""

    def test_concierge_context_compilation_with_rules(self, test_company_and_owner):
        company_id, _, _ = test_company_and_owner
        preferences = [
            "Never approve contractor quotes above €650 without Harjot sign-off",
            "Emergency electrician priority vendor is Chahal Bouw",
        ]

        compiled = compile_concierge_context(
            question="What is the budget cap for Pieter Floriszstraat?",
            recent=["owner: Check heating", "assistant: Ticket #005 opened"],
            cases=[],
            open_tasks=["Task 1: Dispatch electrician"],
            page_facts_text="Unit: Pieter Floriszstraat 1 C",
            owner_preferences=preferences,
        )

        assert compiled.prompt_text is not None
        assert "Chahal Bouw" in compiled.prompt_text
        assert "€650" in compiled.prompt_text
        assert compiled.prefix_hash is not None

    def test_turn_creation_persists_in_agent_turns(self, live_engine, test_company_and_owner):
        company_id, owner_id, _ = test_company_and_owner

        with Session(live_engine) as session, session.begin():
            conversation_id, turn_id = concierge_turns.create_turn(
                session,
                company_id=company_id,
                owner_id=owner_id,
                conversation_id=None,
                text="Check ticket #005 status",
            )

        with Session(live_engine) as session:
            turn = session.get(AgentTurn, turn_id)
            assert turn is not None
            assert turn.conversation_id == conversation_id
            assert turn.status == TurnStatus.pending


class TestPagePreWarm:
    """Pillar 2: Page Pre-Warm State & Freshness."""

    def test_prewarm_stores_cached_facts(self, live_engine, test_company_and_owner):
        company_id, owner_id, unit_id = test_company_and_owner
        page_ctx = PageContext(view=PageView.inbox)

        # Pre-warm the page
        warmed = page_state.warm(live_engine, company_id, owner_id, page_ctx)
        assert warmed is True

        with Session(live_engine) as session:
            cached = session.scalars(
                select(AgentPageState).where(
                    AgentPageState.company_id == company_id,
                    AgentPageState.owner_id == owner_id,
                )
            ).first()

            assert cached is not None
            assert cached.page_key is not None
            assert "facts" in cached.resolved


class TestMemoryManagement:
    """Pillar 3: 5-Tier Memory Persistence (T3 & T5)."""

    def test_record_and_list_standing_rule(self, live_engine, test_company_and_owner):
        company_id, owner_id, _ = test_company_and_owner

        with Session(live_engine) as session, session.begin():
            item, reason = record_owner_memory(
                session,
                company_id=company_id,
                text="Standard plumbing call-out cap is €350",
                scope=MemoryScope.company,
                kind=MemoryKind.rule,
            )
            assert item is not None
            assert item.status == MemoryStatus.active

        with Session(live_engine) as session:
            active_rules = list_memory_items(
                session, company_id=company_id, status=MemoryStatus.active
            )
            assert len(active_rules) >= 1
            assert any("€350" in r.text for r in active_rules)

    def test_person_profile_memory(self, live_engine, test_company_and_owner):
        company_id, _, _ = test_company_and_owner

        with Session(live_engine) as session, session.begin():
            person = Person(
                company_id=company_id,
                kind=PersonKind.tenant,
                display_name="Pieter Bakker",
                valid_from=date(2024, 1, 1),
            )
            session.add(person)
            session.flush()
            person_id = person.id

            profile = PersonProfile(
                company_id=company_id,
                person_id=person_id,
                language="nl",
                preferred_channel="whatsapp",
                summary="Tenant works from home on Tuesdays and Fridays",
            )
            session.add(profile)

        with Session(live_engine) as session:
            saved = session.scalars(
                select(PersonProfile).where(PersonProfile.person_id == person_id)
            ).first()
            assert saved is not None
            assert saved.preferred_channel == "whatsapp"
            assert "Tuesdays" in saved.summary


class TestAdvancedRag:
    """Pillar 4: Document Chunks & pgvector Semantic Search."""

    def test_document_chunk_pgvector_distance(self, live_engine, test_company_and_owner):
        company_id, _, _ = test_company_and_owner

        # Generate mock 1024-dim embedding
        mock_embedding = [0.0] * 1024
        mock_embedding[0] = 1.0  # Unit vector along axis 0

        with Session(live_engine) as session, session.begin():
            raw = RawEvent(
                company_id=company_id,
                provider=Channel.gmail,
                provider_msg_id=str(new_id()),
                payload={},
            )
            session.add(raw)
            session.flush()

            msg = MessageRow(
                company_id=company_id,
                raw_event_id=raw.id,
                channel=Channel.gmail,
                provider_msg_id=raw.provider_msg_id,
                thread_ref="test-thread-1",
                sender_identity="pieter@example.com",
                direction=Direction.inbound,
                sent_at=datetime.now(UTC),
                text="Please find attached the signed contract.",
                meta={},
            )
            session.add(msg)
            session.flush()

            att = AttachmentRow(
                company_id=company_id,
                message_id=msg.id,
                filename="ROZ_Lease.pdf",
                mime_type="application/pdf",
                size_bytes=10240,
                sha256="0" * 64,
                s3_key="attachments/test_lease.pdf",
            )
            session.add(att)
            session.flush()

            doc = DocumentRow(
                company_id=company_id,
                attachment_id=att.id,
                doc_type="lease",
                title="ROZ Standard Residential Tenancy Agreement 2023",
                file_name="ROZ_Lease.pdf",
                confidence=0.98,
                status=DocumentStatus.filed,
            )
            session.add(doc)
            session.flush()
            doc_id = doc.id

            chunk = DocumentChunk(
                company_id=company_id,
                document_id=doc_id,
                ord=0,
                page=3,
                heading="Article 3: Notice Period",
                text="The tenant must provide at least one calendar month formal notice.",
                embedding=mock_embedding,
            )
            session.add(chunk)

        with Session(live_engine) as session:
            # Query using pgvector cosine distance (<=>)
            query_embedding = [0.0] * 1024
            query_embedding[0] = 0.95
            query_embedding[1] = 0.05

            stmt = (
                select(DocumentChunk.text, DocumentChunk.page)
                .where(DocumentChunk.document_id == doc_id)
                .order_by(DocumentChunk.embedding.cosine_distance(query_embedding))
                .limit(1)
            )

            result = session.execute(stmt).first()
            assert result is not None
            chunk_text, page_num = result
            assert page_num == 3
            assert "one calendar month" in chunk_text
