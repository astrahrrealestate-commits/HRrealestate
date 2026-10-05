# M1 Foundation Implementation Plan

> **For agentic workers:** Execute task-by-task with the `/ship` skill (RED → GREEN → REFACTOR → G1 → G2 → review →
> commit). Steps use checkbox (`- [ ]`) syntax. Execution mode chosen by user: **native, via /ship**.

**Goal:** A repo where `make smoke` brings up Postgres, migrate, API and a DBOS worker; the first migration creates all
24 domain tables; the six contracts are tested; G1/G2 gates and CI are green.

**Architecture:** One Python package `app/` layered per `docs/hld.md` §3 and enforced by import-linter. FastAPI serves
health; DBOS runs workflows in a separate worker process against the same Postgres (schema `dbos`). Tests: unit (no
I/O) and integration (testcontainers Postgres 16, real Alembic migrations, real DBOS).

**Tech Stack:** Python 3.12, uv, FastAPI, SQLAlchemy 2 + Alembic + psycopg 3, Pydantic v2 + pydantic-settings, DBOS
Transact, structlog, Sentry, phonenumbers, email-validator, uuid-utils; pytest, pytest-xdist, pytest-socket,
hypothesis, polyfactory, testcontainers, ruff, mypy, import-linter, pre-commit, pip-audit.

**Spec:** `docs/superpowers/specs/2026-10-05-estateos-m1-foundation-design.md` (+ `docs/hld.md`, `docs/tech-stack.md`)

## Global Constraints

- Python `>=3.12,<3.13`; dependencies via `uv` only; `uv.lock` committed.
- Every domain table: `id uuid` PK (UUIDv7 from `app.core.ids.new_id`), `created_at timestamptz default now()`,
  `company_id uuid not null` FK → `companies.id` (except `companies`).
- Enums stored as `VARCHAR` + CHECK (`sa.Enum(..., native_enum=False, create_constraint=True)`), values = `StrEnum` values.
- All datetimes timezone-aware; money `Decimal` + ISO-4217 code.
- Contracts: `ConfigDict(frozen=True, extra="forbid")`.
- No Redis, no Celery. Workflows = DBOS. API never executes workflows.
- Local Postgres host port **5433**. Tests never use the network except localhost + Docker unix socket.
- Ruff line length 120. mypy strict.

## Review Focus

1. **Odd sender identities**: `"0151 2345 6789"`, `"+49 (151) 2345-6789"`, `" Tenant@Example.DE "` normalise to E.164 /
   lowercase; `"hello"`, `"+49 1"` are rejected. Tested in Task 3.
2. **Naive datetimes** (`datetime(2026,1,1)`) passed as `sent_at` are rejected, not silently treated as UTC. Task 3.
3. **Malformed button ids** (`"apr:x:ok"`, `"apr:<uuid>:OK"`, `"apr:<uuid>:ok:extra"`, `" apr:<uuid>:ok"`, `""`) raise
   `InvalidButtonId` and nothing else. Hypothesis fuzz in Task 3.
4. **Double inserts** on every unique constraint (raw_events, messages, sends, timers, channel_identities current row)
   raise `IntegrityError`; a *historical* channel identity (valid_to set) may repeat. Task 5.
5. **Migration round-trip twice** leaves no orphan objects (CHECK constraints, indexes). Task 5 runs up/down/up and
   `alembic check`.

---

### Task 1: Tooling, package skeleton, gates runnable

**Files:**
- Create: `pyproject.toml`, `uv.lock` (generated), `alembic.ini`, `app/__init__.py`, every package `__init__.py` from
  hld §3 (`api, channels, channels/whatsapp, channels/gmail, ingestion, workflows, pipeline, owner, sender, directory,
  outcomes, llm, storage, db, db/models, contracts, core`), `app/pipeline/rules.py` (docstring only — anchors the
  purity contract), `app/channels/whatsapp/outbound.py`, `app/channels/gmail/outbound.py` (docstring only — anchor
  the send-isolation contract), `tests/__init__.py`, `tests/unit/__init__.py`, `tests/integration/__init__.py`,
  `evals/__init__.py`
- Test: `tests/unit/test_package.py`

**Interfaces:**
- Produces: `app.__version__: str`; `make quick` / `make setup` runnable; import-linter contracts:
  1. layers `app.main | app.worker` > `app.api` > `app.workflows` > `app.pipeline | app.owner | app.ingestion |
     app.directory | app.outcomes | app.sender` > `app.db : app.llm : app.storage : app.channels` > `app.contracts` >
     `app.core`
  2. forbidden: every `app.*` package except `app.sender` must not import `app.channels.whatsapp.outbound`,
     `app.channels.gmail.outbound`, `app.sender.settings`
  3. forbidden: `app.pipeline.rules` must not import `app.db`, `app.llm`, `app.channels`, `app.storage`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_package.py
