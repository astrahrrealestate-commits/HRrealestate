# EstateOS

AI property-management assistant for one owner. It reads tenant and contractor WhatsApp and Gmail, links every message
to a case, and proposes typed actions with 2–3 drafts. The owner works only in the dashboard (approvals, inbox, Super
Agent chat); **nothing is sent to a tenant until the owner clicks approve**, and by default (`outbound_mode=draft`)
nothing leaves the machine at all.

| Part | Tech | Where |
|---|---|---|
| Backend API | FastAPI, PostgreSQL 16 + pgvector, SQLAlchemy 2, Alembic | `backend/app/` |
| Workflows / queues / cron | DBOS Transact on Postgres (no Redis, no Celery) | `backend/app/worker.py` |
| Agents | Pydantic AI (OpenAI / Gemini / Groq), Langfuse | `backend/app/llm/` |
| Dashboard | Next.js 16, React 19, Tailwind 4 | `frontend/` |

Out of the box everything runs **offline on fakes**: fake LLM, fake WhatsApp, fake Gmail, local file storage. You need
no API keys and no accounts to see it work.

---

## Quick start

```bash
git clone <repo-url> EstateOS && cd EstateOS
./start.sh
```

Then open **http://localhost:3000**. That is the whole setup.

`start.sh` checks your tools, creates `backend/.env` and `frontend/.env.local`, builds and starts the backend in Docker
(Postgres, migrations, API, worker), creates the dev company and owner, installs the dashboard dependencies and starts
the dashboard. The first run builds the Docker image and downloads packages, so expect a few minutes.

Prefer make? Same result:

```bash
make all        # check tools, create config, start backend, seed owner, install dashboard deps
make frontend   # dashboard on http://localhost:3000   (Ctrl-C stops only the dashboard)
```

Want a populated dashboard instead of an empty one?

```bash
./start.sh --demo     # also loads a mock portfolio and runs one scripted day through every agent
```

Stop and start again:

```bash
make stop             # stop the backend, keep data
./start.sh            # start everything again
make reset CONFIRM=yes   # stop AND wipe the local database and app data
```

### Prerequisites

