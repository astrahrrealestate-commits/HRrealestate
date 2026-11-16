# Deployment

Two separately deployable units, each with its own production Docker image. Infrastructure choice (which AWS
service, or any other host) is not decided yet — this page is the contract each side needs regardless of where it
runs: what image to build, what it needs at boot, and how the two talk to each other. Real provider credentials
(WhatsApp, Gmail, S3, BRIXX, the LLM) are [docs/go-live-channels.md](go-live-channels.md); this page is the
container/runtime side, not the credentials side.

## Backend (`backend/docker/Dockerfile`)

One image, three roles picked by the command at run time — `backend/docker/compose.yml` shows the exact invocation
of each:

| Role | Command | Runs |
|---|---|---|
| migrate | `alembic upgrade head` | once per deploy, before `api`/`worker` start |
| api | `uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8000` | the FastAPI app |
| worker | `python -m app.worker` | DBOS workflows, queues, cron |

Build once, run the same image three ways (build context is `backend/`, not the repo root):

```bash
docker build -f backend/docker/Dockerfile -t estateos-backend backend
```

Non-root user, read-only application layer (only `/app/.data` is writable, and that path is dev-only — prod refuses
local storage), digest-pinned base images. Needs `DATABASE_URL` (Postgres 16 + pgvector) and `ENV=prod`; startup
(`app/core/startup.py: production_problems`) refuses to boot under `ENV=prod` with any fake provider, local storage,
or a missing required secret — a half-configured deploy fails at boot, not silently. Each `worker` replica needs its
own `DBOS__VMID` (`backend/docker/compose.yml` sets `worker-0`; a second replica needs a different id, ADR 0001).

## Frontend (`frontend/Dockerfile`)

Multi-stage production build (`npm run build` in a builder stage, Next's `output: "standalone"` server copied into a
minimal non-root runtime stage — not the dev server). Build with the public API origin baked in at build time
(`NEXT_PUBLIC_API_URL` is read client-side, so it must be a build arg, not a runtime environment variable):

```bash
docker build -f frontend/Dockerfile --build-arg NEXT_PUBLIC_API_URL=https://app.example.com -t estateos-frontend frontend
```

**Set `NEXT_PUBLIC_API_URL` to the SPA's own real public origin, always** — if it is left unset, the frontend code
falls back to `http://localhost:8000`, which only works on a dev machine. There is no "leave it empty for same
origin" option; set it explicitly even when both sides share a host.

## Wiring the two together

The default, and simplest, topology is **same-origin behind one reverse proxy**: the browser only ever talks to one
public host; the frontend's own server proxies `/api/*` to the backend (`frontend/next.config.ts`'s `rewrites()`,
using `INTERNAL_BACKEND_URL`, e.g. `http://backend:8000` on an internal network — never exposed publicly). This is
why `FRONTEND_BASE_URL` and `NEXT_PUBLIC_API_URL` end up equal in that topology: both name the one public origin.
Also set `GOOGLE_LOGIN_REDIRECT_URI` to that origin's `/api/auth/login/google/callback` if using Google login.

A split-host topology (separate `api.example.com` / `app.example.com`) also works, documented in
`backend/.env.example` right above `DASHBOARD_CORS_ORIGINS` and `DASHBOARD_COOKIE_DOMAIN` — needed only if the two
are not proxied same-origin.

## CI already proves both images build

`.github/workflows/ci.yml`'s `image` job builds the backend image and runs a Trivy CVE scan on every push to
`main`/`stage`/`dev`; the `frontend` job runs `npx tsc --noEmit`, `npm run lint` (advisory) and `npm run build`. A
green `ci-success` check means both sides are known to build; it does not build or push the frontend Docker image
(no step does yet — add one once a registry/target exists).

## What is intentionally not decided here

Which AWS service runs each container (ECS/Fargate, EC2, App Runner, …), autoscaling, the load balancer / TLS
termination point, and a registry + push step for the frontend image are all open. This page gives the two images
and their contract so that choice can be made independently of application code.

## Running on AWS ECS (stage and prod, `terraform/`)

The client deploy runs api, worker and the migrator as separate Fargate tasks from one ECR image (`deploy.yml`), with
the frontend on Vercel (split host: `estateos.hrrealestate.nl` → `api-estateos.hrrealestate.nl`). Things that only
show up there:

- **Owner Google tokens are shared through S3.** The Connections modal's Google connect runs in the api task, the
  Gmail poll in the worker task, and Fargate disks are thrown away on every deploy (and nightly on stage). With
  `STORAGE_BACKEND=s3` the tokens live at `credentials/google_owner.json` in the environment's bucket
  (`app/channels/google_store.py`); each process keeps `.data/credentials/google_owner.json` only as a cache refreshed
  every 30 s. A failed upload fails the connect instead of pretending it worked. The OAuth client secret is not
  stored there (re-added from Settings), and disconnect revokes the grant at Google. Tokens connected before this
  change lived only on a replaced task's disk: connect Google once after the deploy.
- **`ENV=dev` on AWS, on purpose for now.** `ENV=prod` refuses to boot until every channel is configured
  (`app/core/startup.py`: BRIXX, Google Chat, Drive and Gmail credentials files, WhatsApp secrets, Pub/Sub, price
  source). Cookies are still `Secure` there: a cookie is HTTPS-only whenever `GOOGLE_LOGIN_REDIRECT_URI` (the API's
  own public URL) is https. Switch to `ENV=prod` once the list in that refusal is empty.
- **LLM.** `LLM_MODEL` plus optional `LLM_FALLBACK_MODELS` (Pydantic AI `FallbackModel`, tried in order on a provider
  error; a fallback whose key is empty in Secrets Manager is skipped). On 2026-11-16 every agent call failed because
  the Gemini keys answered `402 RESOURCE_EXHAUSTED` (prepaid credits depleted); the key in Secrets Manager was
  replaced. Watch the Gemini project's credits. The next failure was `400 ... not enabled for api version v1`:
  google-genai 3.x defaults the Developer API to v1, which refuses system instructions and function calling; the code
  now pins v1beta (`app/llm/runtime.py: gemini_provider`) and the task definitions set
  `GOOGLE_GENAI_API_VERSION=v1beta` as well. Failures are now logged with the provider's status and message
  (`superagent.chat_failed`, `superagent.research_failed`, `api.superagent.llm_fallback`; key-shaped text scrubbed).
- **Task definitions vs terraform.** Terraform state is not in this repo (the S3 backend block is commented out), so a
  live change to a task definition must be mirrored in `terraform/environments/*/main.tf` or the next apply reverts it.