import app


def test_version_is_semver() -> None:
    parts = app.__version__.split(".")
    assert len(parts) == 3
    assert all(p.isdigit() for p in parts)
```

- [ ] **Step 2: Run** `uv run pytest tests/unit/test_package.py -q` → FAIL (no project / module).
- [ ] **Step 3: Implement** `pyproject.toml` (deps + `[tool.ruff]`, `[tool.mypy]` strict + `pydantic.mypy`,
  `[tool.pytest.ini_options]` with `addopts = "--disable-socket --allow-unix-socket --allow-hosts=127.0.0.1,localhost,::1 --strict-markers"`,
  markers `integration`, `[tool.coverage]` `fail_under = 85` branch, `[tool.importlinter]` contracts above), package
  skeleton, `app/__init__.py` with `__version__ = "0.1.0"`. `uv lock && uv sync`.
- [ ] **Step 4: Run** `make quick` → PASS (ruff, format, mypy, lint-imports "Contracts: 3 kept", 1 passed).
- [ ] **Step 5: Commit** `build(m1): project tooling, package skeleton, architecture contracts`

---

### Task 2: Core — settings, ids, errors, logging, telemetry

**Files:**
- Create: `app/core/settings.py`, `app/core/ids.py`, `app/core/errors.py`, `app/core/logging.py`,
  `app/core/telemetry.py`, `app/sender/settings.py`
- Test: `tests/unit/core/test_settings.py`, `tests/unit/core/test_ids.py`, `tests/unit/core/test_logging.py`

**Interfaces:**
- Produces:
  - `class Settings(BaseSettings)`: `env: Literal["dev","test","prod"]="dev"`, `database_url: PostgresDsn`,
    `api_port: int = 8000`, `app_version: str = app.__version__`, `pipeline_concurrency: int = 4`,
    `sentry_dsn: str | None = None`, `langfuse_host/public_key/secret_key: str | None`, `s3_*: str | None`,
    `openai_api_key: SecretStr | None`; property `dbos_database_url -> str` (driver stripped to `postgresql://`).
    `get_settings() -> Settings` (lru_cache).
  - `class SenderSettings(BaseSettings)` in `app/sender/settings.py`: `whatsapp_access_token: SecretStr | None`,
    `whatsapp_phone_number_id: str | None`, `gmail_send_credentials_file: Path | None`.
  - `new_id() -> uuid.UUID` (version 7).
  - errors: `EstateOSError(Exception)`, `IllegalTransition(EstateOSError)`, `InvalidButtonId(EstateOSError, ValueError)`,
    `PromptNotFound(EstateOSError)`, `NotFound(EstateOSError)`, `TenantMismatch(EstateOSError)`.
  - `configure_logging(env: str) -> None` (JSON renderer unless env == "dev"); `get_logger(name) -> structlog BoundLogger`.
  - `init_telemetry(settings: Settings) -> None` (Sentry init iff dsn; no-op otherwise).

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/core/test_ids.py
import uuid

from app.core.ids import new_id


def test_new_id_is_uuid7_and_time_ordered() -> None:
    ids = [new_id() for _ in range(50)]
    assert all(isinstance(i, uuid.UUID) and i.version == 7 for i in ids)
    assert ids == sorted(ids)
    assert len(set(ids)) == 50
```

```python
# tests/unit/core/test_settings.py
import pytest
from pydantic import ValidationError

from app.core.settings import Settings


def test_dbos_url_strips_driver(monkeypatch: pytest.MonkeyPatch) -> None:
    s = Settings(database_url="postgresql+psycopg://u:p@localhost:5433/db")  # type: ignore[arg-type]
    assert s.dbos_database_url == "postgresql://u:p@localhost:5433/db"


def test_database_url_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)  # type: ignore[call-arg]


def test_secret_not_in_repr() -> None:
    s = Settings(database_url="postgresql+psycopg://u:p@h/db", openai_api_key="sk-test-123")  # type: ignore[arg-type]
    assert "sk-test-123" not in repr(s)
```

```python
# tests/unit/core/test_logging.py
import json

import pytest

from app.core.logging import configure_logging, get_logger