| Tool | Version | Why | Install |
|---|---|---|---|
| Docker (with Compose v2) | any recent | runs Postgres, API, worker | [Docker Desktop](https://docs.docker.com/get-docker/) / Docker Engine |
| Node.js + npm | 20.9+ (22 LTS recommended) | dashboard | [nodejs.org](https://nodejs.org), or `nvm install 22` |
| make, curl | any | entry points | macOS: `xcode-select --install` · Debian/Ubuntu: `sudo apt install make curl` |
| uv | **exactly 0.12.5** | *optional*: tests, lint, migrations, `make setup` | `curl -LsSf https://astral.sh/uv/0.12.5/install.sh \| sh` |

Windows: use WSL2 with Docker Desktop's WSL integration and run everything inside WSL.
Run `make doctor` at any time to see what is missing; it also checks free disk and ports.

### What runs where

| Service | URL / port | Notes |
|---|---|---|
| Dashboard | http://localhost:3000 | must be port 3000: the API's dev CORS allows only that origin |
| API | http://localhost:8000 | Swagger at `/docs`, health at `/health/ready` |
| Postgres | `127.0.0.1:5433` | user/password/db: `estateos` (dev only). Override with `PG_PORT` |
| Worker | none | DBOS workflows, queues, cron |

**Login:** in `ENV=dev` the dashboard needs no login. The API uses the first owner in the database, which
`make seed` (run by `start.sh` and `make all`) creates. Without the seed the dashboard gets `401`.

---

## Configuration

`make env` copies `backend/.env.example` to `backend/.env` (never committed). The defaults need no edits. The ones you will touch:

| Variable | Default | Change it to |
|---|---|---|
| `LLM_MODEL` | `fake` | a real model, e.g. `google-gla:gemini-2.5-flash` or `openai:gpt-4.1-mini` |
| `GEMINI_API_KEY` / `OPENAI_API_KEY` / `GROQ_API_KEY` | empty | the key for the model you chose |
| `EMBEDDING_MODEL` | `fake` | `openai:text-embedding-3-small` or `google-gla:gemini-embedding-001` |
| `PG_PORT` / `API_PORT` | `5433` / `8000` | another port if one is taken |
| `WHATSAPP_PROVIDER`, `GMAIL_PROVIDER` | `fake` | real channels: see [docs/go-live-channels.md](docs/go-live-channels.md) |

After editing `backend/.env`, apply it with `make up`. The frontend reads `frontend/.env.local`
(`NEXT_PUBLIC_API_URL=http://localhost:8000`). Keep it on `localhost`, not `127.0.0.1`: the session cookie is
host-bound, and the dashboard and API must share a host.

Real Gmail/WhatsApp/S3 credentials, `ENV=prod` and the go-live checklist are in
[docs/go-live-channels.md](docs/go-live-channels.md). Production refuses fake providers on purpose.

---

## Everyday commands

`make help` lists everything. The ones you will use:

| Command | What it does |
|---|---|
| `make all` | fresh clone: doctor, config, backend up, seed, dashboard deps |
| `make start` / `./start.sh` | backend + seed + dashboard; `--backend-only`, `--demo` |
| `make up` / `make down` (`make stop`) | start / stop backend (Postgres, migrate, API, worker) |
| `make frontend` | dashboard dev server on :3000 |
| `make seed` | create dev company, channels and owner (idempotent) |
| `make logs` · `make ps` | tail logs · container status |
| `make sim-agents` | mock portfolio + one scripted day; prints calls per agent |
| `make sim-demo` | simulate WhatsApp + Gmail through the stack and assert the stored rows |
| `make pending` · `make approve n=1 choice=d1` | list / approve pending drafts from the terminal |
| `make migrate` · `make migration m="add x"` | apply / create Alembic migrations |
| `make workflows` | list recent DBOS workflows |
| `make requirements` | regenerate `backend/requirements*.txt` from `backend/uv.lock` |
| `make reset CONFIRM=yes` | wipe local database and app data |

Backend code in `backend/app/` is mounted into the containers: the API hot-reloads. The worker does **not**; after
changing workflow or agent code run `docker compose -f backend/docker/compose.yml restart worker`.

### Python without Docker (contributors)

The app runs in Docker, so you only need Python locally to run tests, lint and migrations.
[uv](https://docs.astral.sh/uv/) 0.12.5 manages Python 3.12 and the virtualenv for you:

```bash
make setup      # uv sync --frozen, pre-commit hooks, .env
make quick      # G1: ruff, format, mypy, import-linter, unit tests (no Docker)
make check      # G2: G1 + integration tests (testcontainers Postgres + DBOS, needs Docker)
make cov        # coverage floors
```

Prefer plain pip? `backend/requirements.txt` (runtime) and `backend/requirements-dev.txt` (dev tools) are exported
from `backend/uv.lock`:

```bash
cd backend
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
```

`backend/uv.lock` is the source of truth. After changing dependencies in `backend/pyproject.toml` run
`cd backend && uv lock` then `make requirements` from the repo root.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `make doctor` says port 5433 (or 8000, 3000) is taken | something else is listening. Stop it, or set `PG_PORT=` / `API_PORT=` in `backend/.env`. Find it with `lsof -nP -iTCP:5433 -sTCP:LISTEN`. Port 3000 cannot move (CORS) |
| Docker build or Postgres hangs, no error | disk is probably full. Check `df -h`, then `docker system df`; free space before retrying |
| `Cannot connect to the Docker daemon` | start Docker Desktop and wait until it says running |
| Dashboard shows `401` / empty data | backend not seeded or not running: `make up seed`; check `curl localhost:8000/health/ready` |
| Dashboard shows sample data but nothing real | it falls back to bundled mock data when the API is unreachable. Check the backend and `NEXT_PUBLIC_API_URL` |
| `uv` error about `required-version` | the repo pins uv 0.12.5. Install that version (link above) or just skip uv: running the app does not need it |
| `make frontend` fails on port 3000 | free port 3000; Next is started with `--port 3000` so it fails instead of hopping to another port |
| Code change not picked up by agents/workflows | restart the worker (see above) |
| Want a clean slate | `make reset CONFIRM=yes`, then `./start.sh` |

Logs: `make logs`. Workflow state: `make workflows`.

---

## Repository map

```
backend/          Python: FastAPI + DBOS. pyproject.toml, uv.lock, alembic.ini and .env.example live here too
  app/            api/v1 (dashboard API), channels, sender, llm, workflows, db (models, alembic), dev (simulator)
  tests/          unit, contract, integration, live
  evals/          golden-set agent evals (make eval)
  docker/         Dockerfile (production image) + compose.yml/compose.test.yml (dev and QA stacks)
frontend/         Next.js dashboard, its own Dockerfile and package.json — fully self-contained
scripts/          doctor.sh preflight
docs/             architecture, ADRs, specs, progress, deployment.md
```

## Docs

| Doc | Read when |
|---|---|
| [docs/hld.md](docs/hld.md) | architecture, flows, failure handling |
| [docs/tech-stack.md](docs/tech-stack.md) | which tool does what; check before writing plumbing |
| [docs/dashboard-api.md](docs/dashboard-api.md) | dashboard API, auth, limits |
| [docs/dev-pipeline.md](docs/dev-pipeline.md) | gates, test strategy, definition of done |
| [docs/go-live-channels.md](docs/go-live-channels.md) | real WhatsApp, Gmail, S3, production |
| [docs/deployment.md](docs/deployment.md) | deploying: the two images, their contract, how they're wired together |
| [docs/adr/](docs/adr/) | why DBOS, Pydantic AI, WhatsApp Cloud API, import-linter |
| [CLAUDE.md](CLAUDE.md) | invariants and conventions (also the contributor rules) |

## Safety defaults

- `outbound_mode` defaults to `draft`: drafts are stored and shown, never sent.
- Only `backend/app/sender/` can send, and only after the owner approves; the Super Agent can propose, never approve.
- Message content is treated as data, never as instructions. Recipients come from the database, not model output.
- `backend/.env` is git-ignored. Never commit credentials; Google token files live outside the repo in `~/.estateos`.