def test_json_logs_in_prod(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("prod")
    get_logger("t").info("hello", company_id="c1")
    line = capsys.readouterr().out.strip().splitlines()[-1]
    record = json.loads(line)
    assert record["event"] == "hello"
    assert record["company_id"] == "c1"
    assert record["level"] == "info"
    assert "timestamp" in record
```

- [ ] **Step 2: Run** `uv run pytest tests/unit/core -q` → FAIL (modules missing).
- [ ] **Step 3: Implement** the modules above (`uuid_utils.compat.uuid7` for ids; structlog with
  `merge_contextvars`, `add_log_level`, `TimeStamper(fmt="iso", utc=True)`, `JSONRenderer` / `ConsoleRenderer`,
  `PrintLoggerFactory`).
- [ ] **Step 4: Run** `make quick` → PASS.
- [ ] **Step 5: Commit** `feat(m1): core settings, ids, errors, logging, telemetry`

---

### Task 3: The six contracts

**Files:**
- Create: `app/contracts/__init__.py` (re-exports), `common.py` (`Money`, `Channel`, `Direction`), `message.py`,
  `understanding.py`, `action.py`, `case_state.py`, `button_id.py`, `prompt_ref.py`
- Test: `tests/unit/contracts/test_message.py`, `test_understanding.py`, `test_action.py`, `test_case_state.py`,
  `test_button_id.py`, `test_prompt_ref.py`

**Interfaces:**
- Consumes: `app.core.errors.IllegalTransition`, `InvalidButtonId`.
- Produces (all frozen, extra=forbid):
  - `Channel(StrEnum)`: `whatsapp, gmail`; `Direction(StrEnum)`: `inbound, outbound`;
    `Money(amount: Decimal[max_digits=12, decimal_places=2], currency: str ^[A-Z]{3}$)`
  - `Attachment(s3_key: str, mime_type: str, filename: str | None, size_bytes: int >= 0, sha256: str ^[0-9a-f]{64}$)`
  - `Message(channel, provider_msg_id: str min1, thread_ref: str | None, sender_identity: str, direction,
    sent_at: AwareDatetime, text: str, attachments: list[Attachment] = [], raw_event_id: UUID, company_id: UUID)`;
    `normalise_identity(value: str, default_region: str = "DE") -> str` (module function, used by validator)
  - `Category(StrEnum)`: `maintenance, payment, lease, complaint, contractor_update, admin, spam, other`;
    `Urgency(StrEnum)`: `emergency, high, normal, low`; `Entities(people, unit_refs, dates: list[date | str],
    amounts: list[Money])` all default `[]`; `Suspicious(flag: bool, reason: str | None)`;
    `Understanding(category, intent: str max200, urgency, entities, suspicious, confidence: float [0,1],
    prompt_version: str ^[a-z][a-z0-9_]*/v\d+$)`
  - `ActionType(StrEnum)`: `reply_draft, notify_owner, create_reminder, update_case_state, request_contractor,
    escalate`; payload models with `kind: Literal[...]`; `ActionPayload = Annotated[Union[...], Field(discriminator="kind")]`;
    `Action(type, case_id: UUID, payload, rationale: str min1, context_ref: list[UUID], draft_version: int >= 1)`
  - `CaseState(StrEnum)`: `open, waiting_on_owner, waiting_on_third_party, resolved, closed`;
    `ALLOWED: Mapping[CaseState, frozenset[CaseState]]`; `can_transition(a, b) -> bool`; `assert_transition(a, b) -> None`
  - `ButtonChoice(StrEnum)`: `ok, edit, rej, d1, d2, d3`; `ButtonId(approval_id: UUID, choice)` with
    `ButtonId.parse(raw: str) -> ButtonId` and `.render() -> str`; `MAX_BUTTON_ID_LEN = 256`
  - `PromptRef(name: str ^[a-z][a-z0-9_]*$, version: str ^v\d+$)` with `.key -> "name/version"` and
    `.relative_path -> Path("vN/name.md")`

- [ ] **Step 1: Write failing tests** (excerpt; each file covers its contract)

```python
# tests/unit/contracts/test_message.py
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.contracts import Channel, Direction, Message, normalise_identity

BASE = dict(channel=Channel.whatsapp, provider_msg_id="wamid.TEST1", thread_ref=None, direction=Direction.inbound,
            sent_at=datetime(2026, 1, 1, tzinfo=UTC), text="Heizung kaputt", raw_event_id=uuid4(), company_id=uuid4())


@pytest.mark.parametrize(("raw", "expected"), [
    ("0151 2345 6789", "+4915123456789"),
    ("+49 (151) 2345-6789", "+4915123456789"),
    ("  Tenant@Example.DE ", "tenant@example.de"),
])
def test_identity_normalised(raw: str, expected: str) -> None:
    assert normalise_identity(raw) == expected
    assert Message(**BASE, sender_identity=raw).sender_identity == expected


@pytest.mark.parametrize("raw", ["hello", "+49 1", "", "a@", "@b.de"])
def test_identity_rejected(raw: str) -> None:
    with pytest.raises(ValidationError):
        Message(**BASE, sender_identity=raw)


def test_naive_datetime_rejected() -> None:
    with pytest.raises(ValidationError):
        Message(**{**BASE, "sent_at": datetime(2026, 1, 1)}, sender_identity="+4915123456789")


def test_round_trip_and_frozen() -> None:
    m = Message(**BASE, sender_identity="+4915123456789")
    assert Message.model_validate_json(m.model_dump_json()) == m
    with pytest.raises(ValidationError):
        m.text = "x"  # type: ignore[misc]
```

```python
# tests/unit/contracts/test_case_state.py
import itertools

import pytest

from app.contracts import CaseState as S, assert_transition, can_transition
from app.core.errors import IllegalTransition

LEGAL = {
    (S.open, S.waiting_on_owner), (S.open, S.waiting_on_third_party), (S.open, S.resolved), (S.open, S.closed),
    (S.waiting_on_owner, S.open), (S.waiting_on_owner, S.resolved), (S.waiting_on_owner, S.closed),
    (S.waiting_on_third_party, S.open), (S.waiting_on_third_party, S.resolved), (S.waiting_on_third_party, S.closed),
    (S.resolved, S.open), (S.resolved, S.closed),
}


@pytest.mark.parametrize(("a", "b"), list(itertools.product(S, S)))
def test_full_matrix(a: S, b: S) -> None:
    assert can_transition(a, b) is ((a, b) in LEGAL)
    if (a, b) in LEGAL:
        assert_transition(a, b)
    else:
        with pytest.raises(IllegalTransition):
            assert_transition(a, b)
```

```python
# tests/unit/contracts/test_button_id.py
from uuid import uuid4

import pytest
from hypothesis import given, strategies as st

from app.contracts import ButtonChoice, ButtonId, MAX_BUTTON_ID_LEN
from app.core.errors import InvalidButtonId


def test_round_trip_all_choices() -> None:
    for c in ButtonChoice:
        b = ButtonId(approval_id=uuid4(), choice=c)
        raw = b.render()
        assert len(raw) <= MAX_BUTTON_ID_LEN
        assert ButtonId.parse(raw) == b


@pytest.mark.parametrize("raw", ["", "apr:x:ok", "apr:{u}:OK", "apr:{u}:ok:extra", " apr:{u}:ok", "rej:{u}:ok",
                                 "apr:{u}:", "apr::ok"])
def test_malformed(raw: str) -> None:
    with pytest.raises(InvalidButtonId):
        ButtonId.parse(raw.format(u=uuid4()))


@given(st.text(max_size=300))
def test_fuzz_never_other_error(raw: str) -> None:
    try:
        ButtonId.parse(raw)
    except InvalidButtonId:
        pass
```

```python
# tests/unit/contracts/test_action.py
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.contracts import Action, ActionType, Channel


def _reply(**kw: object) -> dict[str, object]:
    return {"kind": "reply_draft", "channel": Channel.gmail, "to": "tenant@example.de", "subject": "Re: Heizung",
            "body_variants": ["a", "b"], **kw}


def test_valid_reply_draft_round_trip() -> None:
    a = Action(type=ActionType.reply_draft, case_id=uuid4(), payload=_reply(), rationale="tenant asked",
               context_ref=[uuid4()], draft_version=1)
    assert Action.model_validate_json(a.model_dump_json()) == a


def test_type_payload_mismatch_rejected() -> None:
    with pytest.raises(ValidationError):
        Action(type=ActionType.escalate, case_id=uuid4(), payload=_reply(), rationale="x", context_ref=[], draft_version=1)


@pytest.mark.parametrize("variants", [["only one"], ["a", "b", "c", "d"]])
def test_variant_count(variants: list[str]) -> None:
    with pytest.raises(ValidationError):
        Action(type=ActionType.reply_draft, case_id=uuid4(), payload=_reply(body_variants=variants), rationale="x",
               context_ref=[], draft_version=1)


def test_draft_version_min_one() -> None:
    with pytest.raises(ValidationError):
        Action(type=ActionType.reply_draft, case_id=uuid4(), payload=_reply(), rationale="x", context_ref=[],
               draft_version=0)
```

```python
# tests/unit/contracts/test_understanding.py
import pytest
from pydantic import ValidationError

from app.contracts import Category, Entities, Suspicious, Understanding, Urgency


def _u(**kw: object) -> Understanding:
    base: dict[str, object] = dict(category=Category.maintenance, intent="report broken heating", urgency=Urgency.high,
                                   entities=Entities(), suspicious=Suspicious(flag=False, reason=None), confidence=0.9,
                                   prompt_version="understanding/v1")
    return Understanding(**{**base, **kw})


def test_round_trip() -> None:
    u = _u()
    assert Understanding.model_validate_json(u.model_dump_json()) == u


@pytest.mark.parametrize(("flag", "reason"), [(True, None), (True, ""), (False, "why")])
def test_suspicious_reason_iff_flag(flag: bool, reason: str | None) -> None:
    with pytest.raises(ValidationError):
        Suspicious(flag=flag, reason=reason)


@pytest.mark.parametrize("kw", [{"confidence": 1.1}, {"confidence": -0.1}, {"intent": "x" * 201},
                                {"prompt_version": "v1"}])
def test_bounds(kw: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        _u(**kw)


def test_json_schema_usable_as_llm_output_schema() -> None:
    schema = Understanding.model_json_schema()
    assert schema["additionalProperties"] is False
```

```python
# tests/unit/contracts/test_prompt_ref.py
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.contracts import PromptRef


def test_paths() -> None:
    r = PromptRef(name="understanding", version="v1")
    assert r.key == "understanding/v1"
    assert r.relative_path == Path("v1/understanding.md")


@pytest.mark.parametrize(("name", "version"), [("../etc", "v1"), ("Understanding", "v1"), ("u", "1"), ("u", "v1/..")])
def test_rejects_traversal_and_bad_names(name: str, version: str) -> None:
    with pytest.raises(ValidationError):
        PromptRef(name=name, version=version)
```

- [ ] **Step 2: Run** `uv run pytest tests/unit/contracts -q` → FAIL (imports).
- [ ] **Step 3: Implement** contracts per Interfaces. Identity: contains `@` → `email_validator.validate_email(
  check_deliverability=False).normalized.lower()`; else `phonenumbers.parse(v, "DE")`, require `is_valid_number`,
  format E164; else raise `ValueError`.
- [ ] **Step 4: Run** `make quick` → PASS.
- [ ] **Step 5: Commit** `feat(m1): six pipeline contracts with property tests`

---

### Task 4: DB base, 22 models, integration test infra

**Files:**
- Create: `app/db/base.py` (naming convention, `Base`, mixins), `app/db/session.py`, `app/db/models/__init__.py`,
  `app/db/models/{tenancy,directory,ingestion,pipeline,owner,ops}.py`, `tests/conftest.py`,
  `tests/integration/conftest.py`, `tests/factories.py`
- Test: `tests/unit/db/test_models_metadata.py`

**Interfaces:**
- Consumes: `new_id`, contracts enums (`Channel, Direction, Category, Urgency, CaseState, ActionType`).
- Produces:
  - `Base(DeclarativeBase)` with `metadata = MetaData(naming_convention={"ix": "ix_%(column_0_label)s", "uq":
    "uq_%(table_name)s_%(column_0_N_name)s", "ck": "ck_%(table_name)s_%(constraint_name)s", "fk":
    "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s", "pk": "pk_%(table_name)s"})`
  - mixins `IdMixin` (`id: Mapped[UUID]` default `new_id`), `CreatedAtMixin` (`server_default=func.now()`),
    `CompanyScoped` (`company_id` FK `companies.id` ondelete RESTRICT, indexed), `Validity` (`valid_from: date`,
    `valid_to: date | None`)
  - `str_enum(enum_cls) -> sa.Enum` helper (`native_enum=False, create_constraint=True, length=32,
    values_callable=lambda e: [m.value for m in e]`, name = snake of enum)
  - 22 mapped classes, table names exactly as spec §3: `Company, ChannelAccount, OwnerAccount, GmailSyncState,
    DirectoryImport, Person, ChannelIdentity, Unit, Lease, LeaseParty, RawEvent, MessageRow, AttachmentRow,
    UnderstandingRow, Case, CaseLink, CaseEvent, ActionRow, ActionRevision, Approval, Send, Timer, Outcome, ModelCall`
    (24 tables — the spec table lists 24 rows; earlier prose saying "22" was a miscount and is corrected)
  - `make_engine(url: str) -> Engine` (pool_pre_ping) and `session_factory(engine) -> sessionmaker[Session]`
  - fixtures: `pg_url` (session; testcontainers `postgres:16-alpine`, driver psycopg), `migrated_engine` (session;
    alembic upgrade head), `db` (function; connection-level transaction + `Session(join_transaction_mode=
    "create_savepoint")`, rolled back), `company` (function; inserted `Company`)
  - `recorded(provider: str, scenario: str) -> bytes` fixture loader (unit conftest)

- [ ] **Step 1: Write failing test**

```python
# tests/unit/db/test_models_metadata.py
from app.db.base import Base
import app.db.models  # noqa: F401  (registers tables)

SPEC_TABLES = {
    "companies", "channel_accounts", "owner_accounts", "gmail_sync_state", "directory_imports", "people",
    "channel_identities", "units", "leases", "lease_parties", "raw_events", "messages", "attachments",
    "understandings", "cases", "case_links", "case_events", "actions", "action_revisions", "approvals", "sends",
    "timers", "outcomes", "model_calls",
}


def test_exact_table_set() -> None:
    assert set(Base.metadata.tables) == SPEC_TABLES


def test_every_domain_table_company_scoped_with_uuid_pk_and_created_at() -> None:
    for name, table in Base.metadata.tables.items():
        assert [c.name for c in table.primary_key.columns] == ["id"], name
        assert "created_at" in table.c, name
        if name != "companies":
            assert "company_id" in table.c and not table.c.company_id.nullable, name


def test_critical_unique_constraints_present() -> None:
    def uniques(t: str) -> set[tuple[str, ...]]:
        table = Base.metadata.tables[t]
        out = {tuple(c.name for c in u.columns) for u in table.constraints if u.__class__.__name__ == "UniqueConstraint"}
        out |= {tuple(c.name for c in i.columns) for i in table.indexes if i.unique}
        return out
    assert ("provider", "provider_msg_id") in uniques("raw_events")
    assert ("channel", "provider_msg_id") in uniques("messages")
    assert ("idempotency_key",) in uniques("sends")
    assert ("dedupe_key",) in uniques("timers")
    assert ("company_id", "channel", "identity") in uniques("channel_identities")
    assert ("message_id",) in uniques("case_links")
    assert ("action_id", "draft_version") in uniques("action_revisions")
```

- [ ] **Step 2: Run** `uv run pytest tests/unit/db -q` → FAIL.
- [ ] **Step 3: Implement** base, mixins, models (columns per spec §3 table; FKs to parent rows with indexes;
  `channel_identities` partial unique index `postgresql_where=valid_to IS NULL`; jsonb via
  `sqlalchemy.dialects.postgresql.JSONB`; money/cost `Numeric`), session helpers, conftest fixtures, factories.
- [ ] **Step 4: Run** `make quick` → PASS.
- [ ] **Step 5: Commit** `feat(m1): SQLAlchemy models for all phase-1 tables + test db fixtures`

---

### Task 5: Alembic + first migration + constraint integration tests

**Files:**
- Create: `app/db/alembic/env.py`, `app/db/alembic/script.py.mako`, `app/db/alembic/versions/0001_initial.py`
  (autogenerated, then hand-reviewed per `/new-migration`)
- Test: `tests/integration/test_migrations.py`, `tests/integration/test_constraints.py`

**Interfaces:**
- Consumes: `Base.metadata`, `Settings.database_url`, fixtures `pg_url`, `migrated_engine`, `db`, `company`.
- Produces: `alembic upgrade head` creates everything; `alembic_config(url: str) -> alembic.config.Config` helper in
  `tests/integration/conftest.py`.

- [ ] **Step 1: Write failing tests**

```python
# tests/integration/test_migrations.py
import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect

from app.db.base import Base
import app.db.models  # noqa: F401
from tests.integration.conftest import alembic_config

pytestmark = pytest.mark.integration


def test_roundtrip(pg_url: str) -> None:
    cfg = alembic_config(pg_url)
    for _ in range(2):
        command.upgrade(cfg, "head")
        command.downgrade(cfg, "base")
        leftover = set(inspect(create_engine(pg_url)).get_table_names()) - {"alembic_version"}
        assert leftover == set()
    command.upgrade(cfg, "head")


def test_drift(migrated_engine) -> None:  # type: ignore[no-untyped-def]
    with migrated_engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == []
```

```python
# tests/integration/test_constraints.py
from datetime import UTC, date, datetime

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.contracts import Channel
from app.db.models import ChannelIdentity, Person, RawEvent, Send, Timer
from app.db.models.tenancy import Company

pytestmark = pytest.mark.integration


def _twice(db: Session, make) -> None:  # type: ignore[no-untyped-def]
    db.add(make()); db.flush()
    db.add(make())
    with pytest.raises(IntegrityError):
        db.flush()


def test_raw_event_dedupe(db: Session, company: Company) -> None:
    _twice(db, lambda: RawEvent(company_id=company.id, provider="whatsapp", provider_msg_id="wamid.T1", payload={}))


def test_send_idempotency(db: Session, company: Company) -> None:
    _twice(db, lambda: Send(company_id=company.id, idempotency_key="exec:a:1", channel=Channel.gmail, target="t"))


def test_timer_dedupe(db: Session, company: Company) -> None:
    _twice(db, lambda: Timer(company_id=company.id, kind="briefing", due_at=datetime(2026, 1, 1, tzinfo=UTC),
                             payload={}, dedupe_key="briefing:2026-01-01"))


def test_identity_current_unique_but_history_allowed(db: Session, company: Company) -> None:
    p = Person(company_id=company.id, kind="tenant", display_name="Tenant 1", valid_from=date(2025, 1, 1))
    db.add(p); db.flush()
    old = ChannelIdentity(company_id=company.id, person_id=p.id, channel=Channel.whatsapp, identity="+4915550000001",
                          valid_from=date(2024, 1, 1), valid_to=date(2024, 12, 31))
    cur = ChannelIdentity(company_id=company.id, person_id=p.id, channel=Channel.whatsapp, identity="+4915550000001",
                          valid_from=date(2025, 1, 1))
    db.add_all([old, cur]); db.flush()
    db.add(ChannelIdentity(company_id=company.id, person_id=p.id, channel=Channel.whatsapp,
                           identity="+4915550000001", valid_from=date(2025, 6, 1)))
    with pytest.raises(IntegrityError):
        db.flush()


def test_enum_check_rejects_unknown_value(db: Session, company: Company) -> None:
    from sqlalchemy import text
    with pytest.raises(IntegrityError):
        db.execute(text("INSERT INTO sends (id, company_id, idempotency_key, channel, target, status) "
                        "VALUES (gen_random_uuid(), :c, 'k', 'telegram', 't', 'pending')"), {"c": company.id})
```

- [ ] **Step 2: Run** `uv run pytest tests/integration -q` → FAIL (no alembic env / revision).
- [ ] **Step 3: Implement** alembic env (url from `-x url=` or `Settings`; `target_metadata = Base.metadata`;
  `compare_type=True`; exclude schema `dbos`), `make up-db`, `uv run alembic revision --autogenerate --rev-id 0001 -m
  initial`, review file (partial index where-clause, CHECK constraints, downgrade order).
- [ ] **Step 4: Run** `make check` → PASS.
- [ ] **Step 5: Commit** `feat(m1): initial alembic migration with roundtrip, drift and constraint tests`

---

### Task 6: DBOS app, worker process, timer-sweep schedule

**Files:**
- Create: `app/workflows/runtime.py` (DBOS config + launch helpers), `app/workflows/queues.py`,
  `app/workflows/system.py` (`selfcheck`, `timer_sweep`), `app/worker.py`
- Test: `tests/integration/test_worker.py`

**Interfaces:**
- Consumes: `Settings.dbos_database_url`, `Settings.app_version`, `Settings.pipeline_concurrency`.
- Produces:
  - `dbos_config(settings) -> DBOSConfig` (`name="estateos"`, `system_database_url`, `application_version`)
  - `PIPELINE_QUEUE: Queue` (`"pipeline"`, `worker_concurrency=settings.pipeline_concurrency`)
  - `@DBOS.workflow(name="system.selfcheck") selfcheck() -> str` returns `"ok"`
  - `@DBOS.workflow(name="system.timer_sweep") timer_sweep(scheduled_time: datetime, context: Any) -> int` (M1: returns 0)
  - `register_schedules() -> None` (idempotent; `timer_sweep` every minute)
  - `app.worker.main(argv: list[str] | None = None) -> int`: no flag → launch + block; `--selfcheck` →
    `DBOSClient.enqueue({"queue_name": "pipeline", "workflow_name": "system.selfcheck"})` and wait ≤30 s, exit 0 iff `"ok"`
  - `enqueue_options(workflow_name: str, workflow_id: str | None = None) -> EnqueueOptions` helper for the API (M2)

- [ ] **Step 1: Write failing tests**

```python
# tests/integration/test_worker.py
import pytest
from dbos import DBOS, DBOSClient

from app.workflows.queues import PIPELINE_QUEUE
from app.workflows.system import selfcheck

pytestmark = pytest.mark.integration


def test_selfcheck_runs_directly(dbos_runtime: None) -> None:
    assert selfcheck() == "ok"


def test_enqueue_via_client_executes_on_worker(dbos_runtime: None, dbos_url: str) -> None:
    client = DBOSClient(system_database_url=dbos_url)
    try:
        h = client.enqueue({"queue_name": PIPELINE_QUEUE.name, "workflow_name": "system.selfcheck",
                            "workflow_id": "selfcheck-test-1"}, )
        assert h.get_result() == "ok"
        # same workflow id again = same workflow, executed once
        h2 = client.enqueue({"queue_name": PIPELINE_QUEUE.name, "workflow_name": "system.selfcheck",
                             "workflow_id": "selfcheck-test-1"})
        assert h2.get_result() == "ok"
        assert len(DBOS.list_workflows(workflow_ids=["selfcheck-test-1"])) == 1
    finally:
        client.destroy()


def test_timer_sweep_noop(dbos_runtime: None) -> None:
    from datetime import UTC, datetime
    from app.workflows.system import timer_sweep
    assert timer_sweep(datetime.now(UTC), None) == 0
```

  plus fixtures `dbos_url` and `dbos_runtime` (DBOS.destroy → DBOS(config) → `reset_system_database(truncate=True)`
  → launch → yield → destroy) in `tests/integration/conftest.py`.
- [ ] **Step 2: Run** `uv run pytest tests/integration/test_worker.py -q` → FAIL.
- [ ] **Step 3: Implement** runtime, queues, system workflows, worker CLI (argparse). Verify `create_schedule` /
  scheduled-workflow API against the installed `dbos` source before using it.
- [ ] **Step 4: Run** `make check` → PASS.
- [ ] **Step 5: Commit** `feat(m1): dbos runtime, pipeline queue, worker with selfcheck and timer sweep`

---

### Task 7: FastAPI app + health endpoints

**Files:**
- Create: `app/main.py` (app factory), `app/api/health.py`, `app/api/deps.py`
- Test: `tests/unit/api/test_health_live.py`, `tests/integration/test_health_ready.py`

**Interfaces:**
- Consumes: `get_settings`, `make_engine`, `configure_logging`, `init_telemetry`.
- Produces: `create_app(settings: Settings | None = None, engine: Engine | None = None) -> FastAPI`;
  module-level `app = create_app()` only under `if __name__`-free lazy factory (`uvicorn app.main:create_app --factory`);
  `GET /health/live` → `200 {"status":"ok","version":...}`; `GET /health/ready` → `200 {"status":"ready"}` if
  `SELECT 1` succeeds, else `503 {"status":"unavailable","checks":{"database":"error"}}`.
  (DBOS system tables are not checked by the API: the API does not run DBOS. Readiness of the worker is proven by
  `python -m app.worker --selfcheck`.)

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/api/test_health_live.py
from unittest.mock import MagicMock

from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.core.settings import Settings
from app.main import create_app

SETTINGS = Settings(database_url="postgresql+psycopg://u:p@localhost:1/db", env="test")  # type: ignore[arg-type]


def test_live_needs_no_db() -> None:
    r = TestClient(create_app(SETTINGS, engine=MagicMock())).get("/health/live")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_ready_503_when_db_down() -> None:
    engine = MagicMock()
    engine.connect.side_effect = OperationalError("SELECT 1", {}, Exception("down"))
    r = TestClient(create_app(SETTINGS, engine=engine)).get("/health/ready")
    assert r.status_code == 503
    assert r.json()["checks"]["database"] == "error"
```

```python
# tests/integration/test_health_ready.py
import pytest
from fastapi.testclient import TestClient

from app.core.settings import Settings
from app.main import create_app

pytestmark = pytest.mark.integration


def test_ready_with_real_db(pg_url: str, migrated_engine) -> None:  # type: ignore[no-untyped-def]
    app = create_app(Settings(database_url=pg_url, env="test"), engine=migrated_engine)  # type: ignore[arg-type]
    r = TestClient(app).get("/health/ready")
    assert r.status_code == 200
    assert r.json() == {"status": "ready"}
```

- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4:** `make check` → PASS.
- [ ] **Step 5: Commit** `feat(m1): fastapi app factory with live/ready health`

---

### Task 8: Dockerfile + compose + smoke

**Files:**
- Create: `docker/Dockerfile`, `docker/compose.yml`, `.dockerignore`
- Modify: `Makefile` (smoke uses compose service names below)

**Interfaces:**
- Produces: image with roles via command: `migrate` (`alembic upgrade head`), `api`
  (`uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8000`), `worker` (`python -m app.worker`). Compose
  services `postgres` (16-alpine, host 5433, healthcheck `pg_isready`), `migrate` (depends postgres healthy), `api`
  (depends migrate completed_successfully; healthcheck python urllib on `/health/ready`), `worker` (depends migrate).
  Non-root user, `uv sync --frozen --no-dev` in builder stage, `PYTHONDONTWRITEBYTECODE=1`, `PYTHONUNBUFFERED=1`.

- [ ] **Step 1: Failing check:** `make smoke` → FAIL (no compose file).
- [ ] **Step 2: Implement** Dockerfile (multi-stage, `ghcr.io/astral-sh/uv` binary copy), compose, `.dockerignore`.
- [ ] **Step 3: Run** `make smoke` → `api ready: ok`, `worker: ok`, `logs: clean`.
- [ ] **Step 4: Commit** `build(m1): docker image and compose stack with smoke gate`

---

### Task 9: CI

**Files:**
- Create: `.github/workflows/ci.yml`, `.github/dependabot.yml`

**Interfaces:**
- Produces: jobs `quality` (uv setup → `make quick`), `integration` (`make test-int`, Docker available on
  ubuntu-latest), `security` (`make audit` + gitleaks action), `image` (docker build). Triggers: push to `m*-*`
  branches and PRs to `main`. Concurrency cancel-in-progress.

- [ ] **Step 1:** Validate YAML locally: `uv run pre-commit run check-yaml --all-files` → PASS.
- [ ] **Step 2:** `act` is not required; CI runs when the branch is pushed (push needs user approval).
- [ ] **Step 3: Commit** `ci(m1): github actions for gates, security and image build`

---

### Task 10: Close M1

- [ ] `make cov` → total ≥ 85 % (quote line)
- [ ] `make audit` → no known vulnerabilities (quote line)
- [ ] `make smoke` → three ok lines
- [ ] `estateos-reviewer` on `git diff main...m1-foundation` → `VERDICT: ship`
- [ ] Tick M1 in `docs/PROGRESS.md` with evidence; `superpowers:finishing-a-development-branch`
